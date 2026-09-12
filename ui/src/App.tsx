import { useMemo, useState } from "react";
import { CopilotKit } from "@copilotkit/react-core";
import { CopilotSidebar } from "@copilotkit/react-ui";
import { makeAgents, AGENT_META, type AgentId } from "./agents";
import { useFlightActions, useHotelActions } from "./actions";
import AgentTabs from "./components/AgentTabs";
import "@copilotkit/react-ui/styles.css";

function ActionRegistry() {
  useFlightActions();
  useHotelActions();
  return null;
}

export default function App() {
  const agents = useMemo(() => makeAgents(), []);
  const [agentId, setAgentId] = useState<AgentId>("flight");

  return (
    <div className="app">
      <header className="app-header">
        <h1>A2A Travel Demo</h1>
        <AgentTabs agentId={agentId} onSwitch={setAgentId} />
      </header>
      <main className="app-main">
        <section className="chat-pane">
          <CopilotKit
            selfManagedAgents={agents}
            agentId={agentId}
            key={agentId}
            showDevConsole={false}
          >
            <ActionRegistry />
            <CopilotSidebar
              defaultOpen
              labels={{
                title: AGENT_META[agentId].label,
                initial: AGENT_META[agentId].blurb,
              }}
            />
          </CopilotKit>
        </section>
        <aside className="info-pane">
          <h2>How this works</h2>
          <ul>
            <li>
              <strong>Flight/Hotel agents</strong> each run their own mock REST API,
              MCP server, and ADK agent — exposed over both A2A (agent card +
              JSON-RPC) and AG-UI (this chat).
            </li>
            <li>
              <strong>Travel Planner</strong> is a host agent: it discovers the
              specialists via their agent cards and delegates over A2A.
            </li>
            <li>
              Cards in the chat are <strong>AG-UI frontend tools</strong> — the
              agent calls <code>render_*_search</code> / <code>render_*_booking</code>
              , and this UI renders them.
            </li>
          </ul>
          <p className="muted">
            Try the Flight tab: “Find flights SFO → NYC on 2026-09-20 for 2
            passengers”.
          </p>
        </aside>
      </main>
    </div>
  );
}
