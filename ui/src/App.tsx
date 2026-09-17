import { useMemo, useState } from "react";
import { CopilotKit } from "@copilotkit/react-core";
import { CopilotSidebar } from "@copilotkit/react-ui";
import { makeAgents, AGENT_META, type AgentId } from "./agents";
import { useAuth } from "./auth";
import { useFlightActions, useHotelActions } from "./actions";
import AgentTabs from "./components/AgentTabs";
import ActivityPanel from "./components/ActivityPanel";
import ArchitectureDiagram from "./components/ArchitectureDiagram";
import CardStrip, { AgentCardModal } from "./components/CardStrip";
import IdentityPanel from "./components/IdentityPanel";
import "@copilotkit/react-ui/styles.css";

function ActionRegistry() {
  useFlightActions();
  useHotelActions();
  return null;
}

export default function App() {
  const { token, login, configuring } = useAuth();
  // Agents re-created when the auth token changes so the planner agent
  // carries the fresh Authorization header.
  const agents = useMemo(() => makeAgents(token ?? undefined), [token]);
  const [agentId, setAgentId] = useState<AgentId>("planner");
  const [activityExpanded, setActivityExpanded] = useState(false);
  const [showArch, setShowArch] = useState(false);
  const [showCard, setShowCard] = useState<AgentId | null>(null);

  // Sign-in gate: the planner requires a PingOne token on /agui (the
  // planner enforces AUTH_REQUIRED); a signed-out visitor gets the
  // sign-in prompt instead of a chat that would only error.
  const needsSignIn = !token && !configuring;

  return (
    <div className="app">
      <header className="app-header">
        <h1>A2A Travel Demo</h1>
        <AgentTabs agentId={agentId} onSwitch={setAgentId} />
        <IdentityPanel />
      </header>
      {showArch && <ArchitectureDiagram onClose={() => setShowArch(false)} />}
      {showCard && (
        <AgentCardModal agentId={showCard} onClose={() => setShowCard(null)} />
      )}
      <main className="app-main">
        <aside
          className={`activity-pane ${activityExpanded ? "expanded" : ""}`}
        >
          <div className="pane-buttons">
            <button className="arch-button" onClick={() => setShowArch(true)}>
              🗺️ Architecture
            </button>
            <button
              className="arch-button"
              onClick={() => setShowCard(agentId)}
              title={`Show the A2A agent card of ${AGENT_META[agentId].label}`}
            >
              🪪 Agent card
            </button>
          </div>
          <ActivityPanel
            enabled
            expanded={activityExpanded}
            onToggleExpanded={() => setActivityExpanded((v) => !v)}
          />
          {!activityExpanded && (
            <div className="info-pane-inner">
              <h2>How this works</h2>
              <ul>
                <li>
                  <strong>Flight/Hotel agents</strong> each run their own mock REST
                  API, MCP server, and ADK agent — exposed over both A2A (agent
                  card + JSON-RPC) and AG-UI (this chat).
                </li>
                <li>
                  <strong>Travel Planner</strong> is a host agent: it discovers the
                  specialists via their agent cards and delegates over A2A.
                </li>
                <li>
                  Cards in the chat are <strong>AG-UI frontend tools</strong> — the
                  agent calls <code>render_*_search</code> /{" "}
                  <code>render_*_booking</code>, and this UI renders them.
                </li>
              </ul>
              <p className="muted">
                🤝/📡 rows show A2A traffic in and out of each agent; 🔧 rows are
                MCP tool calls the LLM made. ⤢ expands the log.
              </p>
            </div>
          )}
        </aside>
        <section className="chat-pane">
          <CardStrip
            selected={agentId}
            onSelect={setAgentId}
            onOpenCard={setShowCard}
          />
          {needsSignIn ? (
            <div className="sign-in-gate">
              <h2>🔐 Sign in to chat</h2>
              <p>
                The travel planner authenticates every prompt: your PingOne
                (planner tenant) identity rides on each request, and the
                specialists receive a delegated identity — bookings land as
                <em> you</em>, with your loyalty applied.
              </p>
              <p className="muted">
                The agent card and trace panels below stay visible without
                signing in (protocol discovery + observability are public by
                design; the agent prompt is not).
              </p>
              <button className="login-button" onClick={login}>
                🔐 Sign in with PingOne
              </button>
            </div>
          ) : (
            <CopilotKit
              selfManagedAgents={agents}
              agentId={agentId}
              agent={agentId}
              key={agentId}
              showDevConsole={false}
              enableInspector={false}
            >
              <ActionRegistry />
              <CopilotSidebar
                defaultOpen
                clickOutsideToClose={false}
                hitEscapeToClose={false}
                labels={{
                  title: AGENT_META[agentId].label,
                  initial: AGENT_META[agentId].blurb,
                }}
              />
            </CopilotKit>
          )}
        </section>
      </main>
    </div>
  );
}
