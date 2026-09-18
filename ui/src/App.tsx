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
                  <strong>Travel Planner</strong> is a host agent: it verifies
                  your login, then <em>delegates</em> to specialist agents over
                  the A2A protocol — flight and hotel agents that each run on
                  Google Agent Platform.
                </li>
                <li>
                  <strong>Reading the trace</strong> — each booking is a chain
                  of trust, and the rows tell it in order:
                  <br />
                  🪪 <em>Person verified</em> — your login token checked
                  <br />
                  🔑 <em>Delegation minted</em> — the token exchange AS minted
                  an OBO token: <code>sub</code>=you, <code>act</code>=the
                  planner (its k8s identity), <code>aud</code>=the one
                  specialist it's valid at
                  <br />
                  📡 <em>A2A sent</em> — the planner's delegation of your
                  prompt, carrying that OBO token + your loyalty reference
                  <br />
                  🛡️ <em>Delegation accepted</em> — the specialist validated
                  issuer, audience, and actor
                  <br />
                  🎟️ <em>Loyalty resolved</em> — the specialist matched the
                  pushed member ref against <strong>its own</strong> records
                  (the planner never sends a tier)
                  <br />
                  📥 <em>A2A reply</em> — the specialist's answer back
                </li>
                <li>
                  Every row is <strong>expandable</strong> — the JSON is the
                  wire truth behind the summary.
                </li>
              </ul>
              <p className="muted">
                🤝/📡 rows show A2A traffic in and out of each agent; a 🔑 row
                is one P1AZ-governed delegation decision. No row for a step =
                that step didn't happen.
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
