# A2A Extension: delegated-identity v1

URI: `https://github.com/cprice-ping/A2A-Demo/extensions/delegated-identity/v1`

## What it declares

An agent that supports this extension accepts a **delegated (OBO) identity**
carried in-message on A2A requests. It answers "who is using the agent, and
through which intermediary" without relying on the transport bearer — which
matters wherever an edge (Google Agent Platform, a gateway) terminates the
transport credential before the agent runs.

## Wire contract

The **caller** sends, per message:

| Where | Value |
|---|---|
| `message.metadata["a2a_demo_identity"]` | The OBO access token (JWT) |
| `message.metadata["a2a_extensions"]` | `[<this URI>]` (activation signal) |
| `X-A2A-Extensions` header | `<this URI>` (transport-visible activation, where headers reach the agent) |

## Token semantics (what the agent validates)

The token MUST be minted by a token exchange (RFC 8693) and carries:

- `sub` — the **person** on whose behalf the request runs (context: whose
  trip, whose loyalty)
- `act.sub` — the **intermediary** (the calling agent's registered client
  id) that obtained the token
- `aud` — the **destination agent's relationship URI** (e.g. `a2a://hotels`).
  Audience binding is the load-bearing property: the token is worthless at
  any other agent, so the receiving specialist only ever sees tokens
  addressed to it.
- `scope` — the delegation scope the destination agreed to (e.g. `a2a:book`)

Validation is in-agent: signature against the minting AS's JWKS, `iss`,
`aud` = own relationship URI, `act.sub` against an allowlist, `exp`/leeway.
Rejection is a 401 (or an in-agent error surfaced to the caller) — never
silent degradation.

## Discovery

- Self-hosted agents: the extension appears in the card's
  `capabilities.extensions` (URI + description, `required: false` —
  anonymous search stays possible where policy allows).
- GAP-hosted agents: GAP serves cards from a fixed field allowlist and
  strips `capabilities.extensions`; for those targets the extension
  clause lives in the caller's **relationship record** (the same
  out-of-band contract store that carries the audience URI and scope —
  see GCP-DEPLOYMENT.md, "The business relationship").

## Reference implementation

- Caller side: `travel-planner/src/travel_planner/agent.py`
  (`_identity_meta_provider_for`, `IDENTITY_EXTENSION_URI`)
- Agent side: `flight-agent/src/flight_agent/gap_agent.py`
  (`GapExecutorAdapter` — metadata read + validation), declared in
  `flight_agent/card.py` / `hotel_agent/card.py`
