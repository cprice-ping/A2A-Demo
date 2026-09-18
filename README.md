# A2A-Demo: Travel Planner + Specialist Agents (ADK · A2A · AG-UI)

A hands-on exploration of the [A2A protocol](https://a2a-protocol.org) with a **Travel Planner** host agent and two specialist agents — **Flight Search/Booking** and **Hotel Search/Booking** — exposed over **A2A** (agent card + JSON-RPC / HTTP+JSON) and **AG-UI** (streaming chat + widget tools).

The thesis is the **identity → A2A boundary**: a host agent delegating to agents operated by *other parties*, with the person's identity conveyed through a delegation chain that is enforced — not assumed — at every seam. Each agent can live on a different platform; the architecture holds as long as the identity registrations are in place:

| Agent | Role | Where it runs (this deployment) | Where it could run |
|---|---|---|---|
| travel-planner | host: verifies the person, delegates | k8s (EKS, public) | any cluster / PaaS |
| flight-agent | specialist | Google Agent Platform (GAP) | GAP · Bedrock AgentCore · self-hosted |
| hotel-agent | specialist | Google Agent Platform (GAP) | GAP · Bedrock AgentCore · any host |

A specialist does not know or care what platform its caller runs on, and vice versa — the relationship is expressed in **identity configuration** (IAM bindings, delegation policy, relationship records), never in agent code.

```
 Person (browser)
   │  PKCE login @ PingOne planner tenant
   ▼
 Chat UI (EKS) ── AG-UI SSE + Bearer person token ──▶ travel-planner (k8s)
                                                        │  person token validated
                                                        │  RFC 8693 exchange @ TokenExchange-AS
                                                        │    subject=person · actor=k8s SA · aud=a2a://flights|hotels
                                                        │  loyalty ref pushed in-message
                                                        ▼
                              ┌──────────────────────────┴──────────────────────────┐
                              ▼ A2A (GAP platform edge: Google IAM / WIF)            ▼
                       flight-agent (GAP)                                hotel-agent (GAP)
                       in-agent OBO validation                           in-agent OBO validation
                       loyalty value from OWN records                    loyalty value from OWN records
                              │                                                     │
                              └── same pattern recurses to the specialist's own tools (own AS, own actor)
```

Every layer refuses unauthenticated execution: the planner's prompt surfaces require a person (anonymous POST → 401), and the GAP specialists fail closed — no valid delegated identity, no execution (search included); bookings additionally require a **person delegation** (`a2a:book` scope, which policy does not grant to workload-only sessions). See [GCP-DEPLOYMENT.md](GCP-DEPLOYMENT.md) — "Presence, not anonymity" — for the three-rung model.

## The three surfaces of an agent (per domain container)

| Path | Protocol | What it's for |
|---|---|---|
| `/api` | REST | The mock domain API (search/book/get) — the "backend system" |
| `/mcp` | MCP (streamable HTTP) | Domain tools the agent's LLM calls (self-hosted flavor; GAP runs native function tools) |
| `/a2a` | A2A JSON-RPC / HTTP+JSON | Agent-to-agent: other agents delegate here. Card at `/a2a/.well-known/agent-card.json` |
| `/agui` | AG-UI (SSE) | The chat UI's streaming endpoint (specialists self-hosted only; GAP serves its own A2A surface) |

Each domain agent runs **two instances of the same brain** when self-hosted: `root_agent` serves `/agui` (calls `render_*` frontend tools the browser renders as cards) and `a2a_agent` serves `/a2a` (no frontend tools — returns raw JSON for an agent caller). Same tools either way. On GAP, the A2aAgent template exposes the specialist over the platform's A2A surface and the executor adapter adds identity enforcement.

The planner wraps each specialist in an `AgentTool(RemoteA2aAgent(...))` so it stays in control of the loop: call flight → get JSON → call hotel → get JSON → render both cards.

## The identity architecture

Three identity spaces, three jobs (full model: [GCP-DEPLOYMENT.md](GCP-DEPLOYMENT.md), "The identity & registration model"):

- **Person** (PingOne planner tenant) — rides the chain as `sub`, unchanged: whose trip, whose loyalty, whose consent.
- **Workload** (k8s SA, federated via WIF) — platform bearer at the GAP edge AND the `act.sub` actor inside minted delegation tokens.
- **AS exchange client** — authenticates the exchange *call* only; never an actor.

Delegation is minted per-request at a standalone AS ([TokenExchange-AS](https://github.com/cprice-ping/TokenExchange-AS)) governed by PingOne Authorize policy: subject introspected (person must be in-session), actor validated at the EKS OIDC issuer, audience pinned to one relationship URI (`a2a://flights` / `a2a://hotels`), scope chosen by policy. The sanitized P1AZ policy snapshot is in [p1az/](p1az/); the planner-environment build order is in [docs/PINGONE-PLANNER-ENV.md](docs/PINGONE-PLANNER-ENV.md); legacy tenant topology in [PINGONE-TOPOLOGY.md](PINGONE-TOPOLOGY.md).

Loyalty uses the **push model**: the planner attaches the person's member *reference* in-message (outside the bearer); the specialist resolves the *value* against its own records. No reverse-direction trust, no planner-API call from the specialist.

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

## Identity (PingOne)

The deployed demo is identity-aware end to end: PingOne (planner tenant) issues the person's tokens and hosts the P1AZ delegation policy; the standalone TokenExchange-AS mints every specialist-bound token; specialists validate in-agent. Full identity model and registration requirements: **[GCP-DEPLOYMENT.md](GCP-DEPLOYMENT.md)**; environment build order: **[docs/PINGONE-PLANNER-ENV.md](docs/PINGONE-PLANNER-ENV.md)**; P1AZ policy snapshot (sanitized): **[p1az/](p1az/)**.

The self-hosted compose flavor runs `AUTH_REQUIRED=false` by default (open demo); set `AUTH_REQUIRED=true` to force the identity path. The GAP/k8s deployment is fail-closed by default — see "Presence, not anonymity" in GCP-DEPLOYMENT.md.

## Deployment

### The deployed architecture (planner on k8s, specialists on GAP)

```bash
# Planner + UI on EKS (WIF federation to Google, no keys):
bash k8s/travel-planner/deploy.sh          # builds, pushes, deploys, forces rollout
# (UI: k8s/travel-ui/ — nginx serving the built SPA with runtime config)

# Specialists on GAP (Agent Runtime, A2aAgent template):
~/.venvs/gap-deploy/bin/python gap/deploy_flight.py   # or upgrade to update in place
~/.venvs/gap-deploy/bin/python gap/deploy_hotel.py
```

The planner discovers GAP specialists via **authenticated cards** (WIF-derived Google credential); GAP does not serve anonymous cards — discovery itself is IAM-governed. Specialists are upgraded in place with `upgrade` (preserves `reasoningEngineId`).

### Flight agent → Cloud Run (self-hosted flavor)

```bash
cd flight-agent
./deploy-cloud-run.sh
```

The script enables APIs, creates a `flight-agent-run` service account with `roles/aiplatform.user`, deploys from source, then bootstraps `PUBLIC_BASE_URL` to the service's real URL (the agent card must advertise it). Model calls authenticate with the service account — no key material anywhere.

### Hotel agent → Kubernetes (self-hosted flavor)

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

### Hybrid — the architecture's point

Any card URL works anywhere: the planner spans platforms by configuration. In the deployed topology the planner runs on EKS while both specialists run on GAP; the same planner could delegate to one specialist on GAP and another on Bedrock AgentCore or a self-hosted cluster — the relationship registrations (IAM binding, `AUTHORIZED_ACTORS`, P1AZ row, relationship record) are the only per-target work. See GCP-DEPLOYMENT.md, "Registration requirements."

## Configuration (env vars)

| Var | Where | Purpose |
|---|---|---|
| `GOOGLE_GENAI_USE_VERTEXAI=true` | any agent | Model calls via Vertex AI (ADC auth) instead of Gemini API key |
| `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` | Vertex agents | Vertex project/region |
| `GOOGLE_API_KEY` | hotel agent (k8s/compose) | Gemini API key (the demo's only key) |
| `PUBLIC_BASE_URL` | all agents | URL other parties use to reach this agent — drives the card's advertised endpoint |
| `MCP_SELF_URL` | domain agents | The agent's own MCP server URL (default `http://localhost:<port>/mcp`) |
| `FLIGHT_AGENT_CARD_URL` / `HOTEL_AGENT_CARD_URL` | planner | Full card URLs of the specialists (self-hosted flavor) |
| `TARGET_RELATIONSHIPS` | planner | GAP targets: engine resource name, audience, scope, AS issuer (see GCP-DEPLOYMENT.md) |
| `AS_ISSUER` / `AS_CLIENT_ID` / `AS_CLIENT_SECRET` | planner + specialists | TokenExchange-AS issuer + exchange client |
| `AUTH_REQUIRED` | planner (k8s: true) + specialists (GAP engines: true; compose: false) | Fail-closed identity gate |
| `GAP_RELATIONSHIP_AUDIENCE` | GAP specialists | The relationship URI the specialist validates (`a2a://flights` / `a2a://hotels`) |
| `AUTHORIZED_ACTORS` | GAP specialists | The planner's k8s SA subject allowed as `act.sub` |
| `CORS_ORIGINS` | all agents | Comma-separated allowed origins (default `http://localhost:5173`) |
| `VITE_FLIGHT_AGENT_URL` / `VITE_HOTEL_AGENT_URL` / `VITE_PLANNER_AGENT_URL` | ui (build time) | Override `/agui` endpoints; also acceptable as query params `?flightAgent=...` |

## Tests

```bash
cd flight-agent && uv run pytest   # schedule synthesis + REST API
cd hotel-agent && uv run pytest    # data enrichment + REST API
```

No LLM tests — model calls are exercised manually/via the chat UI. GAP fail-fast pre-deploy checks: `~/.venvs/gap-deploy/bin/python gap/local_test.py both`.

## Notable implementation details (gotchas worth knowing)

- **A2A has multiple wire shapes** — know which one you're looking at: JSON-RPC `{method, params:{message}}` (0.3), GAP's HTTP+JSON `SendMessageRequest` `{message, configuration, metadata}` (1.0), and bare messages. Metadata location differs: GAP's meta provider lands **request-level** (`SendMessageRequest.metadata`), which is where the delegated identity + loyalty ref ride; `RequestContext.metadata` reads exactly that.
- **GAP responses wrap the Task**: `{"task": {...}}` with enum-named states (`TASK_STATE_COMPLETED`) and the reply text in **artifacts** (status.message.parts is empty).
- **httpx event hooks + streamed clients**: the a2a client reads responses via `client.stream()`; touching `response.content` in a response hook raises `ResponseNotRead`. `await response.aread()` inside the hook works and replays the body to the caller.
- **GAP strips card fields**: served cards carry a fixed core-field allowlist (no `securitySchemes`, no `capabilities.extensions`) — the auth contract must be planner-side relationship config, not card discovery, for GAP targets.
- **RemoteA2aAgent rejects plain-http card URLs** unless the host is loopback — fetch the card JSON yourself and pass the `AgentCard` object.
- **`:latest` + `kubectl apply` is a silent no-op**: a rebuilt image under an unchanged tag never restarts the workload — the deploy script forces `rollout restart`.
- **Mounted sub-app lifespans don't run automatically.** Both FastMCP's session manager AND `to_a2a()`'s route attachment live in their sub-app lifespans — the parent must drive both.
- **The card's JSON-RPC URL needs a trailing slash** (`http://host:8080/a2a/`) — a2a clients don't follow the 307 from `/a2a`.
- **CopilotKit agent selection**: pass both `agent` (v1) and `agentId` (v2) props, else it looks for a nonexistent `'default'` agent; the v1 `agents` prop is gone in 1.71 — use `selfManagedAgents`.
- **a2a-sdk 1.x is protobuf-based**: `AgentCard` uses `supported_interfaces`, not a flat `url` field.
- **fastmcp 2.x, not 4.x**: fastmcp 4 requires `mcp>=2` which hard-conflicts with google-adk's `mcp>=1.24,<2` pin.
- Deterministic schedule synthesis: same `(origin, destination, date)` always yields the same flights/prices — stable across LLM retries and testable.

## Repo layout

```
flight-agent/     specialist (self-hosted flavor reference: data, MCP, agent, card, tests) + GAP flavor
hotel-agent/      mirror + k8s/ manifests + GAP flavor
travel-planner/   A2A host agent (delegation, token exchange, relationship config)
ui/               Vite + React + CopilotKit chat; trace panel; runtime-config for deployment
gap/              GAP deploy/upgrade/smoke scripts for the specialist engines
k8s/              travel-planner + travel-ui k8s manifests (EKS deployment)
docs/             PingOne planner-environment runbook
p1az/             PingOne Authorize delegation policy snapshot (sanitized)
PINGONE-TOPOLOGY.md    legacy three-tenant topology + the AS rationale
GCP-DEPLOYMENT.md      the identity & registration model + deployment phases
docker-compose.yml     self-hosted flavor
```

## Security notes for readers

- The demo uses **placeholder/seed credentials and fixed demo member IDs** — never reuse the tenant IDs, client IDs, or the mock loyalty records in these docs; provision your own.
- `.env`, k8s secrets, and the AS's real credentials are gitignored; the committed P1AZ snapshot carries `<your-*>` placeholders for attribute-resolved credentials.
- The trace panel shows token claims and decision rows, never token values.
