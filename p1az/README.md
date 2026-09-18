# P1AZ policy snapshot

`policy-snapshot.json` (added by the repo owner) is an export/snapshot of
the PingOne Authorize delegation policy that governs the TokenExchange-AS
decisions in this demo — sanitized: client IDs/secrets used by the
Introspect call are replaced with placeholders.

Companion docs:
- docs/PINGONE-PLANNER-ENV.md — the environment build order the policy assumes
- GCP-DEPLOYMENT.md — "Presence, not anonymity": the three-rung model the
  policy rows encode (person row → a2a:book; person-less row → search only)
