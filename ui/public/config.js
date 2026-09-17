// Runtime configuration — loaded by index.html BEFORE the app bundle.
// Local-dev defaults: compose ports, no auth (login button shows the
// "not configured" state). The k8s deployment mounts a ConfigMap at this
// path with cluster values; deploy.sh writes it from env.
window.__A2A_CONFIG__ = {
  // REST bases (no trailing slash); /agui, /a2a, /api are appended.
  flight: "http://localhost:8080",
  hotel: "http://localhost:8081",
  planner: "http://localhost:8082",
  // Planner-tenant OIDC (leave client empty to hide sign-in).
  plannerIssuer: "",
  uiClientId: "",
};
