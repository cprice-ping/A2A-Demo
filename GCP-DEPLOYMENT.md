# GCP deployment: planner in AWS k8s, specialists in GAP

Draft topology + phased plan. Decisions locked in P0 are marked ✅; the
remaining dials are marked ❓ — they gate the phase that needs them.

## Locked decisions (P0)

- **GAP project/location**: `projects/3682147732/locations/us-west1`
  (existing GAP deployments live there; redeploy with the SDK's
  upgrade path to preserve `reasoningEngineId`).
- **Audiences**: stable resource URIs — `a2a://flights` and `a2a://hotels`
  for the GAP targets. The AS stamps these as `aud`; specialists validate
  their own URI in-agent; P1AZ rows key on them (stable across redeploys,
  unlike GAP's resource-ID URLs). The local k8s specialists, if any remain,
  keep URL audiences; both fit the same AS.
- **Planner hostname**: `a2a-travel-planner.ping-devops.com` — mirrors the
  AS's ingress convention (`a2a-token-as.ping-devops.com`, same
  `nginx-public` class, same ELB, cert-manager ClusterIssuers available).
- **Cluster facts (discovered)**: EKS `us-east-2`, OIDC issuer
  `https://oidc.eks.us-east-2.amazonaws.com/id/9ACBE86EA026DE86EFC05A61A5F83B30`,
  workload namespace `ping-devops-cprice` (AS pattern to mirror:
  deployment + ClusterIP + `nginx-public` ingress + cert-manager TLS).

## Topology

```text
Browser UI (built, hosted)                                  [❓ host]
  │  PKCE person token @ PingOne planner tenant (unchanged)
  ▼
travel-planner — AWS k8s (existing cluster)                 [k8s/travel-planner/]
  │  validates person token · AG-UI + render cards to the browser
  │  discovers GAP specialists via AUTHENTICATED card
  │    (WIF: cluster k8s SA → Google credential, aiplatform.user in GAP project)
  │  RFC 8693 @ TokenExchange-AS (already k8s, unchanged)
  │    subject = person · actor = planner bridge · aud = GAP specialist A2A URL
  ▼
flight-agent · hotel-agent — GAP Agent Runtime (A2aAgent native)
  │  Google IAM at the platform edge (planner's SA is the granted caller)
  │  delegated PingOne identity rides INSIDE the A2A message
  │    → validated in-agent (not by edge middleware)
  │  chained profile-token exchange → loyalty pull from planner profile API
  ▼
bookings with loyalty — trace panel shows every seam
```

Division of governance (the demo's thesis, two tiers):

- **Google IAM** governs the platform edge: who may discover/invoke GAP agents.
- **Ping** governs identity + delegation + tool policy: person token,
  RFC 8693 exchange (AS + P1AZ), loyalty-scoped profile tokens.

## What changes per component

| Component | Today (compose) | Target | New artifacts |
|---|---|---|---|
| UI | Vite dev @ :5173 | Built + hosted | `ui/Dockerfile` or static deploy; PingOne redirect URI add |
| travel-planner | compose service | AWS k8s deployment, public via ingress | `k8s/travel-planner/` (mirror `token-exchange/` pattern) |
| specialists | compose services | GAP `A2aAgent` (native) | `gap/` deploy script + code wrap |
| TokenExchange-AS | k8s (done) | unchanged | — |
| PingOne tenants | same | console edits only | redirect URI, P1AZ audience rows |

**docker-compose is unchanged** — it remains the local dev/demo flavor. The
cloud flavor is new artifacts alongside, not a fork. Hybrid integration runs
(local planner ↔ remote specialists) need only `.env` changes; compose
already parameterizes card URLs, audiences, and the profile URL.

## Specialist code changes (GAP-native)

1. **Tools in-process.** GAP-native has no container filesystem of "our
   services" — the self-hosted MCP server (`/mcp` over localhost) has no
   home. Convert `search_flights` / `get_flight` / `search_hotels` /
   `get_hotel` / `get_booking` (plain functions behind `@mcp.tool`) to
   native ADK function tools. Booking tools are already native
   (`book_*_identity_aware`). Loyalty pull is already in-process.
2. **Identity in-message.** The AS-minted delegated token travels in the
   A2A message (metadata key TBD — `identity.authorization` or an A2A
   extension); specialist validates in-agent (iss=AS, aud=chosen resource
   URI, act=planner bridge) and then does the chained loyalty exchange.
   Reuses the middleware's validation logic as a plain function.
3. **Card.** Wrap with `vertexai.agent_engines.templates.a2a.A2aAgent` +
   `create_agent_card`. ❓ Whether we can inject our PingOne
   `securitySchemes` into the GAP-built card — if not, the planner's
   card-derived discovery needs a fallback target config for GAP targets
   (audience/scope carried planner-side, as it was pre-card-design).
4. **Streaming off.** Card advertises `streaming: false`; GAP documents
   non-streaming `message/send` only (Pre-GA). Verify ADK's
   `RemoteA2aAgent` falls back from `message/stream` automatically, and
   that `a2a.exchange` trace rows render the non-streaming shape (they
   already handle both).

## Phases

**P0 — decisions** ✅ (see Locked decisions above)

**P1 — WIF: EKS → Google (keyless)**
Cluster OIDC issuer (above) → Google STS workload identity pool + provider;
map k8s SA (`ping-devops-cprice/travel-planner`) → Google SA; grant
`roles/aiplatform.user` in the GAP project. Prereqs confirmed: issuer
reachable, namespace exists, `gcloud` authed.

**P2 — GAP specialists pilot** (one first: flight-agent)
Code changes above → `gap/deploy_flight.py` (vertexai SDK,
`A2aAgent`, requirements incl. `google-adk[a2a]`) → smoke via SDK:
`handle_authenticated_agent_card()` + `message/send` with identity in
metadata + loyalty chain end-to-end.

**P3 — planner to k8s**
Image build/push; manifests mirror `token-exchange/` (deployment,
service, `nginx-public` ingress with TLS for
`a2a-travel-planner.ping-devops.com`, secrets from k8s secret);
`FLIGHT/HOTEL_AGENT_CARD_URL` → GAP endpoints with **authenticated
fetch** (planner code change: attach WIF-derived Google token when the
anonymous fetch 401s — keep card-derived PingOne discovery working off
the fetched card); `PLANNER_PROFILE_URL` =
`https://a2a-travel-planner.ping-devops.com/api/profile/loyalty`
(specialists in GAP must reach it); `AUTHORIZED_ACTORS` / audiences →
`a2a://flights` / `a2a://hotels`.

**P4 — AS + P1AZ re-point**
New P1AZ rows for the GAP audiences (delegation + loyalty chain rows
keyed on the new `aud` values); old localhost rows can stay for the
local flavor. AS code: no change (audience arrives per-request).

**P5 — UI**
Build + host (❓ Cloud Run vs static bucket vs the k8s cluster); add
redirect URI in PingOne `travel-ui`; `VITE_PLANNER_ISSUER` unchanged;
ActivityPanel `AGENT_URLS` become configuration (build-time env or a
runtime config endpoint) instead of hardcoded localhost.

**P6 — UI honesty states**
Card strip: GAP agents' mini-cards show the IAM-governed state
("🔒 card behind Google IAM — discovery requires platform credential")
when anonymous fetch fails. Specialist direct-chat tabs retire to
"agent-only" notes (the planner introduces the person; specialists are
not human surfaces). Trace panel tells the two-tier story per hop.

## Environment mapping (compose → cloud)

| Var | compose (local) | cloud |
|---|---|---|
| `PUBLIC_BASE_URL` | `http://flight-agent:8080` | GAP card URL / k8s ingress URL |
| `FLIGHT/HOTEL_AGENT_CARD_URL` | compose DNS | GAP authenticated-card endpoints |
| `P1_*_AUDIENCE` | `http://localhost:8080` | `a2a://flights` / `a2a://hotels` |
| `PLANNER_PROFILE_URL` | `http://travel-planner:8080/...` | `https://a2a-travel-planner.ping-devops.com/api/profile/loyalty` |
| `GOOGLE_API_KEY` | `.env` | Secret Manager → GAP env |
| PingOne bridge secrets | `.env` | Secret Manager / k8s secret |
| model auth | `GOOGLE_API_KEY` | same (or Vertex+ADC on GAP natively) |

## Risks / open questions

1. ❓ Can `create_agent_card` / `A2aAgent` carry our `securitySchemes`?
   If not → planner-side fallback target config for GAP targets.
2. A2A version: GAP A2A is Pre-GA; Gemini Enterprise registration wants
   v0.3 while our SDK is newer — check which the Agent Runtime endpoint
   speaks and whether the compat package is needed.
3. Non-streaming fallback in ADK `RemoteA2aAgent` (assumed automatic via
   card capabilities — verify).
4. In-message identity transport (metadata key / extension) — pick one
   convention and document it in the card/topology.
5. GAP egress to AS (public ✓) and planner profile API (public via
   ingress ✓) — no private-network work expected.
6. `AG-UI` disappears on specialists by design (agent-only); planner
   keeps AG-UI + all render cards — UI rework limited to honesty states.
