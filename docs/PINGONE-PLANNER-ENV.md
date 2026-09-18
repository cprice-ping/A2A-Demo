# PingOne environment config for the Planner (runbook)

An agent-facing document: what to create in a PingOne environment so the
travel-planner (and its TokenExchange-AS + P1AZ) runs against it. Written
as a build order — do the steps in order; later steps reference earlier
IDs. Every value lands in `.env` (git-ignored) or k8s secrets, never in
the repo.

Terminology: "the planner environment" is the PingOne sandbox the demo
person logs into AND where P1AZ evaluates delegation policy. The
specialist tenants (flights/hotels) are only needed for the SELF-HOSTED
flavor (compose) — the GAP journey needs exactly ONE PingOne environment.

## 1. Environment

- Create (or pick) a sandbox environment in your PingOne org. Record:
  - `P1_PLANNER_ENV_ID` — the environment UUID
  - `P1_PLANNER_ISSUER` — `https://auth.pingone.com/<envId>/as`
  These two strings are the planner's issuer in all config: the UI's
  PKCE login, the planner's token validation (JWKS discovery from this
  URL), and the AS's subject validation all derive from it.

## 2. Population + demo user

- Population (any name; `Default` works).
- One user for the demo person (e.g. `chris@example.com`) — set a
  password (console-only; the MCP/API path cannot set passwords).
  Record `DEMO_USER_PASSWORD` in `.env` (used by headless tests only).

## 3. Person-login application (the UI's client)

- Application → + → **Web App** (OpenID Connect):
  - Name: `travel-ui`
  - Grant: Authorization Code, **PKCE: S256 REQUIRED**
  - Token endpoint auth: **NONE** (public client — it's a browser SPA)
  - Redirect URIs:
    - `http://localhost:5173/auth/callback` (local dev)
    - `https://<your-ui-host>/auth/callback` (deployed UI)
  - Scopes: `openid profile email` (defaults are fine)
- No secret needed (public client). Record the client ID for the UI
  config (`VITE_PLANNER_CLIENT_ID` local / `uiClientId` in the UI's
  runtime config) — not a secret.

## 4. Protected resource + loyalty scope (self-hosted flavor only)

The GAP journey resolves loyalty from the SPECIALIST's own records
(pushed member reference). This resource exists for the self-hosted
pull path; create it now so the profile API has an issuer if you ever
run that flavor:

- Resources → + → **Planner Profile API**
  - Audience: `planner-profile-api`
  - Scope: `loyalty:read`
- Application `a2a-bridge` (below) gets this scope assigned
  (Resource Access → toggle).

## 5. Exchange client at the TokenExchange-AS

The AS authenticates the EXCHANGE CALL (RFC 8693 request) with a client
credential. This client is NOT the delegation actor — it only
authenticates who is asking:

- Application → + → **Worker** (or model on a CC reference app):
  - Name: `tokenexchange` (the AS's configured client)
  - Grant: **Client Credentials** + **Token Exchange** (if your tenant
    exposes the grant toggle; the AS code path only needs CC auth)
  - Secret: console-set; goes into the AS's k8s secret as
    `TOKEN_CLIENT_ID` / `TOKEN_CLIENT_SECRET` (also referenced by the
    planner as `AS_CLIENT_ID` / `AS_CLIENT_SECRET`).

## 6. PingOne Authorize (P1AZ)

P1AZ is the decision point the AS consults for every delegation. In the
planner environment:

- Enable PingOne Authorize for the environment (license permitting).
- Create a **decision endpoint**; record its ID →
  `P1AZ_DECISION_ENDPOINT_ID`.
- Create a **worker client** the AS uses to call the decision endpoint:
  - Name: `token-as-p1az-worker`
  - Grant: Client Credentials; secret console-set →
    `P1AZ_WORKER_CLIENT_ID` / `P1AZ_WORKER_CLIENT_SECRET`.
- Author the delegation policy. The snapshot in this repo
  (`p1az/policy-snapshot.json`, sanitized) is the exact working shape:

| Policy element | Matches | Effect |
|---|---|---|
| **TrustedIssuers** | `https://auth.pingone.com/<plannerEnvId>/as`, `https://a2a-token-as.ping-devops.com` (your AS host), `https://oidc.eks.us-east-2.amazonaws.com/id/<clusterId>` | who may present tokens for exchange — person tokens (planner tenant), the AS itself, and the k8s cluster's actor JWTs |
| **Person row** | subject from planner tenant + actor = `system:serviceaccount:<ns>:<name>` + aud `a2a://flights\|hotels` + scope `a2a:book` | PERMIT → the AS mints the OBO |
| **Person-less row (optional)** | same but subject = the SA subject itself, scope `a2a:search` (no `a2a:book`) | workload sessions may search, never book (see GCP-DEPLOYMENT.md, "Presence, not anonymity") |
| **Introspection** | the AS introspects the person's access token at the planner tenant before minting | an out-of-session person can't be exchanged for — the "master switch" |

The snapshot lives in `p1az/` — import it (or recreate the rows) and
replace the sanitized client references with your own IDs.

## 7. Environment values → where they go

```
.env (never committed)                     AS k8s secret
──────────────────────────────────────     ─────────────────────────────
P1_PLANNER_ENV_ID                          TOKEN_CLIENT_ID / TOKEN_CLIENT_SECRET   (§5)
P1_PLANNER_ISSUER                          P1AZ_ENVIRONMENT_ID                     (§6)
AS_CLIENT_ID / AS_CLIENT_SECRET            P1AZ_DECISION_ENDPOINT_ID               (§6)
GOOGLE_API_KEY (planner LLM key)           P1AZ_WORKER_CLIENT_ID / _SECRET         (§6)
```

The planner deployment reads only: `GOOGLE_API_KEY`, `P1_PLANNER_ISSUER`,
`AS_CLIENT_ID`, `AS_CLIENT_SECRET` (see `k8s/travel-planner/deploy.sh`,
which greps exactly those from `.env`). Everything AS-side is the AS
repo's secret.

## 8. Trust registrations (who trusts whom — the four registrations)

The environment work above is half the setup; the other half is the
RELATIONSHIP registrations described in GCP-DEPLOYMENT.md
("Registration requirements"):

1. Google IAM binding (planner's WIF identity → `roles/aiplatform.user`
   on each GAP engine)
2. Specialist `AUTHORIZED_ACTORS` env naming the planner's k8s SA subject
3. The P1AZ delegation row (§6)
4. The planner's relationship record (its own config; TARGET_RELATIONSHIPS)

Nothing registers a PingOne client at any specialist — that is the
point of the design.

## What you should see when it's right

- UI login lands with a planner-tenant person token (JWKS URL = §1 issuer).
- Planner trace shows `auth.user` → `auth.token_exchange` (P1AZ-gated)
  → `a2a.outbound` with identity + loyalty ref → specialist
  `auth.accepted`.
- Without a P1AZ permit: exchange fails fast (`auth.token_exchange_failed`)
  and the planner falls back to a raw-token delegation, which the GAP
  specialists then refuse in-agent — no silent degradation anywhere.
