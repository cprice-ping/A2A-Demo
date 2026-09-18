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
  │    subject = person · actor = planner's k8s SA JWT · aud = a2a://flights|hotels
  │    loyalty REFERENCE pushed in-message (planner-owned linkage)
  ▼
flight-agent · hotel-agent — GAP Agent Runtime (A2aAgent native)
  │  Google IAM at the platform edge (planner's SA is the granted caller)
  │  delegated PingOne identity + pushed loyalty ref ride INSIDE the A2A message
  │    → validated in-agent (not by edge middleware)
  │  loyalty VALUE resolved against the specialist's OWN membership records
  ▼
bookings with loyalty — trace panel shows every seam
```

Division of governance (the demo's thesis, two tiers):

- **Google IAM** governs the platform edge: who may discover/invoke GAP agents.
- **Ping** governs identity + delegation + tool policy: person token,
  RFC 8693 exchange (AS + P1AZ), loyalty-scoped profile tokens.

## The identity & registration model (final form, 2026-09-18)

Three identity spaces, three jobs — no identity appears where it does
not belong:

| Identity | Issued by | Appears as | Governs |
|---|---|---|---|
| **k8s SA / WIF subject** (`system:serviceaccount:ping-devops-cprice:travel-planner`) | the cluster | (a) Google platform bearer at the GAP edge (transport, dies there); (b) `act.sub` in AS-minted OBO tokens | platform access + delegation accountability |
| **Person** (`sub` from the planner tenant) | PingOne planner env | `sub` in the OBO token, unchanged | whose trip / whose loyalty / whose consent |
| **AS exchange client** (`AS_CLIENT_ID`) | the TokenExchange-AS | client auth on the exchange call only | authenticates the exchange request — NOT the delegation actor |
| **Specialist's own CC app** | specialist's tenant | specialist-local API calls | retired from the GAP push journey |

### The delegation, end to end

```
planner:  subject_token = person JWT (planner tenant)     ← who
          actor_token   = its OWN k8s SA JWT (projected, WIF-audience)
          audience      = a2a://flights | a2a://hotels
          scope         = a2a:book
AS:       validates subject at planner-tenant JWKS
          validates actor at the EKS OIDC issuer (OIDC discovery)
          consults P1AZ (subject, actor, audience, scope)
          mints: sub=person · act={sub: SA subject} · aud=relationship URI · scope
planner pushes (message metadata, OUTSIDE the bearer):
          a2a_demo_identity = the OBO token
          a2a_loyalty_ref   = the person's member reference for this program
specialist: iss=AS ✓  aud=own URI ✓  act.sub ∈ AUTHORIZED_ACTORS ✓
          → loyalty VALUE resolved against its OWN membership records
            (a pushed reference is a hint to look up, never a claim)
```

### Registration requirements (what an operator actually sets up)

Per relationship (planner ↔ specialist), exactly four registrations —
one per trust layer, none duplicated:

1. **Google IAM** (specialist's project): the planner's WIF-federated
   identity gets `roles/aiplatform.user` on the engine — discovery +
   invocation at the platform edge.
2. **Specialist's `AUTHORIZED_ACTORS`** (engine env): the planner's k8s
   SA subject. This is the specialist's registration of the planner —
   "this platform workload may be the acting intermediary for me."
3. **P1AZ delegation row** (planner-side AS): subject = planner-tenant
   persons, actor = the SA subject, audience = `a2a://…`, scope =
   `a2a:book`. The business decision that switches the delegation on.
4. **Relationship record** (planner config): engine, audience, scope,
   token URL — the machine-readable form of the human agreement.

What is NOT required (and why): **no OAuth client registration at any
specialist's IdP.** The planner already owns a platform identity (the
k8s SA); per-specialist clients would recreate the per-IdP credential
sprawl the standalone AS exists to eliminate. The AS validates whatever
actor JWT it is handed (against that token's own issuer) — the actor
identity is a property of the caller, not of the specialist's directory.
Self-hosted flavor keeps the bridge-client registrations for its
profile-API loyalty pull (a reverse-direction relationship that the
GAP push model deliberately avoids).

### Why act.sub is the SA subject (and not a client, not a GAP identity)

- The actor must be an identity the SPECIALIST can reason about and
  hold accountable: a stable string its allowlist names, attested by the
  AS it trusts.
- The AS stamps act from the presented actor token — the planner
  cannot self-attest.
- The WIF/Google credential authenticates the TRANSPORT and terminates
  at GAP's edge; it never enters the person's delegation chain. The SA
  JWT as actor is the same identity serving its second, business-layer
  role — one workload identity, two governance surfaces (Google IAM at
  the platform edge, P1AZ/specialist policy at the delegation layer).

## The business relationship: how a planner connects to a specialist

Specialists on GAP don't advertise their auth contract — GAP strips
securitySchemes from served cards (verified: fixed core-field allowlist
only), and in cross-org reality no operator publishes their terms
anonymously. The card says WHAT the agent can do; the contract says
UNDER WHAT TERMS you may ask. That contract is a human business
agreement, and the planner represents its side of it as configuration.

### The bootstrap sequence (per relationship, done once by operators)

1. **Arrangement** (human, out-of-band, pre-protocol): the parties agree
   issuers, audiences, scopes, the caller's platform identity, audit
   expectations.
2. **Platform layer**: the specialist's operator grants the planner's
   platform identity access (GAP: IAM binding, roles/aiplatform.user on
   the engine; productized home: Agent Registry entry).
3. **Identity layer**: the specialist's operator records the planner's
   PLATFORM identity as the authorized delegation actor — the k8s SA
   subject (`system:serviceaccount:<ns>:<name>`) the planner presents as
   `actor_token` (the AS validates it at the cluster's OIDC issuer) —
   plus the P1AZ delegation row ("this actor may exchange tokens about
   persons, for this audience, within these scopes"). NOTE: no OAuth
   client registration at the specialist's IdP is required — the actor
   is the planner's existing platform identity, not a new registration.
4. **Wire layer**: planner fetches the authenticated card (skills,
   endpoint), carries the CONTRACT as config, and performs the RFC 8693
   exchange at delegation time — presenting subject (person) + actor
   (own k8s SA JWT) and pushing the person's loyalty REFERENCE in the
   message. The planner contacts NO specialist IdP.

### The relationship object (planner-side contract representation)

Each GAP target is modeled in the planner as an explicit
business-relationship record — TARGET_RELATIONSHIPS (env-derived, like
the current TARGET_TENANTS):

    {
      "hotel-agent": {
        # platform clause (Google tier)
        "engine": "projects/3682147732/locations/us-west1/reasoningEngines/<id>",
        "platform_credential": "wif",          # k8s SA -> Google SA (WIF)
        # identity/delegation clauses (Ping side — the contract proper)
        "audience": "a2a://hotels",            # resource the AS mints for
        "scope": "a2a:book",
        "token_url": "https://a2a-token-as.ping-devops.com/token",
        "as_client": "as-client-id",           # exchange client registration
        # the ACTOR is the planner's own k8s SA JWT (presented at the
        # exchange) — no per-specialist IdP client exists on this path
        # card URL is derived from engine; scheme is NOT read from the
        # card (GAP strips it) — the terms live HERE, not on the wire
      },
      ...
    }

Contract-clause → config mapping (what the operators agreed, where it
lands):

| Contract clause | Where it lives |
|---|---|
| Caller's platform identity (WIF subject) | GAP IAM binding / Agent Registry entry |
| Delegation actor = the caller's platform identity | specialist's `AUTHORIZED_ACTORS` (the SA subject) + P1AZ actor policy |
| Person-scoped subject, audience-bound token | AS exchange (`audience` param) + specialist validator (`aud`) |
| Scopes granted | P1AZ rows + relationship object `scope` |
| Loyalty linkage disclosure | PUSHED in-message as a member reference (planner-owned linkage; specialist resolves the value against its own records) |
| Audit every delegation | trace rows + P1AZ decision logs |

Honest framing for the demo: specialists on GAP do not advertise their
terms; the terms live in the established relationship. That is more
production-true than self-description — and the same shape as Ping's
Identity-for-AI narrative (agent onboarding, scoped access, auditable
delegation). The self-hosted flavor keeps card-driven discovery (same
org, scheme on the wire); the GAP flavor models the contract explicitly.
Side by side, the two show WHERE the contract belongs at each trust
boundary.

Implications recorded: (1) pingone-personal direct login has no
GAP-native home — loyalty stays planner-mediated (already decided);
(2) Agent Registry is the productized home for the contract — GAP gives
the registry; AS + P1AZ remain the delegation contract.

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
   A2A message (the delegated-identity extension, `a2a_demo_identity`
   metadata key + the pushed `a2a_loyalty_ref`); specialist validates
   in-agent (iss=AS, aud=own relationship URI, act.sub=the planner's k8s
   SA subject) and resolves the loyalty value against its own records.
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

**Design stance: native-first.** Specialists deploy as if they were an
enterprise GAP deployment — platform features over custom code wherever
GAP provides one. Concretely:

- **A2aAgent template** (native), not BYOC — the runtime fronts serving,
  IAM, and the authenticated card; we write no serving container.
- **Vertex model path** — GAP forces `GOOGLE_GENAI_USE_VERTEXAI=1` and
  bills through the runtime's Google identity; we don't fight it.
- **Deploy via the SDK** (`agentplatform.Client.runtimes`), staged to
  GCS, redeployed with the upgrade path to preserve `reasoningEngineId`
  — the platform's own lifecycle, not ours.
- **Identity-in-message over middleware**: GAP owns the platform edge
  (Google IAM); our PingOne delegation travels in A2A request metadata
  and is validated in-agent (the one piece that must be custom, because
  it IS the demo's thesis).
- **Discovery & governance**: specialists register in **Agent
  Registry**; the planner discovers via authenticated cards. No custom
  card-hosting workarounds.

Deferred (parked): standalone MCP services + Agent Registry
registration + Ping AI Agent Gateway enforcement in front of tools.
The tools.py/mcp_server split keeps that migration cheap, but the
pilot ships in-process.

Code changes above → `gap/deploy_flight.py` → smoke via SDK:
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
| `GOOGLE_API_KEY` | `.env` | n/a on GAP (Vertex via runtime identity) |
| PingOne AS exchange client | `.env` | k8s secret |
| Bridge clients (retired on GAP path) | `.env` | none — the actor is the k8s SA; registrations remain only for the self-hosted pull flavor |

## Parked: tools as a standalone MCP service (post-pilot)

Once the GAP pilot is green, the enterprise-shaped evolution is to move
specialist tools OUT of process: booking/search as a standalone MCP
service (Cloud Run), registered in **Agent Registry** for governed
discovery, with **Ping AI Agent Gateway** as the enforcement point in
front of the booking APIs — delegated PingOne token validated at the
tool boundary (or by the gateway), per-tool least privilege, audit.
This inverts the earlier contextvar lesson: identity travels to the
tool layer as a bearer credential, not request-scoped contextvars.
The tools.py / mcp_server.py split keeps this migration cheap — only
the transport changes.
| model auth | `GOOGLE_API_KEY` | same (or Vertex+ADC on GAP natively) |

## Risks / open questions

1. ✅ RESOLVED: `create_agent_card` accepts a full card dict and our
   `pingone` securitySchemes survive the GAP wrap (verified locally).
2. A2A version: GAP A2A is Pre-GA and the A2aAgent template REQUIRES
   protocol 1.0 / HTTP+JSON (lifted in gap_agent.py; the self-hosted
   card keeps 0.3). Planner-side client compatibility still to verify.
3. Non-streaming fallback in ADK `RemoteA2aAgent` (assumed automatic via
   card capabilities — verify in the pilot smoke test).
4. ✅ RESOLVED: identity rides SendMessageRequest.metadata key
   `a2a_demo_identity` (planner: a2a_request_meta_provider; GAP agent:
   executor adapter validates via auth.validate_token).
5. GAP egress to AS (public ✓) and planner profile API (public via
   ingress ✓) — no private-network work expected.
6. `AG-UI` disappears on specialists by design (agent-only); planner
   keeps AG-UI + all render cards — UI rework limited to honesty states.
7. Deploy-loop learnings (encoding here so they aren't relearned):
   engine-start failures are generic at the API — the real cause is in
   the engine's stderr log (`aiplatform.googleapis.com/reasoning_engine_stderr`);
   extra_packages entries must be RELATIVE paths (tar.add stores paths
   verbatim); the pickled agent references the source package, so
   extra_packages must carry the package dir itself; pickle happens
   BEFORE set_up (locks after set_up are unpicklable); the GAP import
   graph must be free of self-hosted-only deps (fastmcp, ag_ui_adk).
