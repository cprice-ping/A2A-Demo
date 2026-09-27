# Plan: one set of agents, three trust models

Status: **plan.** Phase 0 and phase 1 are ready to build. Phase 2 needs its
own spec first.

## Thesis

The same travel scenario (a person, a planner, a flight agent and a hotel
agent) runs under three trust models. The agents, tools, UI and trace
panel stay the same, and only the trust layer (plus, for ATProto, the
transport) changes. That makes the difference between the models the
thing a viewer actually watches.

The underlying question is: **when an agent acts, is its authority decided
live by a policy point, or carried with it as a signed artifact?** Each
variant sits at a different point on that line, and each is the right
answer somewhere.

| | Enterprise (exists) | Ad hoc (phase 1) | ATProto (phase 2) |
|---|---|---|---|
| Relationship | Pre-arranged partners | Strangers, discovered at runtime | Strangers, on a shared open network |
| Transport | A2A | A2A | ATProto XRPC |
| Root of trust | PingOne (planner tenant) | The person's own key (`did:key`) | The person's own DID (`did:plc`), anchored in their PDS |
| Authority decided | Live, per request: TokenExchange-AS + PingOne Authorize | Carried: signed delegation chain, checked by the receiver | Carried: service-auth tokens, delegation record in the person's PDS |
| What the receiver trusts | The shared exchange server, allowlisted actors | Only what arrives in the message, plus public DID lookups, plus attestors it chooses | The same, with DID resolution through the ATProto network |
| Revocation | Immediate (policy is evaluated live) | Live check for high-stakes actions only; otherwise at expiry | Record deleted in the person's PDS |
| Discovery | Configured card URLs, IAM-governed on GAP | Card URL supplied at runtime | Lexicons and DIDs |
| Spec | `extensions/delegated-identity/v1/` | `extensions/delegated-identity/v2/` | To be written |

## What stays the same in every variant

These are the metaphors the audience learns once and then watches under
each model:

- **The person** asks for a trip and is the root of every delegation.
- **The planner** decomposes the trip and delegates legs. It never books
  anything itself.
- **Specialists** (flight, hotel) own their own data and their own
  decisions.
- **Loyalty is pushed, not pulled.** The planner attaches a member
  reference, and the specialist resolves the value from its own records.
- **Bookings need the person.** The mechanism differs by variant (scope
  in a delegation token, a signed approval, a PDS record), but no variant
  lets the planner book on its own authority.
- **The trace panel shows every trust decision**, with `auth.*` rows at
  every boundary crossing.

## Target repo layout

```
core/                      shared by every variant
  domain/flights/          mock API, data, store, tools, prompts   (from flight-agent/src/flight_agent/)
  domain/hotels/           the same for hotels                     (from hotel-agent/src/hotel_agent/)
  trace/                   trace ring buffers + SSE                (trace.py, identical in both agents today)
  loyalty/                 push-model loyalty resolution           (loyalty.py, differs by 4 lines)
  ui/                      chat UI, cards, trace panel             (from ui/)
transport/
  a2a/                     cards, executors, clients               (enterprise + ad hoc)
  xrpc/                    lexicons, XRPC endpoints                (ATProto, phase 2)
trust/
  enterprise/              v1: OBO validation, exchange client, GAP adapter   (auth.py, gap_agent.py, p1az/)
  adhoc/                   v2: DIDs, chains, attestations, tiers, revocation  (new)
  atproto/                 service auth, PDS records                          (phase 2)
services/
  attestor/                ad hoc: third-party attestation issuer             (new)
  status/                  ad hoc: person-signed revocation lists             (new)
apps/
  flight-agent/            thin entrypoint: core + transport + trust, chosen by config
  hotel-agent/
  travel-planner/
deploy/
  enterprise/              GAP + EKS (from gap/, k8s/)
  adhoc/                   per-party hosting
  atproto/                 phase 2
extensions/                protocol specs (unchanged location)
docs/
```

Each app is a thin entrypoint that picks one transport and one trust
module:

| Variant | Transport | Trust | Selected by |
|---|---|---|---|
| Enterprise | `transport/a2a` | `trust/enterprise` | `IDENTITY_MODE=v1` |
| Ad hoc | `transport/a2a` | `trust/adhoc` | `IDENTITY_MODE=v2` |
| ATProto | `transport/xrpc` | `trust/atproto` | Separate entrypoint (phase 2) |
| Open demo | `transport/a2a` | none | `IDENTITY_MODE=off` (today's `AUTH_REQUIRED=false`) |

Enterprise and ad hoc differ only in the `trust/` folder they load. That is
the argument, visible in the file tree.

## Branching and releases

- **One long-lived branch: `main`.** Every variant lives on it, side by side.
- **No long-lived branch per variant.** Shared fixes would have to be
  copied three ways, the variants could not run together, and the
  difference between them would be buried in unrelated drift.
- **Short-lived feature branches** for each phase, merged to `main`.
- **Tags for known-good demo states**, for example
  `demo/enterprise-baseline` and `demo/adhoc-2026-10`, so a customer demo
  can be run from exactly what was last verified.

## Phase 0: extract shared code (do this first)

Today `flight-agent/` and `hotel-agent/` duplicate most of their
non-domain code. Measured after normalizing the words flight/hotel:

| File | Differing lines | Destination |
|---|---|---|
| `trace.py` | 0 of 362 | `core/trace/` |
| `loyalty.py` | 4 | `core/loyalty/` (parameterize the program) |
| `main.py` | 5 | `apps/*/` entrypoint, with shared app factory |
| `instructions.py` | 5 | stays per domain |
| `auth.py` | 34 | `trust/enterprise/` (parameterize issuer and audience env names) |
| `card.py` | 35 | `transport/a2a/` card builder + per-domain skills |
| `routes.py`, `store.py` | 37–40 | `core/domain/*/` |
| `tools.py`, `mcp_server.py` | 64–72 | `core/domain/*/` |
| `gap_agent.py` | 102 | `trust/enterprise/` (GAP adapter) |
| `api/data.py` | 275 | `core/domain/*/` (the genuinely different part) |

Also check `travel-planner/src/travel_planner/trace.py` against the agents'
copy; it is likely the same module.

If phase 0 is skipped, v2 has to be implemented twice, once in each agent.

### Constraints to handle

- **Docker build context.** Each Dockerfile copies only its own `src/`.
  Shared packages need the build context at the repo root, or a uv
  workspace with path dependencies.
- **GAP packaging.** `gap/deploy_flight.py` stages code with
  `extra_packages = ["flight_agent"]`, relative to the source directory,
  because GAP unpickles modules by import path. Shared packages must be
  staged the same way, as relative package directories, or the deployed
  agent fails with `No module named ...`. Test this early, because it is
  the most likely thing to break.
- **Environment names.** Keep the existing env variable names
  (`P1_FLIGHTS_ISSUER`, `AUTHORIZED_ACTORS`, and so on) so the deployed
  enterprise environment needs no reconfiguration.

### Done when

- `demo/enterprise-baseline` is tagged **before** the refactor starts.
- After the refactor: compose runs the open demo unchanged, the enterprise
  deployment (EKS planner + GAP specialists) runs unchanged, and the trace
  panel shows the same `auth.user` → `auth.token_exchange` →
  `auth.accepted` rows as the baseline.
- `flight-agent/` and `hotel-agent/` contain no duplicated non-domain code.

## Phase 1: ad hoc trust on A2A

Build spec: [`extensions/delegated-identity/v2/README.md`](../extensions/delegated-identity/v2/README.md).
That spec has its own sub-phases (search → attestation and hold → step-up
booking → revocation → multi-hop).

Decisions from planning:

- **Stay on A2A.** Changing the transport and the trust model at once
  would hide which change mattered. The ad hoc variant differs from
  enterprise in trust only.
- **Lighter A2A handling in v2.** The weight in the current demo is ADK's
  A2A wrappers and GAP, not A2A itself. For v2:
  - **Receivers** own their A2A executor (a2a-sdk), so v2 verification
    runs in our code before the agent sees the request. ADK can still run
    the agent's model loop behind it.
  - **The planner's v2 path** calls specialists with the a2a-sdk client
    directly, not `RemoteA2aAgent` + `AgentTool`. That puts the step-up
    round trip (refused → person approves → retry) under our control.
- **Self-hosted only.** GAP requires IAM to read a card and strips the
  extension declaration, which makes discovery a pre-arranged
  relationship.

### Making it honestly ad hoc

Running everything in one compose file on one machine would still be one
trust domain in disguise. The deployment must show separate parties:

- **Runtime discovery.** In v2 the planner is **not** given
  `FLIGHT_AGENT_CARD_URL`. The card URL arrives at runtime, typed by the
  person or chosen from a directory the planner does not control.
- **Separate hosting and domains per party.** For example: planner on EKS
  (existing), flight agent on Cloud Run (`deploy-cloud-run.sh` exists), and
  attestor and status each on their own host. Real HTTPS domains mean
  `did:web` resolves normally; `DID_WEB_ALLOW_HTTP` is for local compose
  only.
- **No planner in the receiver's config.** No actor allowlist, no audience
  agreed in advance. The receiver's only trust setting is which attestors
  it recognizes.
- **A stranger.** A second flight agent, run as a different party, with
  different recognized attestors and stricter tiers. The same planner with
  the same person's delegation gets different ceilings from each receiver.

Local compose remains for development, with an `adhoc` profile, but the
demo that is shown to people uses the separated deployment.

### Done when

All 13 acceptance scenarios in the v2 spec pass against the separated
deployment, including the stranger (scenario 13).

## Phase 2: ATProto variant (spec first)

Write a spec in the style of v2 before any code. What it should cover:

- **Person identity.** A `did:plc`, which gives key rotation and recovery,
  addressing v2's open question on key custody.
- **Delegation and revocation as records in the person's PDS.** The
  person controls where they live. Revocation means deleting the record.
  This addresses v2's open question on where revocation lists live.
- **Service auth for calls.** ATProto's short-lived inter-service tokens
  (issuer DID, audience DID, bound to a method) are close in structure to
  the v2 invocation token. Check how far they can go before custom tokens
  are needed.
- **Lexicons for the travel schemas** (search, hold, book). These need an
  NSID namespace, which means a domain under Chris's control.
- **Transport.** `transport/xrpc`, reusing `core/` unchanged. If it stops
  reusing `core/`, consider moving it to its own repo.

Starting point: the ATProto work in Agentic-Watershed.

## Phase 3: combined demo

Once phases 0 and 1 are done, run one planner that uses **both** trust
models in one conversation:

- A **partner airline** with a relationship record → v1: live exchange,
  Authorize decides.
- A **stranger airline** found at runtime → v2: carried delegation, the
  receiver decides.

The same trip request crosses both boundaries, and the trace panel shows
each one side by side. The selection rule (v1 when a relationship record
exists for the target, v2 otherwise) is open question 5 in the v2 spec.

## Where each variant sits

| Property | Enterprise | Ad hoc | ATProto |
|---|---|---|---|
| Trust domains | Several, pre-federated | Several, none federated | Several, on one open network |
| Policy point reachable per request | Yes, required | No, not used | No, not used |
| Revocation speed | Immediate | Seconds for hold/book; up to 1 hour for search | As fast as the receiver re-reads the record |
| Who decides | Central policy (Authorize) | Each receiver, locally | Each receiver, locally |
| Accountability trail | Exchange server logs + policy decisions | Signed chain in each message | Signed records in the person's PDS |

These rows are the variables of the choice, not a scorecard. The demos
exist to show when each column is the right one.

## Risks

- **Phase 0 breaking the GAP deployment** (packaging). Mitigation: tag
  first, and test a GAP deploy of one agent before refactoring the second.
- **Scope creep in phase 1.** The v2 spec has five sub-phases; the first
  two (search and hold) are enough for a first showing.
- **The person key is fragile** in phase 1 (one browser's WebCrypto key).
  Accept it for phase 1 and say so on screen; phase 2 is where it gets
  fixed.
