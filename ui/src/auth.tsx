import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

/**
 * OIDC Authorization Code + PKCE (S256) against the planner PingOne tenant.
 * Public client (no secret); tokens live in sessionStorage for this tab only.
 *
 * Vite env (ui/.env.local, not committed):
 *   VITE_PLANNER_ISSUER=https://auth.pingone.com/<plannerEnvId>/as
 *   VITE_UI_CLIENT_ID=<travel-ui clientId>
 */

const ISSUER = import.meta.env.VITE_PLANNER_ISSUER as string | undefined;
const CLIENT_ID = import.meta.env.VITE_UI_CLIENT_ID as string | undefined;
const REDIRECT_URI = `${window.location.origin}/auth/callback`;
const SCOPE = "openid profile email";

export const authConfigured = Boolean(ISSUER && CLIENT_ID);

interface Claims {
  sub: string;
  email?: string;
  name?: string;
  [key: string]: unknown;
}

interface AuthState {
  token: string | null;
  claims: Claims | null;
  login: () => void;
  logout: () => void;
  handleCallback: () => Promise<void>;
  configuring: boolean;
}

const AuthContext = createContext<AuthState>({
  token: null,
  claims: null,
  login: () => {},
  logout: () => {},
  handleCallback: async () => {},
  configuring: !authConfigured,
});

// ---- PKCE helpers ----

function base64url(buf: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function sha256(input: string): Promise<ArrayBuffer> {
  return crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
}

function randomString(len = 64): string {
  const bytes = new Uint8Array(len);
  crypto.getRandomValues(bytes);
  return base64url(bytes.buffer).slice(0, len);
}

const TOKEN_KEY = "a2a_demo.tokens";
const VERIFIER_KEY = "a2a_demo.verifier";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [claims, setClaims] = useState<Claims | null>(null);

  useEffect(() => {
    if (!authConfigured) return;
    try {
      const raw = sessionStorage.getItem(TOKEN_KEY);
      if (raw) {
        const { access_token } = JSON.parse(raw);
        setToken(access_token);
        setClaims(decodeClaims(access_token));
      }
    } catch {
      /* ignore corrupt storage */
    }
  }, []);

  const login = useCallback(() => {
    if (!ISSUER || !CLIENT_ID) return;
    const verifier = randomString(64);
    sessionStorage.setItem(VERIFIER_KEY, verifier);
    sha256(verifier).then((digest) => {
      const challenge = base64url(digest);
      const params = new URLSearchParams({
        response_type: "code",
        client_id: CLIENT_ID,
        redirect_uri: REDIRECT_URI,
        scope: SCOPE,
        state: randomString(16),
        nonce: randomString(16),
        code_challenge: challenge,
        code_challenge_method: "S256",
        prompt: "login",
      });
      window.location.href = `${ISSUER}/authorize?${params}`;
    });
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setClaims(null);
  }, []);

  const handleCallback = useCallback(async () => {
    if (!ISSUER || !CLIENT_ID) return;
    const url = new URL(window.location.href);
    const code = url.searchParams.get("code");
    const verifier = sessionStorage.getItem(VERIFIER_KEY);
    if (!code || !verifier) return;
    const resp = await fetch(`${ISSUER}/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        client_id: CLIENT_ID,
        code,
        redirect_uri: REDIRECT_URI,
        code_verifier: verifier,
      }),
    });
    if (!resp.ok) {
      throw new Error(`token exchange failed: ${resp.status}`);
    }
    const tokens = await resp.json();
    sessionStorage.setItem(TOKEN_KEY, JSON.stringify(tokens));
    sessionStorage.removeItem(VERIFIER_KEY);
    setToken(tokens.access_token);
    setClaims(decodeClaims(tokens.access_token));
    // Clean the URL (strip code/state)
    window.history.replaceState({}, "", window.location.origin);
  }, []);

  return (
    <AuthContext.Provider
      value={{ token, claims, login, logout, handleCallback, configuring: !authConfigured }}
    >
      {children}
    </AuthContext.Provider>
  );
}

function decodeClaims(jwt: string): Claims | null {
  try {
    const payload = jwt.split(".")[1];
    return JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}
