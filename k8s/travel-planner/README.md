# travel-planner on EKS

Manifests mirroring the `a2a-token-as` pattern (same namespace
`ping-devops-cprice`, `nginx-public` ingress, cert-manager LE TLS).

## Out-of-band prerequisites (once)

1. **Image**: build + push from repo root:
   docker build -t pricecs/a2a-travel-planner:latest travel-planner
   docker push pricecs/a2a-travel-planner:latest

2. **Secret** (never committed): `a2a-travel-planner-credentials` with keys
   GOOGLE_API_KEY, P1_PLANNER_ISSUER, AS_CLIENT_ID, AS_CLIENT_SECRET,
   P1_FLIGHTS_ISSUER, P1_FLIGHTS_BRIDGE_CLIENT_ID,
   P1_FLIGHTS_BRIDGE_CLIENT_SECRET, P1_HOTELS_ISSUER,
   P1_HOTELS_BRIDGE_CLIENT_ID, P1_HOTELS_BRIDGE_CLIENT_SECRET. Same values
   as the local .env (copy from .env; do not paste secrets into transcripts):
   kubectl -n ping-devops-cprice create secret generic \
     a2a-travel-planner-credentials --from-env-file=<(grep -E '^(GOOGLE_API_KEY|P1_PLANNER_ISSUER|AS_CLIENT_ID|AS_CLIENT_SECRET|P1_FLIGHTS|P1_HOTELS)' .env)

3. **k8s SA for WIF** (P1 runbook, already done):
   kubectl -n ping-devops-cprice get sa travel-planner  # annotated with the Google SA

   The workloadIdentityUser binding MUST use the token's real `sub`:
   EKS/GKE SA tokens carry sub = system:serviceaccount:<ns>:<name>, so
   the principal is .../subject/system:serviceaccount:ping-devops-cprice:travel-planner
   (NOT .../subject/kubernetes.io/serviceaccount/<ns>/<name> — that
   subject never occurs in a real token and the binding matches nothing;
   surfaced as IAM_PERMISSION_DENIED iam.serviceAccounts.getAccessToken
   at the impersonation step).

3b. **WIF credential config** (ConfigMap the deployment mounts):

   gcloud beta iam workload-identity-pools create-cred-config \
     projects/3682147732/locations/global/workloadIdentityPools/a2a-eks-pool/providers/a2a-eks-provider \
     --service-account=a2a-planner@cprice---agentic-demos.iam.gserviceaccount.com \
     --service-account-token-lifetime-seconds=3600 \
     --output-file=credential-config.json \
     --credential-source-file=/var/run/secrets/tokens/token

   kubectl -n ping-devops-cprice create configmap a2a-travel-planner-wif \
     --from-file=credential-config.json

   Notes:
   - The credential config is URLs, not a secret — a ConfigMap is correct.
   - --credential-source-file must match the deployment's projected-token
     mount (/var/run/secrets/tokens/token, aud=sts.amazonaws.com).
   - The provider's allowed audiences must include sts.amazonaws.com
     (verify with `providers describe`).
   - If the provider restricts audiences differently, adjust BOTH the
     projected token's audience AND re-generate the cred config (the
     config embeds the expected audience too).

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
- No FLIGHT/HOTEL_AGENT_CARD_URL in the deployment: GAP relationships
  supersede the self-hosted cards entirely (agent.py skips the fetch),
  and there are no specialists in-cluster to fetch cards from anyway.
- Self-hosted compose flavor keeps both env vars set (docker-compose.yml).
- The UI's VITE_* vars point at the planner URL for the hosted flow;
  the local UI (localhost:5173) can target the k8s planner by setting
  the planner base in agents.ts env — CORS_ORIGINS lists the UI origin.
