import { useEffect, useRef, useState } from "react";

/**
 * The deployed architecture: person → planner (EKS) → GAP specialists,
 * with the two governance tiers (Google IAM at the platform edge, Ping
 * identity/delegation across the A2A boundary) and the exchange AS that
 * mints every delegation. The pattern composes: each specialist runs the
 * same move toward its own tools (own AS, own actor) — shown dashed as
 * the next tier, out of scope here.
 */
const DIAGRAM = `
flowchart LR
    USER(["Person"])

    subgraph UI["Chat UI — a2a-travel-ui (EKS, nginx)"]
        direction TB
        LOGIN["PingOne login (PKCE)<br/>planner tenant"]
        CHAT["CopilotSidebar<br/>AG-UI HttpAgent"]
        CARDS["Widget cards<br/>render_*_search / render_*_booking"]
        PANEL["Activity panel<br/>trace: the delegation story"]
    end

    subgraph PLANNER["travel-planner — a2a-travel-planner (EKS, public)"]
        direction TB
        PGATE["AUTH_REQUIRED gate<br/>person token validated<br/>(planner-tenant JWKS)"]
        PAGENT["ADK Agent<br/>RemoteA2aAgent x2 (AgentTool)<br/>+ AGUIToolset(render_*)"]
        PEX["RFC 8693 exchange<br/>subject=person actor=k8s SA<br/>aud=a2a://flights|hotels"]
        PGATE --> PAGENT
        PEX --> PAGENT
    end

    subgraph AS["TokenExchange-AS — a2a-token-as (EKS)"]
        ASBOX["P1AZ decision<br/>subject introspected (in-session)<br/>actor = k8s SA sub<br/>mints sub/act/aud/scope OBO"]
    end

    subgraph GAP["Google Agent Platform — project 3682147732 / us-west1"]
        direction TB
        GEDGE["Google IAM platform edge<br/>(WIF caller: aiplatform.user)"]
        FLIGHT["flight-agent (A2aAgent)<br/>in-agent OBO validation<br/>iss=AS aud=a2a://flights act∈allowlist"]
        HOTEL["hotel-agent (A2aAgent)<br/>same, aud=a2a://hotels"]
        GEDGE --> FLIGHT
        GEDGE --> HOTEL
    end

    subgraph PING["PingOne tenants (three independent IdPs)"]
        P1P["planner tenant<br/>person login + loyalty linkage"]
        P1F["flights tenant<br/>member records: SK-…"]
        P1H["hotels tenant<br/>member records: HB-…"]
    end

    USER --> UI
    LOGINP1["Person token<br/>(planner tenant, PKCE)"]

    UI -- "AG-UI SSE + Bearer person token" --> PGATE
    LOGINP1 -.-> UI

    PAGENT -- "1. authenticated card (WIF bearer)<br/>2. message/send" --> GEDGE
    PAGENT -- "subject + actor(k8s SA JWT)" --> ASBOX
    ASBOX -- "P1AZ policy" --> P1P
    FLIGHT -- "resolve member value<br/>from OWN records" --> P1F
    HOTEL -- "resolve member value<br/>from OWN records" --> P1H

    PAGENT -. "render_* (data via<br/>planner LLM today)" .-> CARDS
    PANEL <-. "trace SSE" .-> PLANNER

    FLIGHT -. "next tier (this demo's<br/>composition boundary):<br/>own AS → own MCP servers" .-> FUTURE[("Tier-2 tools<br/>not in scope")]

    classDef surface fill:#eff6ff,stroke:#2563eb,color:#1e3a8a;
    classDef domain fill:#f0fdf4,stroke:#047857,color:#14532d;
    classDef planner fill:#fefce8,stroke:#a16207,color:#713f12;
    classDef asx fill:#fef2f2,stroke:#b91c1c,color:#7f1d1d;
    classDef gapx fill:#eef2ff,stroke:#4338ca,color:#312e81;
    classDef pingx fill:#fdf4ff,stroke:#a21caf,color:#701a75;
    class UI surface;
    class PLANNER planner;
    class ASBOX asx;
    class GAP,FLIGHT,HOTEL,GEDGE gapx;
    class PING,P1P,P1F,P1H pingx;
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
            <strong>Two governance tiers:</strong> Google IAM at the platform
            edge (WIF) · Ping identity/delegation across the A2A boundary
          </span>
          <span className="legend-item">
            <strong>Every delegation minted</strong> at the TokenExchange-AS
            (P1AZ-gated): sub=person · act=planner's k8s identity ·
            aud=one specialist
          </span>
          <span className="legend-item muted">
            The pattern composes: each specialist would run the same move
            toward its own tools (dashed — out of scope)
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
