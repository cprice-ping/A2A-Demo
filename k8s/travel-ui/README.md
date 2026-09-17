# travel-ui on EKS

Static SPA served by nginx; the browser talks directly to the planner
(`a2a-travel-planner.ping-devops.com`) over AG-UI/A2A — the UI pod is
stateless static files.

## Out-of-band steps

1. **Image**:
   docker build -t pricecs/a2a-travel-ui:latest ui
   docker push pricecs/a2a-travel-ui:latest

2. **Runtime config ConfigMap** (agent URLs + auth; public values, no
   secrets — the OIDC client is public/PKCE):

```bash
kubectl -n ping-devops-cprice create configmap a2a-travel-ui-config \
  --from-literal=config.js='window.__A2A_CONFIG__ = {
  flight: "https://a2a-travel-ui.ping-devops.com/disabled-flight",
  hotel: "https://a2a-travel-ui.ping-devops.com/disabled-hotel",
  planner: "https://a2a-travel-planner.ping-devops.com",
  plannerIssuer: "https://auth.pingone.com/<PLANNER_ENV_ID>/as",
  uiClientId: "<travel-ui CLIENT_ID>",
  deployment: "gap",
};'
```

   - planner: the public planner (browser -> planner HTTPS; the UI pod
     never proxies it)
   - deployment: "gap" — specialists are GAP-hosted (agent-only): their
     card strip entries render the 🔒 GAP honesty state and no card is
     fetched (a browser holds no Google credential; GAP cards are
     IAM-gated). Use "local" (or omit) when specialists run in compose.
   - flight/hotel: GAP-hosted specialists have NO AG-UI surface — their
     tabs render the agent-only honesty state (P6). Point them anywhere
     unreachable; the tabs do not fetch cards when retired.
   - plannerIssuer/uiClientId: same values as ui/.env.local (names only
     in transcripts; these two are not secrets).

3. **DNS**: a2a-travel-ui.ping-devops.com -> the nginx-public ELB
   (same convention as the AS + planner).

4. **PingOne**: add redirect URI `https://a2a-travel-ui.ping-devops.com/auth/callback`
   to the `travel-ui` app (console step).

## Deploy

```bash
kubectl apply -f k8s/travel-ui/deployment.yaml
kubectl apply -f k8s/travel-ui/service-ingress.yaml
kubectl -n ping-devops-cprice rollout status deploy/a2a-travel-ui
```

Verify:

```bash
curl -s https://a2a-travel-ui.ping-devops.com/ | head -c 200
curl -s https://a2a-travel-ui.ping-devops.com/config.js
```

## Auth on the planner side

The k8s planner should run with AUTH_REQUIRED=true (add to the planner
deployment env) so the agent prompt has no anonymous path. The UI sends
the planner-tenant token on every /agui call; login redirect URI is
this host + /auth/callback.
