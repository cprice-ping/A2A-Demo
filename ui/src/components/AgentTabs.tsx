import { AGENT_META, type AgentId } from "../agents";

export default function AgentTabs({
  agentId,
  onSwitch,
}: {
  agentId: AgentId;
  onSwitch: (id: AgentId) => void;
}) {
  return (
    <div className="agent-tabs">
      {(Object.keys(AGENT_META) as AgentId[]).map((id) => (
        <button
          key={id}
          className={`agent-tab ${id === agentId ? "active" : ""}`}
          onClick={() => onSwitch(id)}
          title={AGENT_META[id].blurb}
        >
          {AGENT_META[id].label}
        </button>
      ))}
    </div>
  );
}
