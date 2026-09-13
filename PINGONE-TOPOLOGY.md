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

| Env | App | Client ID | Type / grants | Purpose |
|---|---|---|---|---|
| Planner | `travel-ui` | `a553fbcd-a0c7-4291-b1f6-f1667147e8c1` | WEB_APP · AUTH_CODE, PKCE S256 REQUIRED, **public** (token auth = NONE) | The chat UI's login; redirect `http://localhost:5173/auth/callback` |
| Flights | `travel-planner` | `da2ff827-114a-448c-92ae-5297e9fcdb9a` | WEB_APP · AUTH_CODE + CLIENT_CREDENTIALS + **TOKEN_EXCHANGE** | The planner agent's actor/subject-exchange client at the flight tenant |
| Hotels | `travel-planner` | `e629c4f9-4533-4c5c-a7bb-78e32620e000` | WEB_APP · same grants | Same, hotel tenant |
| Planner | `loyalty-lookup` | `30ef8221-9da2-42d5-8556-9e40ca53e8ea` | WEB_APP · CLIENT_CREDENTIALS | Specialists' client for the planner profile API |

> **Why WEB_APP, not WORKER:** PingOne restricts WORKER applications to grants
> on the built-in `openid` resource only — a WORKER cannot be granted custom
> resources/scopes. Web apps can carry `CLIENT_CREDENTIALS` +
> `TOKEN_EXCHANGE` and hold custom-resource grants, so the service clients
> are web apps hidden from the application portal.

## Resources & scopes

| Env | Resource | Audience | Scope |
|---|---|---|---|
| Flights | A2A Flight API (`b328b159-…`) | `http://localhost:8080` | `a2a:book` (`ed8a7fc1-…`) |
| Hotels | A2A Hotel API (`b25de1a3-…`) | `http://localhost:8081` | `a2a:book` (`d9cc7889-…`) |
| Planner | Planner Profile API (`9f9793ec-…`) | `planner-profile-api` | `loyalty:read` (`948cb9fd-…`) |

Grants: each `travel-planner` app → its own API resource/scope;
`loyalty-lookup` → Planner Profile API/`loyalty:read`.

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

The MCP server cannot read/write client secrets or user passwords. Set once
in the PingOne console:

- `P1_FLIGHTS_PLANNER_CLIENT_SECRET` (Flights env → travel-planner app)
- `P1_HOTELS_PLANNER_CLIENT_SECRET` (Hotels env → travel-planner app)
- `P1_LOYALTY_CLIENT_SECRET` (Planner env → loyalty-lookup app)
- `DEMO_USER_PASSWORD` — same password for chris@example.com in all three envs

## Swapping in production PingOne / other IdPs

Everything is driven by issuer URLs + client IDs/secrets:

1. Point `P1_*_ISSUER` at real tenants (`https://auth.pingone.com/<env>/as`).
2. Recreate the apps above (or import); put secrets in the secret manager.
3. The middleware validates whatever issuer its env var names (JWKS
   discovery is standard); the planner exchanges at whatever issuer the
   target config names. No code changes.

## Honest limitations (demo scope)

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
