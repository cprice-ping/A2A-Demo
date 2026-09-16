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

/** Class-safe kind slug: CSS classes can't hold dots, so
 *  "auth.token_exchange" becomes "auth-token-exchange". */
function kindSlug(kind: string): string {
  return kind.replace(/[^a-z0-9]+/gi, "-").toLowerCase();
}

/** Kinds whose wire moment deserves the deck's attention wash. Delegation
 *  (token exchange) is the demo's identity thesis — it lands visibly. */
const KIND_ATTENTION = new Set(["auth.token_exchange"]);

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
  "mcp.setup": { icon: "🔌", label: "MCP session" },
  "agui.run": { icon: "💬", label: "Chat run" },
  "auth.user": { icon: "🪪", label: "User token" },
  "auth.token_exchange": { icon: "🔑", label: "Token exchange" },
  "auth.token_exchange_failed": { icon: "🔑", label: "Exchange failed" },
  "auth.accepted": { icon: "🛡️", label: "Auth accepted" },
  "auth.rejected": { icon: "🛡️", label: "Auth rejected" },
  "trace.complete": { icon: "✓", label: "" },
};

/** True for events that arrived from stream replay (before this viewer
 *  connected) vs live tail. The mountTime ref in ActivityPanel applies the
 *  same comparison for the history separator. */
const REPLAY_WINDOW_MS = 1500;

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

/** Every row is expandable: the detail JSON is the presenter's proof. Rows
 *  with an exchange_id additionally fetch the full request/response. */
function hasExchange(e: TraceEvent): boolean {
  return e.kind === "a2a.exchange" && !!e.detail.exchange_id;
}

/** Rows whose detail is worth rendering even without an exchange record. */
function hasDetail(e: TraceEvent): boolean {
  return Object.keys(e.detail ?? {}).length > 0;
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
  event,
}: {
  source: string;
  event: TraceEvent;
}) {
  const exchangeId = event.kind === "a2a.exchange" ? String(event.detail.exchange_id ?? "") : "";
  const [ex, setEx] = useState<A2AExchange | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!exchangeId) return;
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

  // No exchange record behind this row: show the event's own detail JSON.
  if (!exchangeId) {
    return (
      <div className="ex-block">
        <div className="ex-section">
          <div className="ex-label">detail</div>
          <pre className="ex-json">{JSON.stringify(event.detail, null, 2)}</pre>
        </div>
      </div>
    );
  }

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

  const mountTime = useRef(Date.now());
  const rows: Row[] = [
    ...flight.map((event, i) => ({ key: `f${i}-${event.ts}`, event })),
    ...hotel.map((event, i) => ({ key: `h${i}-${event.ts}`, event })),
    ...planner.map((event, i) => ({ key: `p${i}-${event.ts}`, event })),
  ]
    .sort((a, b) => a.event.ts - b.event.ts)
    .slice(-120);

  // Pre-mount (replayed) events get a visual separator at the boundary so
  // old ring-buffer history is distinguishable from this session's traffic.
  const firstLiveIdx = rows.findIndex(
    (r) => r.event.ts * 1000 >= mountTime.current - REPLAY_WINDOW_MS
  );

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
          {rows.map(({ key, event }, idx) => {
            const style =
              KIND_STYLE[event.kind] ?? { icon: "•", label: event.kind };
            const expandable = hasExchange(event) || hasDetail(event);
            const isOpen = expandedRows.has(key);
            const time = new Date(event.ts * 1000).toLocaleTimeString();
            return (
              <div key={key}>
                {idx === firstLiveIdx && firstLiveIdx > 0 && (
                  <div className="activity-separator">
                    ↑ earlier activity (from agent history) · this session ↓
                  </div>
                )}
                <div
                  className={`activity-row kind-${kindSlug(event.kind)} ${KIND_ATTENTION.has(event.kind) ? "attention" : ""} ${expandable ? "expandable" : ""}`}
                  onClick={expandable ? () => toggleRow(key) : undefined}
                  title={expandable ? "Click to show the wire detail" : undefined}
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
                    event={event}
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
