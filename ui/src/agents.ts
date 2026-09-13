import { HttpAgent } from "@ag-ui/client";

/** Direct AG-UI connection per agent — no CopilotKit runtime needed. */
export type AgentId = "flight" | "hotel" | "planner";

/** Base URLs of the three agents (REST surfaces: card, trace). */
export const AGENT_BASE: Record<AgentId, string> = {
  flight: "http://localhost:8080",
  hotel: "http://localhost:8081",
  planner: "http://localhost:8082",
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
      url: url("flightAgent", "http://localhost:8080/agui"),
    }),
    hotel: new HttpAgent({
      url: url("hotelAgent", "http://localhost:8081/agui"),
    }),
    planner: new HttpAgent({
      url: url("plannerAgent", "http://localhost:8082/agui"),
      // The human's planner-tenant PingOne token travels on every /agui
      // call; the planner validates it and exchanges it at specialists.
      ...(authToken ? { headers: { Authorization: `Bearer ${authToken}` } } : {}),
    }),
  };
}
