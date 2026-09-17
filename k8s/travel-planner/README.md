# travel-planner on EKS

Manifests mirroring the `a2a-token-as` pattern (same namespace
`ping-devops-cprice`, `nginx-public` ingress, cert-manager LE TLS).

## Out-of-band prerequisites (once)

1. **Image**: build + push from repo root:
   docker build -t pricecs/a2a-travel-planner:latest travel-planner
   docker push pricecs/a2a-travel-planner:latest

2. **Secret** (never committed): `a2a-travel-planner-credentials` with keys
   GOOGLE_API_KEY, AS_CLIENT_ID, AS_CLIENT_SECRET, P1_FLIGHTS_ISSUER,
   P1_FLIGHTS_BRIDGE_CLIENT_ID, P1_FLIGHTS_BRIDGE_CLIENT_SECRET,
   P1_HOTELS_ISSUER, P1_HOTELS_BRIDGE_CLIENT_ID,
   P1_HOTELS_BRIDGE_CLIENT_SECRET. Same values as the local .env
   (copy from .env; do not paste secrets into transcripts):
   kubectl -n ping-devops-cprice create secret generic \
     a2a-travel-planner-credentials --from-env-file=<(grep -E '^(GOOGLE_API_KEY|AS_CLIENT_ID|AS_CLIENT_SECRET|P1_FLIGHTS|P1_HOTELS)' .env)

3. **k8s SA for WIF** (P1 runbook, already done):
   kubectl -n ping-devops-cprice get sa travel-planner  # annotated with the Google SA

4. **DNS**: a2a-travel-planner.ping-devops.com -> the nginx-public ELB
   (same wildcard/convention as a2a-token-as; cert-manager issues TLS
   once DNS resolves and the ingress exists).

## Deploy

   kubectl apply -f k8s/travel-planner/deployment.yaml
   kubectl apply -f k8s/travel-planner/service-ingress.yaml
   kubectl -n ping-devops-cprice rollout status deploy/a2a-travel-planner

## Notes

- Proxy timeouts are long (AG-UI SSE + A2A delegation run minutes);
  proxy-buffering off for SSE.
- FLIGHT/HOTEL_AGENT_CARD_URL point at a harmless placeholder: with
  GAP_*_ENGINE set, the relationship mode supersedes the local card
  targets (fetch_gap_card). The env values still satisfy module import.
- The UI's VITE_* vars point at the planner URL for the hosted flow;
  the local UI (localhost:5173) can target the k8s planner by setting
  the planner base in agents.ts env — CORS_ORIGINS lists the UI origin.
