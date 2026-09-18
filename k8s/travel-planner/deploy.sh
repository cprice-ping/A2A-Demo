#!/usr/bin/env bash
# travel-planner EKS deploy — all out-of-band steps in one paste-proof run.
# Idempotent: safe to re-run (secret/configmap are replaced, image rebuilt).
#
# Usage:  bash k8s/travel-planner/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/../.."   # repo root

NS=ping-devops-cprice
SECRET=a2a-travel-planner-credentials
CM=a2a-travel-planner-wif
IMAGE=pricecs/a2a-travel-planner:latest

echo "== 1/5 build + push image =="
docker build -q -t "$IMAGE" travel-planner
docker push "$IMAGE"

echo "== 2/5 create secret (values from .env, via temp file) =="
TMP_ENV="$(mktemp)"
TMP_CFG="$(mktemp)"
trap 'rm -f "$TMP_ENV" "$TMP_CFG"' EXIT
grep -E '^(GOOGLE_API_KEY|P1_PLANNER_ISSUER|AS_CLIENT_ID|AS_CLIENT_SECRET)' .env > "$TMP_ENV"
kubectl -n "$NS" create secret generic "$SECRET" --from-env-file="$TMP_ENV" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "== 3/5 WIF credential config -> ConfigMap =="
PROVIDER="projects/3682147732/locations/global/workloadIdentityPools/a2a-eks-pool/providers/a2a-eks-provider"
GSA="a2a-planner@cprice---agentic-demos.iam.gserviceaccount.com"
# beta: the cred-config generator lives only in the beta surface. The
# projected SA token is an OIDC ID token -> file-sourced, no source-type
# flag (that flag means JSON/text format for AWS/Azure sources).
gcloud beta iam workload-identity-pools create-cred-config \
  "$PROVIDER" \
  --service-account="$GSA" \
  --service-account-token-lifetime-seconds=3600 \
  --output-file="$TMP_CFG" \
  --credential-source-file=/var/run/secrets/tokens/token
kubectl -n "$NS" create configmap "$CM" --from-file=credential-config.json="$TMP_CFG" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "== 4/5 apply manifests =="
kubectl apply -f k8s/travel-planner/deployment.yaml
kubectl apply -f k8s/travel-planner/service-ingress.yaml

echo "== 5/5 rollout =="
kubectl -n "$NS" rollout status deploy/a2a-travel-planner --timeout=180s

echo
echo "Done. Verify:"
echo "  curl -s https://a2a-travel-planner.ping-devops.com/a2a/.well-known/agent-card.json | head -c 300"
echo "  kubectl -n $NS logs deploy/a2a-travel-planner --tail=50"
