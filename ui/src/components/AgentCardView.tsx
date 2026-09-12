import { useEffect, useState } from "react";
import { AGENT_BASE, type AgentId } from "../agents";

/** The subset of the a2a-sdk 1.x card JSON we render. */
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
}

export function useAgentCard(agentId: AgentId) {
  const [card, setCard] = useState<AgentCard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${AGENT_BASE[agentId]}/a2a/.well-known/agent-card.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((c) => !cancelled && setCard(c))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  return { card, error };
}

export default function AgentCardView({ agentId }: { agentId: AgentId }) {
  const { card, error } = useAgentCard(agentId);

  if (error)
    return (
      <div className="agent-card error">
        Card unavailable: {error} <span className="muted">(is the agent up?)</span>
      </div>
    );
  if (!card) return <div className="agent-card muted">Fetching card…</div>;

  const iface = card.supportedInterfaces?.[0];

  return (
    <div className="agent-card">
      <div className="agent-card-head">
        <span className="agent-card-name">{card.name}</span>
        <span className="muted">v{card.version}</span>
        {card.capabilities?.streaming && (
          <span className="chip" title="Supports streaming (SSE)">
            streaming
          </span>
        )}
      </div>
      <div className="agent-card-desc">{card.description}</div>

      <div className="agent-card-endpoint">
        <span className="muted">A2A endpoint</span>
        <code>
          {ifaceProtocol(iface)} {iface?.url ?? "?"}
        </code>
      </div>

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
