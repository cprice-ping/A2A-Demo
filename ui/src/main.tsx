import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { AuthProvider, useAuth } from "./auth";
import "./index.css";

/** /auth/callback — OIDC redirect landing page; completes the PKCE flow. */
function AuthCallback() {
  const { handleCallback } = useAuth();
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    handleCallback()
      .then(() => {
        window.location.replace("/");
      })
      .catch((e) => setError(String(e)));
  }, [handleCallback]);
  return (
    <div style={{ padding: 40, fontFamily: "sans-serif" }}>
      {error ? `Login failed: ${error}` : "Signing in…"}
    </div>
  );
}

const isCallback = window.location.pathname === "/auth/callback";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthProvider>
      {isCallback ? <AuthCallback /> : <App />}
    </AuthProvider>
  </React.StrictMode>
);
