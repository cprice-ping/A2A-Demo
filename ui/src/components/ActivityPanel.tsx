import { useEffect, useRef, useState } from "react";

export interface TraceEvent {
  ts: number;
  source: string;
  kind: string;
  detail: Record<string, unknown>;
}

const AGENT_URLS: Record<string, string> = {
  "flight-agent": "http://localhost:8080",
  "hotel-agent": "http://localhost:8081",
  "travel-planner": "http://localhost:8082",
};

const SOURCE_ICON: Record<string, string> = {
  "flight-agent": "✈️",
  "hotel-agent": "🏨",
  "travel-planner": "🧭",
};

const KIND_STYLE: Record<string, { icon: string; label: string }> = {
  "a2a.request": { icon: "🤝", label: "A2A received" },
  "a2a.outbound": { icon: "📡", label: "A2A sent" },
  "a2a.card_fetch": { icon: "📇", label: "Card fetched" },
  "mcp.call": { icon: "🔧", label: "MCP tool call" },
  "mcp.rpc": { icon: "🔧", label: "MCP rpc" },
  "agui.run": { icon: "💬", label: "Chat run" },
  "trace.complete": { icon: "✓", label: "" },
};

interface Row {
  key: string;
  event: TraceEvent;
}

function describe(e: TraceEvent): string {
  const d = e.detail;
  switch (e.kind) {
    case "a2a.request":
      return `${d.rpc ?? "message/send"}: "${d.text ?? ""}"`;
    case "a2a.outbound":
      return `→ ${d.target}: ${d.rpc ?? "message/send"} "${d.text ?? ""}"`;
    case "a2a.card_fetch":
      return String(d.url ?? "");
    case "mcp.call":
      return `${d.tool}(${(d.args as string[])?.join(", ") ?? ""})`;
    case "mcp.rpc":
      return String(d.method ?? "");
    case "agui.run":
      return `"${d.message ?? ""}"`;
    case "trace.complete": {
      const s = d.status ?? "?";
      const ms = d.elapsed_ms ?? "?";
      return `${d.path} → ${s} · ${ms}ms`;
    }
    default:
      return JSON.stringify(d).slice(0, 120);
  }
}

function useAgentTrace(source: string, enabled: boolean): TraceEvent[] {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  useEffect(() => {
    if (!enabled) return;
    const base = AGENT_URLS[source];
    let es: EventSource | null = null;
    let closed = false;
    const connect = () => {
      es = new EventSource(`${base}/api/trace/stream`);
      es.onmessage = (msg) => {
        try {
          const event = JSON.parse(msg.data) as TraceEvent;
          setEvents((prev) => [...prev.slice(-200), event]);
        } catch {
          /* ignore malformed frames */
        }
      };
      es.onerror = () => {
        if (!closed) {
          es?.close();
          setTimeout(() => {
            if (!closed) connect();
          }, 2000);
        }
      };
    };
    connect();
    return () => {
      closed = true;
      es?.close();
    };
  }, [source, enabled]);
  return events;
}

export default function ActivityPanel({
  enabled,
  expanded,
  onToggleExpanded,
}: {
  enabled: boolean;
  expanded: boolean;
  onToggleExpanded: () => void;
}) {
  const flight = useAgentTrace("flight-agent", enabled);
  const hotel = useAgentTrace("hotel-agent", enabled);
  const planner = useAgentTrace("travel-planner", enabled);

  const [open, setOpen] = useState(true);
  const feedRef = useRef<HTMLDivElement>(null);

  const rows: Row[] = [
    ...flight.map((event, i) => ({ key: `f${i}-${event.ts}`, event })),
    ...hotel.map((event, i) => ({ key: `h${i}-${event.ts}`, event })),
    ...planner.map((event, i) => ({ key: `p${i}-${event.ts}`, event })),
  ]
    .sort((a, b) => a.event.ts - b.event.ts)
    .slice(-120);

  useEffect(() => {
    if (open && feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [rows.length, open]);

  const connectedCount = [flight.length, hotel.length, planner.length].filter(
    (n) => n > 0
  ).length;

  if (!enabled) return null;

  return (
    <div className={`activity-panel ${expanded ? "expanded" : ""}`}>
      <div className="activity-header">
        <button className="activity-toggle" onClick={() => setOpen(!open)}>
          <span>Protocol activity</span>
          <span className="muted">
            {connectedCount}/3 streams · {rows.length} events {open ? "▾" : "▸"}
          </span>
        </button>
        <button
          className="activity-expand"
          onClick={onToggleExpanded}
          title={expanded ? "Shrink panel" : "Expand panel"}
        >
          {expanded ? "⤡" : "⤢"}
        </button>
      </div>
      {open && (
        <div className="activity-feed" ref={feedRef}>
          {rows.length === 0 && (
            <div className="widget-empty">
              No activity yet — send the agents a message.
            </div>
          )}
          {rows.map(({ key, event }) => {
            const style =
              KIND_STYLE[event.kind] ?? { icon: "•", label: event.kind };
            const time = new Date(event.ts * 1000).toLocaleTimeString();
            return (
              <div className={`activity-row kind-${event.kind}`} key={key}>
                <span className="activity-time">{time}</span>
                <span className="activity-icon">
                  {SOURCE_ICON[event.source] ?? "•"}
                </span>
                <span className="activity-kind">
                  {style.icon} {style.label || event.kind}
                </span>
                <span className="activity-detail">{describe(event)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
