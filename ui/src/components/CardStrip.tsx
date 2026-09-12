import { AGENT_META, type AgentId } from "../agents";
import AgentCardView, { useAgentCard } from "./AgentCardView";

/** One compact card; click opens the full card detail. */
function MiniCard({
  agentId,
  selected,
  onSelect,
}: {
  agentId: AgentId;
  selected: boolean;
  onSelect: (id: AgentId) => void;
}) {
  const { card, error } = useAgentCard(agentId);
  const meta = AGENT_META[agentId];

  return (
    <button
      className={`mini-card ${selected ? "selected" : ""} ${error ? "offline" : ""}`}
      onClick={() => onSelect(agentId)}
      title={`Show full card — ${meta.blurb}`}
    >
      <div className="mini-card-head">
        <span className="mini-card-label">{meta.label}</span>
        <span className={`mini-card-status ${error ? "down" : "up"}`}>
          {error ? "offline" : card ? "live" : "…"}
        </span>
      </div>
      {card && (
        <>
          <div className="mini-card-desc">{card.description}</div>
          <div className="mini-card-skills">
            {card.skills.map((s) => (
              <span className="chip" key={s.id}>
                {s.name}
              </span>
            ))}
          </div>
          <div className="mini-card-url muted">{card.supportedInterfaces?.[0]?.url}</div>
        </>
      )}
      {error && <div className="mini-card-desc muted">card unavailable</div>}
    </button>
  );
}

/** Detail modal for one card (shares modal styling with Architecture). */
export function AgentCardModal({
  agentId,
  onClose,
}: {
  agentId: AgentId;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>🪪 Agent Card — {AGENT_META[agentId].label}</h2>
          <button className="modal-close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal-body card-modal-body">
          <AgentCardView agentId={agentId} />
        </div>
      </div>
    </div>
  );
}

export default function CardStrip({
  selected,
  onSelect,
  onOpenCard,
}: {
  selected: AgentId;
  onSelect: (id: AgentId) => void;
  onOpenCard: (id: AgentId) => void;
}) {
  return (
    <div className="card-strip">
      <div className="card-strip-header">
        <span>A2A Agent Cards</span>
        <span className="muted">live from /a2a/.well-known — click for full card</span>
      </div>
      <div className="card-strip-row">
        {(["flight", "hotel", "planner"] as AgentId[]).map((id) => (
          <MiniCard
            key={id}
            agentId={id}
            selected={id === selected}
            onSelect={(clicked) => {
              onSelect(clicked);
              onOpenCard(clicked);
            }}
          />
        ))}
      </div>
    </div>
  );
}
