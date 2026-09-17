import { useEffect, useState } from "react";
import { AGENT_BASE, type AgentId } from "../agents";

/** The subset of the a2a-sdk card JSON we render. */
interface AgentCard {
  name: string;
  description: string;
  version: string;
  capabilities?: { streaming?: boolean };
  supportedInterfaces?: {
    url: string;
    protocolBinding: string;
    protocolVersion: string;
  }[];
  skills: {
    id: string;
    name: string;
    description: string;
    tags?: string[];
    examples?: string[];
  }[];
  securitySchemes?: Record<
    string,
    {
      type?: string;
      oauth2SecurityScheme?: {
        flows?: Record<
          string,
          {
            authorizationUrl?: string;
            tokenUrl?: string;
            scopes?: Record<string, string>;
          }
        >;
      };
    }
  >;
  /** Spec-named requirements: [{ scheme: [scopes] }]; also tolerate the
   *  raw proto field/shape ({ schemes: { scheme: { list: [...] } } }). */
  security?: Record<string, string[] | { list: string[] }>[];
  securityRequirements?: { schemes: Record<string, string[] | { list: string[] }> }[];
}

/** Normalized requirements: [{ scheme: [scopes] }] from either wire shape. */
function securityRequirements(card: AgentCard): Record<string, string[]>[] {
  const scopes = (v: string[] | { list?: string[] } | undefined): string[] =>
    Array.isArray(v) ? v : (v?.list ?? []);
  if (card.security)
    return card.security.map((req) =>
      Object.fromEntries(Object.entries(req ?? {}).map(([s, v]) => [s, scopes(v)]))
    );
  const proto = (card as { securityRequirements?: { schemes?: Record<string, string[] | { list: string[] }> }[] })
    .securityRequirements;
  return (proto ?? []).map((req) =>
    Object.fromEntries(Object.entries(req.schemes ?? {}).map(([s, v]) => [s, scopes(v)]))
  );
}

export function useAgentCard(
  agentId: AgentId,
  opts?: { skip?: boolean },
) {
  const [card, setCard] = useState<AgentCard | null>(null);
  // The verbatim wire document (for the raw-JSON view — re-serializing the
  // parsed subset would lose fields we don't render).
  const [rawJson, setRawJson] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (opts?.skip) return;
    let cancelled = false;
    fetch(`${AGENT_BASE[agentId]}/a2a/.well-known/agent-card.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.text();
      })
      .then((text) => {
        if (cancelled) return;
        setRawJson(text);
        try {
          setCard(JSON.parse(text));
        } catch {
          // A non-JSON response (HTML 404 page, SPA fallback, gateway error
          // page) is an unreachability signal, not a parse accident.
          throw new Error("response is not an agent card (HTML?) — is the URL an A2A endpoint?");
        }
      })
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [agentId, opts?.skip]);

  return { card, rawJson, error };
}

export default function AgentCardView({ agentId }: { agentId: AgentId }) {
  const { card, rawJson, error } = useAgentCard(agentId);
  const [showRaw, setShowRaw] = useState(false);

  if (error)
    return (
      <div className="agent-card error">
        Card unavailable: {error} <span className="muted">(is the agent up?)</span>
      </div>
    );
  if (!card) return <div className="agent-card muted">Fetching card…</div>;

  const iface = card.supportedInterfaces?.[0];

  if (showRaw) {
    return (
      <div className="agent-card">
        <div className="agent-card-head">
          <span className="agent-card-name">{card.name}</span>
          <span className="agent-card-version">v{card.version}</span>
          <button
            className="raw-json-toggle"
            onClick={() => setShowRaw(false)}
            title="Back to the rendered card"
          >
            ← rendered
          </button>
        </div>
        <pre className="agent-card-raw">
          {rawJson ? JSON.stringify(JSON.parse(rawJson), null, 2) : "…"}
        </pre>
      </div>
    );
  }

  return (
    <div className="agent-card">
      <div className="agent-card-head">
        <span className="agent-card-name">{card.name}</span>
        <span className="agent-card-version">v{card.version}</span>
        {card.capabilities?.streaming && (
          <span className="chip" title="Supports streaming (SSE)">
            streaming
          </span>
        )}
        <button className="raw-json-toggle" onClick={() => setShowRaw(true)} title="Show the raw card JSON">
          {"{ } raw JSON"}
        </button>
      </div>
      <div className="agent-card-desc">{card.description}</div>

      <div className="agent-card-endpoint">
        <span className="muted">A2A endpoint</span>
        <code>
          {ifaceProtocol(iface)} {iface?.url ?? "?"}
        </code>
      </div>

      <CardSecuritySection card={card} />

      <div className="agent-card-skills">
        {card.skills.map((s) => (
          <div className="skill" key={s.id}>
            <div className="skill-head">
              <strong>{s.name}</strong>
              {s.tags?.map((t) => (
                <span className="chip" key={t}>
                  {t}
                </span>
              ))}
            </div>
            <div className="skill-desc">{s.description}</div>
            {s.examples && s.examples.length > 0 && (
              <ul className="skill-examples">
                {s.examples.map((ex) => (
                  <li key={ex}>
                    <code>{ex}</code>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>

      <div className="muted card-note">
        ← this is the document the planner reads at discovery; skills become
        its delegation targets
      </div>
    </div>
  );
}

function ifaceProtocol(iface?: { protocolBinding?: string; protocolVersion?: string }) {
  if (!iface) return "";
  return `${iface.protocolBinding ?? "?"}/${iface.protocolVersion ?? "?"}`;
}

/** The auth contract, exactly as the wire carries it: which schemes this
 *  agent accepts (each with its flow + token endpoint) and which scopes
 *  /a2a demands. This is what the planner reads to learn HOW to talk
 *  here — the delegated-caller scheme and the direct person login side
 *  by side. */
function CardSecuritySection({ card }: { card: AgentCard }) {
  const requirements = securityRequirements(card);
  const schemes = card.securitySchemes ?? {};
  const entries = Object.entries(schemes);
  // No contract on the wire → say so once and render nothing; an empty
  // "Security" box would read as broken rendering, not as "no auth".
  if (entries.length === 0 && requirements.length === 0) return null;

  return (
    <div className="agent-card-security">
      <div className="agent-card-security-title">Security</div>
      {requirements.length > 0 && (
        <div className="agent-card-security-req">
          <span className="muted">requires</span>
          {requirements.map((req, i) => (
            <span className="agent-card-security-req-item" key={i}>
              {Object.entries(req).map(([scheme, scopes]) => (
                <span key={scheme}>
                  <code className="scheme-name">{scheme}</code>
                  {scopes.length > 0 && (
                    <span className="scheme-scopes">
                      {scopes.map((s) => (
                        <span className="chip" key={s}>
                          {s}
                        </span>
                      ))}
                    </span>
                  )}
                </span>
              ))}
            </span>
          ))}
        </div>
      )}
      <div className="agent-card-security-schemes">
        {entries.map(([name, scheme]) => {
          const flows = scheme.oauth2SecurityScheme?.flows ?? {};
          return (
            <div className="agent-card-security-scheme" key={name}>
              <code className="scheme-name">{name}</code>
              <span className="muted">
                {scheme.type ?? "oauth2"} ·{" "}
                {Object.keys(flows).join(" / ")}
              </span>
              {Object.entries(flows).map(([flowName, flow]) => (
                <div className="agent-card-security-flow" key={flowName}>
                  {flow.authorizationUrl && (
                    <div>
                      <span className="muted">authorize</span>{" "}
                      <code>{flow.authorizationUrl}</code>
                    </div>
                  )}
                  {flow.tokenUrl && (
                    <div>
                      <span className="muted">token</span> <code>{flow.tokenUrl}</code>
                    </div>
                  )}
                  {flow.scopes && Object.keys(flow.scopes).length > 0 && (
                    <div className="scheme-scopes">
                      {Object.keys(flow.scopes).map((s) => (
                        <span className="chip" key={s}>
                          {s}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
