# A2A Extension: delegated-identity v2 (ad hoc, untrusted parties)

URI: `https://github.com/cprice-ping/A2A-Demo/extensions/delegated-identity/v2`

Status: **design, not implemented.** This document is the build spec for
phase 1 of [`docs/TRUST-VARIANTS-PLAN.md`](../../../docs/TRUST-VARIANTS-PLAN.md).
Do phase 0 of that plan (extract shared code) first, so this is built once
rather than once per agent.

## Why v2 exists

v1 works because the parties agreed on things in advance: a shared token
exchange server (TokenExchange-AS) both sides trust, an allowlist of actors
(`AUTHORIZED_ACTORS`), an audience URI (`a2a://flights`), and an
out-of-band relationship record. Policy is evaluated live, per request, by
PingOne Authorize.

v2 removes all of that. A planner meets a specialist it has never seen,
run by a party it has no agreement with. **There is no shared anchor.** The
question v2 answers:

> With nothing pre-arranged, what can the receiving agent verify, and how
> much should it let the caller do on that basis?

v2 does **not** replace v1. v1 is the right design for pre-arranged
business relationships with a reachable policy engine. v2 covers the case
v1 cannot: ad hoc relationships. An agent may support both; the extension
URI on the message selects which one applies.

## Design principles

1. **Root authority in the person, not an IdP.** The only party both sides
   can relate to is the human. Delegation is rooted in a key the person
   holds, identified by a DID.
2. **Authority is carried, not looked up.** Everything the receiver needs
   arrives in the message, plus public lookups (DID documents, issuer
   keys). The receiver never calls a party it did not already know.
3. **Trust is a ceiling, not yes/no.** The receiver grants capabilities in
   tiers, and the tier rises with the evidence presented.
4. **Each hop can only narrow.** A delegate can never hold more than its
   delegator granted (attenuation).
5. **Go live only when the stakes justify it.** Revocation is the one
   thing carried authority does badly, so the receiver checks revocation
   live for high-stakes actions only.
6. **Fail closed, and say why.** Every refusal carries a machine-readable
   reason and appears on the trace panel.

## Parties and identifiers

| Party | Identifier | Key custody (demo) |
|---|---|---|
| Person | `did:key` (Ed25519) | Browser: WebCrypto Ed25519, non-extractable, stored in IndexedDB |
| Planner (caller agent) | `did:key` (Ed25519) | Planner container, generated on first start and persisted to a volume |
| Specialist (receiver agent) | `did:web` | Specialist container; DID document served at `/.well-known/did.json` |
| Attestor (third party) | `did:web` | New `attestor` service |
| Status service (person's revocation list) | URL only; content signed by the person's key | New `status` service |

Only `did:key` and `did:web` are accepted. `did:key` resolves locally with
no network call. `did:web` resolves over HTTPS. For local compose only, set
`DID_WEB_ALLOW_HTTP=true` so `did:web:flight-agent%3A8080` resolves to
`http://flight-agent:8080/.well-known/did.json`. Never enable this outside
local development.

The specialist advertises its DID on its agent card (see Discovery). That
DID is the audience every invocation must name.

## Credential format

Every credential is a **compact JWS (JWT)**, `alg: EdDSA`, signed with
Ed25519. This reuses `pyjwt[crypto]`, already a dependency of all three
agents.

This is deliberately *UCAN-inspired, JWT-encoded*, not UCAN 1.0 wire
format (DAG-CBOR envelopes). The goal is to demo the trust model quickly in
Python and TypeScript, not to interoperate with UCAN implementations. The
claim names (`cap`, `prf`) follow UCAN conventions so a later move to UCAN
1.0 is a format change, not a model change.

Common header on all four types:

```json
{ "alg": "EdDSA", "typ": "<type below>", "kid": "<issuer DID>#<key fragment>" }
```

The `kid` must resolve to a verification method in the issuer's DID
document. For `did:key` the fragment is the multibase key itself.

### 1. Delegation: `typ: "a2a-dlg+jwt"`

Grants capabilities from one party to another. The chain starts with a
delegation from the person to the planner.

```json
{
  "iss": "did:key:z6Mk...person",
  "aud": "did:key:z6Mk...planner",
  "iat": 1790000000,
  "nbf": 1790000000,
  "exp": 1790003600,
  "jti": "dlg-7c1e...",
  "cap": [
    { "can": "travel/search", "with": "*" },
    { "can": "travel/hold",   "with": "*", "nb": { "max_total": { "amount": 1500, "currency": "USD" } } },
    { "can": "travel/book",   "with": "*", "nb": { "max_total": { "amount": 1500, "currency": "USD" },
                                                    "requires_approval": true } }
  ],
  "rev": "http://status:8090/lists/did:key:z6Mk...person"
}
```

- `with: "*"` means any provider, which is what makes it ad hoc: the
  person does not know in advance which airline the planner will find.
  A person may instead list specific provider DIDs.
- `nb` holds constraints. v2 defines two: `max_total` and
  `requires_approval`. Unknown constraint keys must cause the receiver to
  refuse (fail closed); they must not be ignored.
- `rev` points to the person's revocation list (see Revocation). It is
  **required** on the root delegation.
- Recommended root lifetime: 1 hour.

### 2. Invocation: `typ: "a2a-inv+jwt"`

Minted by the planner for **one** A2A message to **one** receiver.

```json
{
  "iss": "did:key:z6Mk...planner",
  "aud": "did:web:flight-agent%3A8080",
  "iat": 1790000100,
  "exp": 1790000160,
  "jti": "inv-3f9a...",
  "cap": { "can": "travel/search", "with": "did:web:flight-agent%3A8080" },
  "prf": ["<base64url sha256 of chain[0] compact JWS>", "..."],
  "msg": { "messageId": "<A2A message id>", "parts_sha256": "<base64url>" }
}
```

- `exp - iat` must be 120 seconds or less.
- `prf` lists the hashes of the delegation chain, in order. It binds the
  invocation to that exact chain.
- `msg.parts_sha256` is the SHA-256 of the RFC 8785 (JCS) canonical JSON of
  `message.parts`. It binds the invocation to the message content, so a
  captured invocation cannot be attached to a different request.

### 3. Attestation: `typ: "a2a-att+jwt"`

A third party vouches for the planner as software.

```json
{
  "iss": "did:web:attestor%3A8091",
  "sub": "did:key:z6Mk...planner",
  "iat": 1790000000,
  "exp": 1790604800,
  "jti": "att-...",
  "agent": { "name": "travel-planner", "version": "0.2.0", "build_digest": "sha256:..." },
  "assurance": "vetted-build"
}
```

In the demo the attestor issues on request when the planner presents a
known build digest. That is a stand-in for a real vetting process; the doc
and the UI must say so. What matters for the demo is the receiver's side:
it decides which attestors it recognizes, and nobody else decides for it.

### 4. Approval: `typ: "a2a-apv+jwt"`

The person approves one specific transaction. This is the step-up.

```json
{
  "iss": "did:key:z6Mk...person",
  "aud": "did:web:flight-agent%3A8080",
  "iat": 1790000200,
  "exp": 1790000500,
  "jti": "apv-...",
  "challenge": "<nonce issued by the receiver>",
  "txn": {
    "can": "travel/book",
    "offer": "SW100-2026-09-20",
    "passengers": 2,
    "total": { "amount": 412.00, "currency": "USD" }
  }
}
```

`txn` must equal, field for field, the transaction object the receiver
issued in its challenge. The receiver defines the terms and the person
signs exactly those terms.

## Wire contract

The caller sends, per message:

| Where | Value |
|---|---|
| `message.metadata["a2a_demo_identity_v2"]` | Object below |
| `message.metadata["a2a_extensions"]` | `[<this URI>]` (activation signal, as in v1) |
| `X-A2A-Extensions` header | `<this URI>` (where headers reach the agent) |

```json
{
  "chain": ["<delegation JWS>", "..."],
  "invocation": "<invocation JWS>",
  "attestations": ["<attestation JWS>", "..."],
  "approval": "<approval JWS, only when answering a challenge>"
}
```

Unlike v1, there is **no transport bearer**. The credential lives only in
message metadata.

## Discovery

The receiver's card declares the extension in `capabilities.extensions`,
with parameters:

```json
{
  "uri": "https://github.com/cprice-ping/A2A-Demo/extensions/delegated-identity/v2",
  "required": false,
  "params": {
    "did": "did:web:flight-agent%3A8080",
    "did_methods": ["did:key", "did:web"],
    "tiers": {
      "travel/search": ["chain"],
      "travel/hold":   ["chain", "attestation"],
      "travel/book":   ["chain", "attestation", "approval"]
    }
  }
}
```

Publishing the tier table lets a caller know in advance what evidence each
action needs, rather than learning by being refused.

**v2 is self-hosted only.** Google Agent Platform strips
`capabilities.extensions` and requires IAM to read a card. That makes
discovery itself a pre-arranged relationship, which is exactly what v2
exists to avoid. This is a finding worth stating in the demo, not a
limitation to hide.

### Runtime discovery

In v2 the planner is **not** configured with `FLIGHT_AGENT_CARD_URL` or
`HOTEL_AGENT_CARD_URL`. A specialist's card URL arrives at runtime: typed
by the person, or chosen from a directory the planner does not control.
The planner fetches the card anonymously, reads the extension params
(`did`, `did_methods`, `tiers`), and uses the card's `did` as the
invocation audience.

If the card does not declare the v2 extension, the planner does not call
that agent in v2 mode. It reports that the agent does not support ad hoc
delegation.

## Deployment

A single compose file on one machine is still one trust domain in
disguise. Compose (an `adhoc` profile, with `DID_WEB_ALLOW_HTTP=true`) is
for development. The deployment that is shown to people separates the
parties:

| Party | Example host | Notes |
|---|---|---|
| Planner + UI | EKS (existing) | No specialist URLs in its config |
| Flight agent A | Cloud Run (`deploy-cloud-run.sh` exists) | Own HTTPS domain, so `did:web` resolves normally |
| Flight agent B ("the stranger") | A different project or host | Operated as a different party (see scenario 13) |
| Attestor | Its own host | |
| Status | Its own host | Never co-hosted with the planner |

Each receiver's configuration names **no** planner: no actor allowlist and
no pre-agreed audience. Its only trust setting is
`RECOGNIZED_ATTESTORS`.

## Receiver verification algorithm

Run in this order. Any failure ends processing with the reason code shown.

1. **Activation.** The extension URI is present and the metadata object
   parses. Otherwise → `v2_malformed`.
2. **Resolve keys.** Resolve every DID referenced (issuers of chain links,
   invocation, attestations, approval). Cache `did:web` documents for
   5 minutes. Unsupported method or failed resolution → `did_unresolvable`.
3. **Verify the chain.** For each link `chain[i]`:
   - The signature verifies against `iss`'s key, and `kid` belongs to `iss`.
     Otherwise → `chain_invalid`.
   - `typ` is `a2a-dlg+jwt`. The time is within `nbf`/`exp`, with 30s leeway
     (matches v1's `LEEWAY`). Otherwise → `chain_invalid`.
   - For `i > 0`: `chain[i].iss == chain[i-1].aud`, and
     `chain[i].exp <= chain[i-1].exp`. Otherwise → `chain_broken`.
   - For `i > 0`: every entry in `chain[i].cap` is covered by some entry in
     `chain[i-1].cap` (see Attenuation). Otherwise → `cap_escalation`.
   - `chain[0].rev` is present. Otherwise → `chain_invalid`.
4. **Verify the invocation.**
   - The signature verifies, and `iss == chain[-1].aud`. Otherwise →
     `invocation_invalid`.
   - `aud` equals the receiver's own DID. Otherwise → `audience_mismatch`.
   - `exp - iat <= 120` and the time is within `exp`. Otherwise →
     `invocation_invalid`.
   - `(iss, jti)` has not been seen before. Store it until `exp` plus
     leeway. Otherwise → `replay`.
   - `prf` equals the hashes of `chain`, in order. Otherwise → `chain_broken`.
   - `msg.messageId` and `msg.parts_sha256` match the actual message.
     Otherwise → `message_mismatch`.
   - `cap.with` is the receiver's DID, and `cap` is covered by the chain's
     final capabilities. Otherwise → `cap_exceeded`.
5. **Map the capability to the receiver's own action.** For example,
   `travel/search` maps to `search_flights`. The tool the LLM actually
   calls must match the invoked `can`. That check runs in the tool
   layer, not the prompt.
6. **Collect the evidence** (see Tier policy) and decide.
7. **Record the decision** on the trace panel, as `auth.v2.*` rows.

### Attenuation

Capability B is covered by capability A when:

- `B.can == A.can`, and
- `A.with == "*"`, or `B.with == A.with`, and
- for each constraint in `A.nb`, B has the same constraint at least as
  strict: `max_total` less than or equal, in the same currency;
  `requires_approval: true` cannot be dropped.

There are no wildcards in `can` in v2. Keep the check simple and
exhaustive.

## Tier policy (receiver-local)

The tier policy belongs to the receiver. It is configuration, not
protocol.

| Invoked capability | Required evidence | Revocation check |
|---|---|---|
| `travel/search` | Valid chain and invocation | None: bounded by delegation TTL |
| `travel/hold` | Plus at least one attestation from a recognized attestor, with `sub == invocation.iss` | Live, against `chain[0].rev` |
| `travel/book` | Plus an approval from `chain[0].iss` that matches an open challenge | Live, against `chain[0].rev` |

Configuration:

```
IDENTITY_V2=true
RECOGNIZED_ATTESTORS=did:web:attestor%3A8091
V2_UNATTESTED_SEARCH_RATE=10/min     # receiver-local ceiling for unattested callers
DID_WEB_ALLOW_HTTP=true              # compose only
```

When evidence is missing for a higher tier, the receiver refuses with
`attestation_required` or `approval_required`. It does not silently fall
back to a lower tier.

### Step-up flow (booking)

1. The planner invokes `travel/book` without an approval.
2. The receiver checks everything else. If that passes, it refuses with
   `approval_required` and returns a challenge in a data part:
   `{ "challenge": "<nonce>", "txn": {...}, "exp": <ts> }`. The receiver
   keeps the challenge for 5 minutes.
3. The planner surfaces the challenge to the UI through an AG-UI frontend
   tool (`request_approval`). The UI shows the exact `txn` and the
   receiver's DID, and the person signs an approval with their key.
4. The planner re-sends the booking with `approval` set and a fresh
   invocation. The receiver checks that the approval's issuer is
   `chain[0].iss`, that `aud` is itself, that the challenge is open and
   unused, and that `txn` matches field for field. It then consumes the
   challenge.

Use refuse-then-retry rather than A2A's `auth-required` task state for
the first build, because it is simpler to test. The planner's v2 path
calls specialists with the a2a-sdk client directly (see Components), so
the round trip is under our control either way. If the a2a-sdk version in
use supports `auth-required` cleanly end to end, it is a nicer protocol
fit and can replace step 2 later.

## Revocation

Carried authority cannot be recalled mid-flight, so v2 scales liveness to
the stakes:

- **Search:** no live check. Revocation takes effect when the root
  delegation expires (at most 1 hour).
- **Hold and book:** the receiver fetches `chain[0].rev` and refuses if the
  root delegation's `jti` is listed → `revoked`. Cache for at most 30 seconds.

The revocation list is JSON signed by the person's key:

```json
{ "iss": "did:key:z6Mk...person", "iat": 1790000300, "revoked": ["dlg-7c1e..."] }
```

It is sent as a JWS with `typ: "a2a-rev+jwt"`. The receiver verifies it
against `chain[0].iss`, so the status service is only storage. It cannot
forge or suppress entries without that showing up as an invalid signature
or a stale `iat`.

Two rules for the demo:

- The status service **must not** be run by the planner. The party being
  revoked cannot host the list that revokes it. In compose it is its own
  service.
- If the list cannot be reached, hold and book fail closed with
  `revocation_unavailable`. Search is unaffected.

A later variant could host the list as a record in the person's own
ATProto PDS. That would give the person-controlled storage this design
assumes.

## Components to build

| Component | Language | Work |
|---|---|---|
| `trust/adhoc/` shared package | Python | DID resolution (`did:key`, `did:web`), JWS sign and verify, chain verification, attenuation, JCS hashing, replay cache, tier policy. One implementation, used by every receiver and the planner. |
| UI | TypeScript | Person key generation (WebCrypto Ed25519, non-extractable, IndexedDB) and display of the person's `did:key`. A **Grant** screen that shows the capabilities and limits, then signs the root delegation. A **`request_approval`** frontend tool that shows `txn` and the receiver's DID, then signs the approval. A **Revoke** button that publishes a signed revocation list to `status`. |
| travel-planner | Python | Its own `did:key` (persisted). Fetches an attestation from `attestor` at startup. Holds the person's root delegation per session. **Runtime discovery:** no configured specialist card URLs in v2 mode; takes a card URL at runtime and reads the extension params. **Calls specialists with the a2a-sdk client directly**, not `RemoteA2aAgent` + `AgentTool`, building a fresh invocation per message. Handles `approval_required` by calling `request_approval`, then retries. Selection by `IDENTITY_MODE=v1\|v2\|off`; v1 keeps its existing path. |
| flight-agent (receiver) | Python | Serves its DID document. Card declares the v2 extension with params. **Owns its A2A executor** (a2a-sdk), so v2 verification runs in our code before the request reaches the agent; ADK can still run the model loop behind it. v2 is selected by extension URI, alongside v1. Tier policy, challenges, revocation fetch, `auth.v2.*` trace rows. The tool layer enforces that the invoked `can` matches the tool called. **New:** the mock API has only search and book today, so add `POST /flights/hold` and a `hold_flight` tool (hold expires after 15 minutes; a booking may reference a hold). For challenges, the receiver computes `txn.total` from its own fare data for `flight_id` × `passengers`, and never takes the price from the caller. |
| hotel-agent | Python | Same as flight-agent, in phase 2 or later. Flight alone is enough to prove the model. |
| flight-agent B ("the stranger") | Config only | A second deployment of the flight agent, operated as a different party: different DID and domain, a different `RECOGNIZED_ATTESTORS` list (not including the demo attestor), and stricter tiers (for example, hold requires approval). No code of its own. |
| `attestor` | Python, FastAPI | New, small. A `did:web` document and `POST /attest` for known build digests. |
| `status` | Python, FastAPI | New, small. `PUT` and `GET /lists/{did}` storing signed lists. Verifies the signature on write and rejects an `iat` older than the stored list's. |
| Rogue planner mode | Python | Planner flags that produce the negative scenarios below. Test-only; off by default. |

Keep v1 working. `AUTH_REQUIRED=false` with `IDENTITY_MODE=off` must still
run the anonymous demo exactly as today.

## Demo scenarios (acceptance tests)

Each is an automated end-to-end test that asserts the outcome and the
trace rows. The honest path runs through the UI; the negative paths run
through rogue planner mode.

| # | Scenario | Setup | Expected |
|---|---|---|---|
| 1 | Honest search | Valid chain | Results returned; trace `auth.v2.tier=search` |
| 2 | Honest hold | Plus a recognized attestation | Hold succeeds; trace shows the live revocation check |
| 3 | Honest booking | Plus approval via UI | `approval_required` first, then success after the person signs |
| 4 | Overreach | Chain grants search only, planner invokes book | `cap_exceeded` |
| 5 | Escalation in chain | Planner forges a second link with a higher `max_total` | `cap_escalation` |
| 6 | Replay | Same invocation sent twice | Second one gets `replay` |
| 7 | Wrong audience | Invocation minted for hotel-agent, sent to flight-agent | `audience_mismatch` |
| 8 | Content swap | Valid invocation attached to a different message | `message_mismatch` |
| 9 | Unknown attestor | Self-issued attestation (`did:web` not in `RECOGNIZED_ATTESTORS`) | Hold refused with `attestation_required`; search still works |
| 10 | Approval mismatch | Person approves $412, planner sends booking for $812 | Approval rejected, booking refused |
| 11 | Revocation | Person clicks Revoke mid-session | Hold and book refused with `revoked` within 30s; search keeps working until the root expires. **Show this gap on screen; it is the point.** |
| 12 | Status service down | Stop `status` | Hold and book refused with `revocation_unavailable`; search unaffected |
| 13 | The stranger | Same planner and delegation, sent to flight agent B | Search works; hold refused with `attestation_required` (B does not recognize the demo attestor). Shows that each receiver sets its own ceiling. |

Unit tests for `trust/adhoc/`: every reason code, attenuation edge cases
(currency mismatch, dropped `requires_approval`, unknown `nb` key), JCS
hashing against RFC 8785 test vectors, and `did:key` round trips.

## Build phases

1. **`trust/adhoc/` package, plus search tier on flight-agent.** UI key and
   Grant screen, runtime discovery, planner invocation. Scenarios 1, 4 to 8.
2. **Attestation and hold.** `attestor` service, flight agent B. Scenarios
   2, 9 and 13.
3. **Step-up booking.** Challenge, `request_approval`, retry. Scenarios 3
   and 10.
4. **Revocation.** `status` service, Revoke button. Scenarios 11 and 12.
5. **Stretch: multi-hop.** The planner adds a planner → flight-agent
   delegation to the chain. The flight agent invokes a downstream agent
   (for example a seat-map agent) with a chain of two links. The
   downstream agent verifies the full person → planner → flight path
   without calling anyone. This is the case v1 cannot show.

## Non-goals

- Replacing v1, or running v2 on Google Agent Platform.
- Production key custody, key recovery, or key rotation for the person.
- Interoperability with UCAN 1.0 or W3C Verifiable Credentials.
- Proving that `chain[0].iss` is a human. See open questions.

## Open questions

1. **Is the root a person?** The receiver sees a key, not a human. A bot
   can hold a `did:key` too. Options: a personhood attestation on the root,
   or using a WebAuthn/passkey assertion for approvals (proves user
   presence, but needs WebAuthn verification in the receiver). The demo
   should state that this is unsolved.
2. **Person key custody.** A WebCrypto key in one browser is fragile. A
   passkey-backed key or a `did:plc` with rotation (ATProto) would fix
   recovery, at the cost of complexity.
3. **Where the revocation list lives** outside the demo: a person's PDS, a
   wallet provider, or a status service they choose.
4. **Liability.** When a receiver acts on a valid chain and the outcome is
   bad, who is accountable: the person, the planner's operator, or the
   attestor? The protocol records the evidence but does not answer this.
5. **Relationship to v1.** When should a receiver that supports both
   prefer v1? A reasonable rule: prefer v1 when a relationship record
   exists for the caller, and use v2 otherwise.
