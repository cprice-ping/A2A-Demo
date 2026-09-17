import { HttpAgent } from "@ag-ui/client";

/** Direct AG-UI connection per agent — no CopilotKit runtime needed. */
export type AgentId = "flight" | "hotel" | "planner";

/**
 * Runtime config: ui/public/config.js (ConfigMap-mounted in k8s) sets
 * window.__A2A_CONFIG__ BEFORE the bundle loads; agents.ts reads it here
 * once. Absent -> local-dev defaults (compose ports). This keeps agent
 * URLs and auth config deploy-time settings, not build-time ones.
 */
interface A2AConfig {
  planner?: string;
  flight?: string;
  hotel?: string;
  plannerIssuer?: string;
  uiClientId?: string;
  /** "gap": specialists are GAP-hosted — agent-only (no browser surface). */
  deployment?: "local" | "gap";
}

/** Are the specialists GAP-hosted (agent-only from the browser)? */
export function specialistMode(): "local" | "gap" {
  return cfg().deployment ?? "local";
}

function cfg(): A2AConfig {
  const w = window as unknown as { __A2A_CONFIG__?: A2AConfig };
  return w.__A2A_CONFIG__ ?? {};
}

/** Base URL of the planner (REST surfaces: card, trace). */
export function plannerBase(): string {
  return (cfg().planner ?? "http://localhost:8082").replace(/\/$/, "");
}

/** Base URLs of the three agents (REST surfaces: card, trace). */
export const AGENT_BASE: Record<AgentId, string> = {
  flight: cfg().flight ?? "http://localhost:8080",
  hotel: cfg().hotel ?? "http://localhost:8081",
  planner: plannerBase(),
};

export const AGENT_META: Record<AgentId, { label: string; blurb: string }> = {
  flight: {
    label: "✈️ Flight Agent",
    blurb: "Search & book flights — Cloud Run target",
  },
  hotel: {
    label: "🏨 Hotel Agent",
    blurb: "Search & book hotels — Kubernetes target",
  },
  planner: {
    label: "🧭 Travel Planner",
    blurb: "Delegates to both agents over A2A",
  },
};

function url(envVar: string, fallback: string): string {
  const w = window as unknown as Record<string, unknown>;
  // Allow overriding via query param (?flightAgent=http://host:port/agui) for demos
  const params = new URLSearchParams(window.location.search);
  const q = params.get(envVar);
  if (q) return q;
  const injected = w[envVar];
  if (typeof injected === "string") return injected;
  return fallback;
}

export function makeAgents(authToken?: string): Record<AgentId, HttpAgent> {
  return {
    flight: new HttpAgent({
      url: url("flightAgent", `${AGENT_BASE.flight}/agui`),
    }),
    hotel: new HttpAgent({
      url: url("hotelAgent", `${AGENT_BASE.hotel}/agui`),
    }),
    planner: new HttpAgent({
      url: url("plannerAgent", `${AGENT_BASE.planner}/agui`),
      // The human's planner-tenant PingOne token travels on every /agui
      // call; the planner validates it and exchanges it at specialists.
      ...(authToken ? { headers: { Authorization: `Bearer ${authToken}` } } : {}),
    }),
  };
}
