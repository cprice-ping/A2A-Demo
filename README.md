# A2A-Demo: Flight + Hotel Agents (Google ADK · A2A · AG-UI)

A hands-on exploration of the [A2A protocol](https://a2a-protocol.org) with two [Google ADK](https://adk.dev) agents — **Flight Search/Booking** and **Hotel Search/Booking** — each exposing itself over **A2A** (agent card + JSON-RPC) and **AG-UI** (streaming chat + widget tools), plus a **Travel Planner** host agent that delegates to both over A2A.

```
                          ┌────────────────────┐
   Chat UI (CopilotKit)   │  travel-planner    │  delegates over A2A
   ui/ :5173  ───────────▶│  :8082 (AG-UI/A2A) │──────┬───────────┐
        AG-UI SSE         └────────────────────┘      │ A2A JSON-RPC
                                                          ▼
┌────────────────────────┐                  ┌────────────────────────┐
│ flight-agent  :8080    │                  │ hotel-agent   :8081    │
│  /api   mock REST API  │                  │  /api   mock REST API  │
│  /mcp   MCP server     │                  │  /mcp   MCP server     │
│  /a2a   A2A + card     │◀── agent cards ──│  /a2a   A2A + card     │
│  /agui  AG-UI chat     │                  │  /agui  AG-UI chat     │
└────────────────────────┘                  └────────────────────────┘
 Cloud Run + Vertex AI                        Kubernetes (kind)
 (SA auth — no API key)                       (GOOGLE_API_KEY secret)
```

Each domain agent stacks three layers on one ASGI app: mock REST API (representative data) → MCP server (domain tools for the LLM) → ADK agent exposed over both A2A and AG-UI.

## The three surfaces of an agent (per domain container)

| Path | Protocol | What it's for |
|---|---|---|
| `/api` | REST | The mock domain API (search/book/get) — the "backend system" |
| `/mcp` | MCP (streamable HTTP) | Domain tools the agent's LLM calls |
| `/a2a` | A2A JSON-RPC | Agent-to-agent: other agents delegate here. Card at `/a2a/.well-known/agent-card.json` |
| `/agui` | AG-UI (SSE) | The chat UI's streaming endpoint |

Each domain agent runs **two instances of the same brain**: `root_agent` serves `/agui` (calls `render_*` frontend tools that the browser renders as cards) and `a2a_agent` serves `/a2a` (no frontend tools — returns raw JSON so an *agent caller* can render). Same tools/MCP either way.

The planner wraps each specialist in an `AgentTool(RemoteA2aAgent(...))` so it stays in control of the loop: call flight → get JSON → call hotel → get JSON → render both cards.

## Quick start (all local, keyless model calls via your Google login)

```bash
# 1. One-time auth (enables Vertex-backed model calls without any API key)
gcloud auth application-default login

# 2. Terminal 1 — flight agent (:8080)
cd flight-agent
GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=<your-project> \
  uv run uvicorn flight_agent.main:app --port 8080

# 3. Terminal 2 — hotel agent (:8081)
cd hotel-agent
GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=<your-project> \
  uv run uvicorn hotel_agent.main:app --port 8081

# 4. Terminal 3 — planner (:8082)
cd travel-planner
GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=<your-project> \
FLIGHT_AGENT_CARD_URL=http://localhost:8080/a2a/.well-known/agent-card.json \
HOTEL_AGENT_CARD_URL=http://localhost:8081/a2a/.well-known/agent-card.json \
  uv run uvicorn travel_planner.main:app --port 8082

# 5. Terminal 4 — chat UI (:5173)
cd ui && npm install && npm run dev
```

Open http://localhost:5173 and try:

- **Flight tab**: "Find flights SFO → JFK on 2026-09-20 for 2 passengers"
- **Hotel tab**: "Hotels in NYC for 2 nights from 2026-09-20"
- **Planner tab**: "Plan a trip: flight SFO→JFK on 2026-09-20 for 2, plus a hotel in NYC for 2 nights" — watch it delegate to both specialists over A2A

## docker-compose

```bash
# .env in repo root:
#   GOOGLE_API_KEY=<ai-studio key>     # hotel agent (the only key in the demo)
#   GOOGLE_CLOUD_PROJECT=<project>     # flight agent + planner (Vertex/ADC)
docker compose up --build
```

Same ports as above. The flight agent and planner mount your `application_default_credentials.json` — no key; the hotel agent takes `GOOGLE_API_KEY`.

## Deployment

### Flight agent → Cloud Run (Vertex AI backend, no API key)

```bash
cd flight-agent
./deploy-cloud-run.sh
```

The script enables APIs, creates a `flight-agent-run` service account with `roles/aiplatform.user`, deploys from source, then bootstraps `PUBLIC_BASE_URL` to the service's real URL (the agent card must advertise it). Model calls authenticate with the service account — no key material anywhere.

### Hotel agent → Kubernetes (kind verified; any cluster works)

```bash
brew install kind && kind create cluster --name a2a-demo
docker build -t hotel-agent:local ./hotel-agent
kind load docker-image hotel-agent:local --name a2a-demo

kubectl apply -f hotel-agent/k8s/namespace.yaml
kubectl -n a2a-demo create secret generic hotel-agent-secrets \
  --from-literal=GOOGLE_API_KEY=<your-key>     # replaces the placeholder
kubectl apply -f hotel-agent/k8s/

kubectl -n a2a-demo port-forward svc/hotel-agent 8081:80
```

Manifests: namespace, secret, deployment (probes on `/api/health`, 512Mi–1Gi), ClusterIP service.

### Hybrid

Any card URL works anywhere — point the planner's `FLIGHT_AGENT_CARD_URL` at Cloud Run and `HOTEL_AGENT_CARD_URL` at the port-forwarded kind service and the planner spans both platforms. (For compose↔host mixes use `host.docker.internal`.)

## Configuration (env vars)

| Var | Where | Purpose |
|---|---|---|
| `GOOGLE_GENAI_USE_VERTEXAI=true` | any agent | Model calls via Vertex AI (ADC auth) instead of Gemini API key |
| `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` | Vertex agents | Vertex project/region |
| `GOOGLE_API_KEY` | hotel agent (k8s/compose) | Gemini API key (the demo's only key) |
| `PUBLIC_BASE_URL` | all agents | URL other parties use to reach this agent — drives the card's advertised endpoint |
| `MCP_SELF_URL` | domain agents | The agent's own MCP server URL (default `http://localhost:<port>/mcp`) |
| `FLIGHT_AGENT_CARD_URL` / `HOTEL_AGENT_CARD_URL` | planner | Full card URLs of the specialists |
| `CORS_ORIGINS` | all agents | Comma-separated allowed origins (default `http://localhost:5173`) |
| `VITE_FLIGHT_AGENT_URL` / `VITE_HOTEL_AGENT_URL` / `VITE_PLANNER_AGENT_URL` | ui (build time) | Override `/agui` endpoints; also acceptable as query params `?flightAgent=...` |

## Tests

```bash
cd flight-agent && uv run pytest   # 19 tests: schedule synthesis + REST API
cd hotel-agent && uv run pytest    # 11 tests: data enrichment + REST API
```

No LLM tests — model calls are exercised manually/via the chat UI.

## Notable implementation details (gotchas worth knowing)

- **Mounted sub-app lifespans don't run automatically.** Both FastMCP's session manager AND `to_a2a()`'s route attachment live in their sub-app lifespans — the parent must drive both (see `main.py` in either domain agent; a fresh `to_a2a()` app has an *empty router* until its lifespan runs).
- **The card's JSON-RPC URL needs a trailing slash** (`http://host:8080/a2a/`) — a2a clients don't follow the 307 from `/a2a`.
- **RemoteA2aAgent rejects plain-http card URLs** unless the host is loopback — container-network names (`flight-agent:8080`) fail at card fetch. Fix: fetch the card JSON yourself and pass the `AgentCard` object (ADK explicitly leaves direct-card transport to the caller — right for a trusted container network).
- **CopilotKit agent selection**: the v1 `CopilotSidebar` resolves its agent from the v1 `agent` prop, not the v2 `agentId` — pass both (`<CopilotKit agent={id} agentId={id} selfManagedAgents={...}>`), else it looks for a nonexistent `'default'` agent.
- **a2a-sdk 1.x is protobuf-based**: `AgentCard` uses `supported_interfaces` (list of `AgentInterface`), not a flat `url` field.
- **fastmcp 2.x, not 4.x**: fastmcp 4 requires `mcp>=2` which hard-conflicts with google-adk's `mcp>=1.24,<2` pin. 2.14.x matches exactly.
- **CopilotKit**: the v1 `agents` prop is gone in 1.71 — use `selfManagedAgents` + `agentId` (v2 wiring) with direct `HttpAgent` connections (no CopilotKit runtime needed).
- **MCP self-connection works** (agent → its own `/mcp`): the session opens lazily at request time, after startup.
- Deterministic schedule synthesis: same `(origin, destination, date)` always yields the same flights/prices — stable across LLM retries and testable.

## Repo layout

```
flight-agent/     Cloud Run target — the reference stack (data, MCP, agent, card, tests)
hotel-agent/      exact mirror + k8s/ manifests
travel-planner/   A2A host agent (AgentTool + RemoteA2aAgent)
ui/               Vite + React + CopilotKit chat with agent tabs + widget cards
docker-compose.yml
```
