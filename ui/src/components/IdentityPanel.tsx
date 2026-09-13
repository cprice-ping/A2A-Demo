import { useAuth } from "../auth";

/**
 * Who the demo thinks you are: planner identity + linked loyalty programs.
 * The loyalty linkage data mirrors the planner agent's profile store
 * (the planner serves it to specialists over an OAuth-protected endpoint).
 */
const LINKED_LOYALTY = [
  { program: "SkyWay Rewards (flights)", member_id: "SK-123456", tier: "GOLD", discount: "10%" },
  { program: "Hotel Bonvoy (hotels)", member_id: "HB-789", tier: "SILVER", discount: "5%" },
];

export default function IdentityPanel() {
  const { token, claims, login, logout, configuring } = useAuth();

  if (configuring) {
    return (
      <div className="identity-panel muted">
        Identity: set VITE_PLANNER_ISSUER + VITE_UI_CLIENT_ID to enable PingOne login.
        The demo runs anonymously until then.
      </div>
    );
  }

  if (!token || !claims) {
    return (
      <div className="identity-panel">
        <span className="muted">Signed out — bookings run anonymous, no loyalty.</span>
        <button className="login-button" onClick={login}>
          🔐 Sign in with PingOne
        </button>
      </div>
    );
  }

  return (
    <div className="identity-panel">
      <div className="identity-head">
        <span className="identity-name">
          {claims.name ?? claims.email ?? claims.sub}
        </span>
        <button className="logout-button" onClick={logout} title="Sign out">
          ⎋
        </button>
      </div>
      <div className="loyalty-list">
        {LINKED_LOYALTY.map((l) => (
          <div className="loyalty-row" key={l.member_id}>
            <span className="loyalty-tier">{l.tier}</span>
            <span className="loyalty-program">{l.program}</span>
            <span className="chip">{l.discount}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
