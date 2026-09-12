#!/usr/bin/env bash
# Deploy the flight agent to Cloud Run with a Vertex AI model backend.
#
# No GOOGLE_API_KEY anywhere: model calls authenticate with the Cloud Run
# service account's Application Default Credentials (roles/aiplatform.user).
#
# Prerequisites:
#   gcloud auth login && gcloud config set project <project>
#   (deployer needs roles/iam.serviceAccountUser on the runtime SA)
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE="flight-agent"
RUN_SA="flight-agent-run@${PROJECT}.iam.gserviceaccount.com"

if [ -z "$PROJECT" ] || [ "$PROJECT" = "None" ]; then
  echo "ERROR: no gcloud project configured (gcloud config set project ...)" >&2
  exit 1
fi

echo "Project: $PROJECT  Region: $REGION  Service: $SERVICE"

echo "--- Enable APIs ---"
gcloud services enable aiplatform.googleapis.com run.googleapis.com cloudbuild.googleapis.com --project "$PROJECT"

echo "--- Runtime service account ---"
if ! gcloud iam service-accounts describe "$RUN_SA" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create flight-agent-run --project "$PROJECT" --display-name "flight-agent Cloud Run runtime"
fi
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:${RUN_SA}" --role roles/aiplatform.user --quiet >/dev/null

echo "--- Deploy (first pass) ---"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --source . \
  --port 8080 \
  --allow-unauthenticated \
  --service-account "$RUN_SA" \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=${REGION}"

echo "--- Bootstrap PUBLIC_BASE_URL (card must advertise the real URL) ---"
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
gcloud run services update "$SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --update-env-vars "PUBLIC_BASE_URL=${URL},CORS_ORIGINS=http://localhost:5173"

echo "--- Smoke test ---"
curl -sf "${URL}/a2a/.well-known/agent-card.json" | python3 -c "import json,sys; d=json.load(sys.stdin); print('card:', d['name'], '| url:', d['supportedInterfaces'][0]['url'])"
curl -sf "${URL}/api/health" >/dev/null && echo "health: OK"
echo
echo "Deployed: ${URL}"
echo "  AG-UI chat: ${URL}/agui"
echo "  A2A card:   ${URL}/a2a/.well-known/agent-card.json"
