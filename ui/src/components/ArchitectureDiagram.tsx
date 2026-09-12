import { useEffect, useRef, useState } from "react";

/**
 * Architecture with explicit trust boundaries:
 * - Each agent stack is a SEALED unit: the ADK agent, its MCP server and its
 *   mock data API live inside one container boundary. MCP speaks only over
 *   the container's own loopback — nothing outside the stack can reach it,
 *   and the MCP servers expose no auth surface by design (unreachable).
 * - A2A is the ONLY sanctioned bridge between stacks (planner delegates).
 * - Human AuthN (future) gates the front door: the chat UI's /agui calls.
 */
const DIAGRAM = `
flowchart LR
    USER(["User"])

    subgraph UI["Chat UI - port 5173, Vite + CopilotKit"]
        direction TB
        TABS["Agent tabs: flight / hotel / planner"]
        CHAT["CopilotSidebar<br/>AG-UI HttpAgent"]
        CARDS["Widget cards<br/>render_*_search / render_*_booking"]
        PANEL["Activity panel<br/>trace SSE x3"]
    end

    subgraph PLANNER["travel-planner :8082"]
        direction TB
        PAGUI["/agui - AG-UI SSE"]
        PAGENT["ADK Agent<br/>tools: AgentTool(RemoteA2aAgent) x2<br/>+ AGUIToolset(render_*)"]
        PA2A["/a2a - card + JSON-RPC"]
        PAGUI --> PAGENT
    end

    subgraph FLIGHT["flight-agent :8080 - Cloud Run, Vertex, no API key"]
        direction TB
        FAGUI["/agui - root_agent + AGUIToolset"]
        FA2A["/a2a - a2a_agent<br/>(replies raw JSON)"]
        FMCP["/mcp - 5 flight tools<br/>sealed: loopback now,<br/>separate deploy + authz later"]
        FAPI["/api - mock data"]
        FSTORE[("BK- store")]
        FMCP --> FAPI
        FAPI --> FSTORE
    end

    subgraph HOTEL["hotel-agent :8081 - Kubernetes kind, GOOGLE_API_KEY secret"]
        direction TB
        HAGUI["/agui - root_agent + AGUIToolset"]
        HA2A["/a2a - a2a_agent<br/>(replies raw JSON)"]
        HMCP["/mcp - 5 hotel tools<br/>sealed: loopback now,<br/>separate deploy + authz later"]
        HAPI["/api - mock data"]
        HSTORE[("HB- store")]
        HMCP --> HAPI
        HAPI --> HSTORE
    end

    USER --> TABS
    TABS --> CHAT

    CHAT -- "AG-UI SSE" --> PAGUI
    CHAT -.-> FAGUI
    CHAT -.-> HAGUI

    PAGENT == "1. GET card<br/>2. message/stream (one leg per call)" ==> FA2A
    PAGENT == "1. GET card<br/>2. message/stream (one leg per call)" ==> HA2A

    FA2A -- "MCP (self-connection)" --> FMCP
    HA2A -- "MCP (self-connection)" --> HMCP
    FAGUI -.-> FMCP
    HAGUI -.-> HMCP

    PAGENT -. "render_flight_search<br/>(verbatim data)" .-> CARDS
    PAGENT -. "render_hotel_search<br/>(verbatim data)" .-> CARDS

    PANEL <-. "trace" .-> PLANNER
    PANEL <-.-> FLIGHT
    PANEL <-.-> HOTEL

    classDef surface fill:#eff6ff,stroke:#2563eb,color:#1e3a8a;
    classDef domain fill:#f0fdf4,stroke:#047857,color:#14532d;
    classDef planner fill:#fefce8,stroke:#a16207,color:#713f12;
    classDef storec fill:#f5f5f4,stroke:#78716c,color:#44403c;
    class FAGUI,FA2A,FMCP,FAPI surface;
    class HAGUI,HA2A,HMCP,HAPI surface;
    class PAGENT,PA2A,PAGUI planner;
    class FSTORE,HSTORE storec;
`.trim();

export default function ArchitectureDiagram({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "loose",
          theme: "base",
          themeVariables: {
            fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
            fontSize: "13px",
          },
          flowchart: { curve: "basis", htmlLabels: true },
        });
        const { svg } = await mermaid.render(`arch-${Date.now()}`, DIAGRAM);
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
          const svgEl = ref.current.querySelector("svg");
          if (svgEl) {
            svgEl.style.maxWidth = "100%";
            svgEl.style.height = "auto";
          }
        }
      } catch (e) {
        if (!cancelled) setError(String(e instanceof Error ? e.message : e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Architecture</h2>
          <button className="modal-close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="arch-legend">
          <span className="legend-item">
            <strong>Sealed stacks:</strong> agent + MCP + data inside one
            boundary; MCP is loopback-only
          </span>
          <span className="legend-item">
            <strong>A2A = only bridge</strong> between stacks (planner
            delegation)
          </span>
          <span className="legend-item muted">
            Future: Human AuthN at the UI's /agui front door
          </span>
        </div>
        {error ? (
          <p className="widget-empty">Failed to render diagram: {error}</p>
        ) : (
          <div className="modal-body" ref={ref} />
        )}
      </div>
    </div>
  );
}
