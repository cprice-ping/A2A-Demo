import { useEffect, useRef, useState } from "react";

const DIAGRAM = `
flowchart TB
    subgraph UI["🖥️ Chat UI — ui/ :5173 (Vite + CopilotKit)"]
        TABS["Agent tabs<br/>flight · hotel · planner"]
        CHAT["CopilotSidebar chat<br/>AG-UI HttpAgent → /agui"]
        CARDS["Widget cards<br/>render_*_search / render_*_booking<br/>(frontend tools)"]
        PANEL["Protocol activity panel<br/>SSE ← /api/trace/stream ×3"]
        TABS --> CHAT
        CHAT -. frontend tool calls .-> CARDS
    end

    subgraph FP["🧭 travel-planner :8082 — Cloud Run/compose"]
        direction TB
        PAGENT["ADK Agent<br/>AgentTool(RemoteA2aAgent) ×2<br/>+ AGUIToolset(render_*)"]
        PA2A["/a2a — A2A JSON-RPC + card"]
        PAGUI["/agui — AG-UI SSE"]
        PTRACE["/api/trace[/stream]"]
        PAGENT --> PA2A
        PAGENT --> PAGUI
    end

    subgraph FA["✈️ flight-agent :8080 — Cloud Run (Vertex AI · SA auth · no API key)"]
        direction TB
        FAGUI["/agui — AG-UI SSE<br/>root_agent + AGUIToolset"]
        FA2A["/a2a — A2A JSON-RPC + card<br/>a2a_agent (raw-JSON replies)"]
        FMCP["/mcp — fastmcp<br/>search_flights · book_flight<br/>get_flight · get_booking · list_airports"]
        FAPI["/api — mock REST<br/>deterministic schedule synthesis"]
        FSTORE[("booking store<br/>BK-… in-memory")]
        FAPI --> FSTORE
    end

    subgraph HA["🏨 hotel-agent :8081 — Kubernetes (kind · GOOGLE_API_KEY secret)"]
        direction TB
        HAGUI["/agui — AG-UI SSE<br/>root_agent + AGUIToolset"]
        HA2A["/a2a — A2A JSON-RPC + card<br/>a2a_agent (raw-JSON replies)"]
        HMCP["/mcp — fastmcp<br/>search_hotels · book_hotel<br/>get_hotel · get_booking · list_cities"]
        HAPI["/api — mock REST<br/>nights / total enrichment"]
        HSTORE[("booking store<br/>HB-… in-memory")]
        HAPI --> HSTORE
    end

    CHAT -- "AG-UI SSE" --> PAGUI
    CHAT -- "AG-UI SSE" --> FAGUI
    CHAT -- "AG-UI SSE" --> HAGUI
    PANEL -- "trace SSE" --> PTRACE
    PANEL -- "trace SSE" --> FTRACE["/api/trace"]
    PANEL -- "trace SSE" --> HTRACE["/api/trace"]

    PAGENT == "1️⃣ fetch card<br/>2️⃣ delegate one leg<br/>(A2A JSON-RPC)" ==> FA2A
    PAGENT == "1️⃣ fetch card<br/>2️⃣ delegate one leg<br/>(A2A JSON-RPC)" ==> HA2A

    PAGENT -. "render_* with<br/>specialist data" .-> CARDS

    FAGUI -- "MCP streamable-HTTP<br/>(self-connection)" --> FMCP
    FA2A -- "MCP" --> FMCP
    FMCP --> FAPI
    HAGUI -- "MCP streamable-HTTP<br/>(self-connection)" --> HMCP
    HA2A -- "MCP" --> HMCP
    HMCP --> HAPI

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
        {error ? (
          <p className="widget-empty">Failed to render diagram: {error}</p>
        ) : (
          <div className="modal-body" ref={ref} />
        )}
      </div>
    </div>
  );
}
