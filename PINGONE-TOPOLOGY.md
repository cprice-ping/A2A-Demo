# PingOne topology — A2A demo identity

Three PingOne sandbox environments (same org) provide identity for the demo.
All were provisioned 2026-09-13 via the PingOne MCP server; IDs below are
referenced from `.env` (never committed).

## Environments

| Tenant | Environment ID | Role in demo |
|---|---|---|
| **A2A - Planner** | `516a3a93-03be-49fd-89c6-5a5bdac1d33e` | Human login (PKCE); loyalty-linkage authority; profile API |
| **A2A - Flights** | `042b7e33-688a-487a-beff-b9fb8226ac19` | Identity for flight-agent `/a2a`; token-exchange target |
| **A2A - Hotels** | `42eb21e4-fcd6-4921-ae50-628ce4c51c61` | Identity for hotel-agent `/a2a`; token-exchange target |

## Users

`chris@example.com` exists in **all three** envs (same human, three accounts):

| Env | User ID | Notes |
|---|---|---|
| Planner | `e8b4ba57-e243-4fc6-ac8c-f6972d6115bf` | Primary login; loyalty linkage lives in the planner's profile API |
| Flights | `0c081bb0-0428-486f-9f19-21b07237e5a0` | SkyWay member SK-123456 (GOLD, −10%) in the flight agent's member store |
| Hotels | `b73cb84a-fc4e-4c8d-a927-6251fae4c462` | Bonvoy member HB-789 (SILVER, −5%) in the hotel agent's member store |

## Applications

Per-domain model — every specialist environment hosts BOTH a person-login
client (local, direct use of the domain) and an A2A bridge client (delegated
use from the planner):

| Env | App | Client ID | Type / grants | Purpose |
|---|---|---|---|---|
| Planner | `travel-ui` | `a553fbcd-a0c7-4291-b1f6-f1667147e8c1` | WEB_APP · AUTH_CODE, PKCE S256 REQUIRED, **public** (token auth = NONE) | The chat UI's login; redirect `http://localhost:5173/auth/callback` |
| Planner | `loyalty-lookup` | `0742209d-5092-42c1-958d-4bba38b13720` | WORKER · **CLIENT_CREDENTIALS only** | Specialists' client for the planner profile API |
| Flights | `flights-web` | `6dccbd2a-a4a1-4617-8dd9-60643876607c` | WEB_APP · AUTH_CODE, PKCE S256 REQUIRED, **public** | Person login LOCAL to the flight domain; redirect `http://localhost:8080/auth/callback` |
| Flights | `a2a-bridge` | `46f0882e-40ce-43da-8c24-c08826718f08` | WORKER · CLIENT_CREDENTIALS + **TOKEN_EXCHANGE** | The planner agent's actor/exchange client at the flight tenant |
| Hotels | `hotels-web` | `0e587769-2193-4756-a31f-174254da4fbb` | WEB_APP · AUTH_CODE, PKCE S256 REQUIRED, **public** | Person login LOCAL to the hotel domain; redirect `http://localhost:8081/auth/callback` |
| Hotels | `a2a-bridge` | `7db6a04b-9a07-4661-99b9-5983973b582f` | WORKER · CLIENT_CREDENTIALS + **TOKEN_EXCHANGE** | Same, hotel tenant |

Two identity flows into each specialist, both ending in a token about THE
PERSON minted by that domain's own tenant:

1. **Local person login** — direct PKCE at `flights-web`/`hotels-web`; the
   token is native to the domain (no delegation, no act claim).
2. **A2A delegation** — planner exchanges the person's planner token at the
   domain tenant via `a2a-bridge`; the minted token carries
   `act={sub: a2a-bridge}` distinguishing delegated from direct.

> **Type note:** exchange/lookup clients are WORKERs (CC-only, no
> AUTHORIZATION_CODE forced onto them — the earlier web-app workaround is
> gone). PingOne still restricts WORKER custom-resource grants; whether the
> bridge needs a scope grant at all (audience-param TE) is settled in the
> token-exchange spike.

## Resources & scopes

| Env | Resource | Audience | Scope |
|---|---|---|---|
| Flights | A2A Flight API (`b328b159-…`) | `http://localhost:8080` | `a2a:book` (`ed8a7fc1-…`) |
| Hotels | A2A Hotel API (`b25de1a3-…`) | `http://localhost:8081` | `a2a:book` (`d9cc7889-…`) |
| Planner | Planner Profile API (`9f9793ec-…`) | `planner-profile-api` | `loyalty:read` (`948cb9fd-…`) |

Grants: WORKER apps don't use them (PingOne restricts WORKER grants to the
built-in `openid` resource). What puts a custom `aud`/claims into minted
tokens is **scope mapping**: scope defined on the Resource, then assigned
to the application (Applications → app → Resource Access/Scopes in the
console, or `POST /applications/{id}/scopes` on the management API). Each
`a2a-bridge` maps its domain's `a2a:book`; `loyalty-lookup` maps
`loyalty:read`. Tokens requested with those scopes then carry
`aud = <resource audience>`.

## The identity flow

```
Browser ── PKCE login @ planner tenant ──▶ Bearer <planner-user-token> on /agui
Planner: validates token (planner JWKS) → contextvar
Planner ── per delegation: RFC 8693 at the TARGET tenant's /as/token
           subject_token = planner-user-token (cross-issuer, same org)
           actor_token   = travel-planner CC at that tenant
           audience      = the specialist's A2A base URL
           → token: sub=<human in target env>, act={sub: travel-planner},
             aud=<specialist URL>, scope=a2a:book
Specialist /a2a middleware: validates own tenant JWKS/iss/aud/act →
           identity into ADK session state (user_identity)
Specialist loyalty: CC token @planner (loyalty:read) → GET planner
           /api/profile/loyalty → match member → tier discount on booking
```

## Console-managed values (in `.env`)

The MCP server cannot read/write client secrets or user passwords, and its
application-scope-mapping surface is incomplete. One console pass covers
everything (per app: **Applications → <app> → Resource Access → toggle the
scope**; per user: **Users → chris → password**):

| Env | Action | → `.env` |
|---|---|---|
| Flights | a2a-bridge: copy client secret + map scope `a2a:book` (A2A Flight API) | `P1_FLIGHTS_BRIDGE_CLIENT_SECRET` |
| Hotels | a2a-bridge: copy client secret + map scope `a2a:book` (A2A Hotel API) | `P1_HOTELS_BRIDGE_CLIENT_SECRET` |
| Planner | loyalty-lookup: copy client secret + map scope `loyalty:read` (Planner Profile API) | `P1_LOYALTY_CLIENT_SECRET` |
| all 3 | chris@example.com: set password (same in each) | `DEMO_USER_PASSWORD` |

## Swapping in production PingOne / other IdPs

Everything is driven by issuer URLs + client IDs/secrets:

1. Point `P1_*_ISSUER` at real tenants (`https://auth.pingone.com/<env>/as`).
2. Recreate the apps above (or import); put secrets in the secret manager.
3. The middleware validates whatever issuer its env var names (JWKS
   discovery is standard); the planner exchanges at whatever issuer the
   target config names. No code changes.

## Production evolution: workload-identity actors via TokenExchange-AS

In this demo the actor credential is a PingOne client (CC secret), and the
exchange happens **at the specialist's PingOne tenant** — possible because
all three environments are in one org (first-party cross-environment TE).

When the agents deploy for real, the actor token becomes the **workload
identity** of the platform the agent runs on:

| Agent | Deployment | Actor token |
|---|---|---|
| hotel-agent | k8s (kind → real cluster) | projected ServiceAccount token / EKS Pod Identity JWT |
| flight-agent | Cloud Run | Google-issued identity token (`accounts.google.com`) |

PingOne does not support third-party token exchange (subject from a
non-PingOne / non-org issuer), so the exchange moves to
**[TokenExchange-AS](../TokenExchange-AS/)** — the standalone AS that:

- validates ANY JWT actor by per-token issuer discovery (k8s SA, Google,
  PingOne — same code path; actors require only `exp`/`iat`),
- keeps the same claim semantics (`sub` = human from the subject token,
  `act.sub` = workload identity, nested `act` chains for follow-on
  exchanges),
- consults PingOne Authorize for the delegation decision (P1AZ policy),
- mints the downstream specialist-audience token with its own JWKS.

The agent-side code does not change shape: `auth.py`'s exchange call just
posts to the AS's `/as/token` instead of the specialist tenant's, and the
specialist middleware still validates a token minted about *its* domain.
Trust stays pairwise and lives in IdP/AS config — never in agent code.

- Loyalty data lives in the planner agent's profile store and specialist
  member stores, not in PingOne custom user attributes (custom schema
  needs a management-API worker token; the MCP path intentionally has no
  admin-role escalation). The identity/token layer is fully real.
- Consent is enforced two ways: the target tenant's `act` registration
  (which clients may exchange which users) and the UI's consent cards —
  recorded per specialist before the first delegation. PingOne's native
  TE consent policy is not exercised in this demo.
- `AUTH_REQUIRED=false` by default so the anonymous demo keeps working;
  set it `true` in compose to force the identity path end-to-end.
