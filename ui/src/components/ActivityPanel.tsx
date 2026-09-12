import { useEffect, useRef, useState } from "react";

export interface TraceEvent {
  ts: number;
  source: string;
  kind: string;
  detail: Record<string, unknown>;
}

interface A2AExchange {
  id: string;
  ts: number;
  source: string;
  direction: string;
  peer?: string | null;
  path: string;
  request: unknown;
  response: unknown;
  status: number | null;
  elapsed_ms: number | null;
  sse: boolean;
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
  "a2a.exchange": { icon: "🤝", label: "A2A exchange" },
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
    case "a2a.exchange":
      return `${d.rpc ?? "message/send"}: "${d.text ?? ""}"${d.elapsed_ms ? ` · ${d.elapsed_ms}ms` : ""}`;
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

/** Expandable: rows with an exchange_id fetch the full request/response. */
function hasExchange(e: TraceEvent): boolean {
  return e.kind === "a2a.exchange" && !!e.detail.exchange_id;
}

function summarizeResult(frame: unknown): string {
  const f = frame as { result?: Record<string, unknown> };
  const result = f?.result;
  if (!result) return JSON.stringify(frame).slice(0, 100);
  if ("message" in result) {
    const parts = (result.message as { parts?: { text?: string }[] }).parts ?? [];
    return `message: ${parts.map((p) => p.text ?? "").join(" ").slice(0, 160)}`;
  }
  if ("statusUpdate" in result) {
    const su = result.statusUpdate as { status?: { state?: string } };
    return `status: ${su?.status?.state ?? "?"}`;
  }
  if ("artifactUpdate" in result) {
    const au = result.artifactUpdate as {
      artifact?: { name?: string; parts?: { text?: string }[] };
    };
    const text = (au?.artifact?.parts ?? []).map((p) => p.text ?? "").join(" ");
    return `artifact${au?.artifact?.name ? ` "${au.artifact.name}"` : ""}: ${text.slice(0, 160)}`;
  }
  if ("task" in result) {
    const t = result.task as { status?: { state?: string } };
    return `task: ${t?.status?.state ?? "?"}`;
  }
  return JSON.stringify(result).slice(0, 100);
}

function ExchangeView({
  source,
  exchangeId,
}: {
  source: string;
  exchangeId: string;
}) {
  const [ex, setEx] = useState<A2AExchange | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`${AGENT_URLS[source]}/api/trace/a2a`)
      .then((r) => r.json())
      .then((data: { exchanges: A2AExchange[] }) => {
        if (!cancelled) {
          const found = data.exchanges.find((e) => e.id === exchangeId) ?? null;
          setEx(found);
          setError(!found);
        }
      })
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
    };
  }, [source, exchangeId]);

  if (error) return <div className="ex-block muted">exchange expired</div>;
  if (!ex) return <div className="ex-block muted">loading exchange…</div>;

  const frames = Array.isArray(ex.response) ? ex.response : null;

  return (
    <div className="ex-block">
      <div className="ex-section">
        <div className="ex-label">request {ex.path}</div>
        <pre className="ex-json">{JSON.stringify(ex.request, null, 2)}</pre>
      </div>
      <div className="ex-section">
        <div className="ex-label">
          response {ex.sse ? `(${frames?.length ?? "?"} SSE frames)` : ""} ·{" "}
          {ex.status} {ex.elapsed_ms != null ? `· ${ex.elapsed_ms}ms` : ""}
        </div>
        {frames ? (
          <div className="ex-frames">
            {frames.map((frame, i) => (
              <div className="ex-frame" key={i}>
                <span className="ex-frame-idx">{i + 1}</span>
                <span className="ex-frame-text">{summarizeResult(frame)}</span>
              </div>
            ))}
          </div>
        ) : (
          <pre className="ex-json">{JSON.stringify(ex.response, null, 2)}</pre>
        )}
      </div>
    </div>
  );
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
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const feedRef = useRef<HTMLDivElement>(null);

  const rows: Row[] = [
    ...flight.map((event, i) => ({ key: `f${i}-${event.ts}`, event })),
    ...hotel.map((event, i) => ({ key: `h${i}-${event.ts}`, event })),
    ...planner.map((event, i) => ({ key: `p${i}-${event.ts}`, event })),
  ]
    .sort((a, b) => a.event.ts - b.event.ts)
    .slice(-120);

  useEffect(() => {
    if (open && feedRef.current && !expandedRows.size) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [rows.length, open, expandedRows.size]);

  const connectedCount = [flight, hotel, planner].filter((a) => a.length > 0)
    .length;

  if (!enabled) return null;

  const toggleRow = (key: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

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
            const expandable = hasExchange(event);
            const isOpen = expandedRows.has(key);
            const time = new Date(event.ts * 1000).toLocaleTimeString();
            return (
              <div key={key}>
                <div
                  className={`activity-row kind-${event.kind} ${expandable ? "expandable" : ""}`}
                  onClick={expandable ? () => toggleRow(key) : undefined}
                  title={expandable ? "Click to show full request/response" : undefined}
                >
                  <span className="activity-time">{time}</span>
                  <span className="activity-icon">
                    {SOURCE_ICON[event.source] ?? "•"}
                  </span>
                  <span className="activity-kind">
                    {expandable && (
                      <span className="activity-chevron">
                        {isOpen ? "▾" : "▸"}
                      </span>
                    )}
                    {style.icon} {style.label || event.kind}
                  </span>
                  <span className="activity-detail">{describe(event)}</span>
                </div>
                {expandable && isOpen && (
                  <ExchangeView
                    source={event.source}
                    exchangeId={String(event.detail.exchange_id)}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
