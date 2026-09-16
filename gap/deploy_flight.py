"""Deploy the flight agent to GAP Agent Runtime (project 3682147732 / us-west1).

Usage:
  python gap/deploy_flight.py create   # first deployment
  python gap/deploy_flight.py upgrade  # redeploy preserving reasoningEngineId
  python gap/deploy_flight.py card     # fetch the authenticated agent card (WIF/ADC creds)

The agent module (flight_agent.gap_agent) builds an A2aAgent wrapping our
card + an identity-aware executor. Deployment registers it as a
reasoningEngine; the platform handles serving, IAM at the edge, and the
authenticated card endpoint.
"""

from __future__ import annotations

import json
import os
import sys

PROJECT_NUMBER = "3682147732"
PROJECT_ID = "cprice---agentic-demos"
LOCATION = "us-west1"
DISPLAY_NAME = "a2a-flight-agent"

# App runtime configuration: GAP runs our module and calls build_gap_agent().
REQUIREMENTS = [
    "google-cloud-aiplatform[agent_engines]>=2.1,<3",
    "google-adk[a2a]>=2.9,<3",
    "a2a-sdk>=1.0",
    "pyjwt>=2.8",
    "httpx",
]

EXTRA_PACKAGES = ["../flight-agent/src"]  # the flight_agent package itself


def _client():
    import vertexai

    return vertexai.Client(project=PROJECT_NUMBER, location=LOCATION)


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "create"
    client = _client()

    # Import the agent module with repo paths on sys.path (the template
    # pickles the module tree at deploy time).
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(repo_root, "flight-agent", "src"))
    from flight_agent.gap_agent import gap_agent  # noqa: E402

    if action == "create":
        remote = client.agent_engines.create(
            agent=gap_agent,
            config={
                "display_name": DISPLAY_NAME,
                "requirements": REQUIREMENTS,
            },
        )
        # create(agent_engine=None, agent=…, config=…) — agent_engine is
        # None for a fresh deployment.
        print("created:", remote.name)
    elif action == "upgrade":
        # Preserve the existing reasoningEngineId: resolve by display name.
        # The list API doesn't filter by display_name server-side; scan locally.
        engines = list(client.agent_engines.list(config={}))
        if not engines:
            raise SystemExit("no existing agent engines found; run create first")
        target = None
        for e in engines:
            if getattr(e, "display_name", "") == DISPLAY_NAME or DISPLAY_NAME in str(
                getattr(e, "name", "")
            ):
                target = e
                break
        if target is None:
            raise SystemExit(f"{DISPLAY_NAME} not found; run create first")
        remote = client.agent_engines.update(
            target.name,
            agent=gap_agent,
            config={"requirements": REQUIREMENTS},
        )
        print("updated:", remote.name)
    elif action == "card":
        name = sys.argv[2] if len(sys.argv) > 2 else None
        if not name:
            raise SystemExit("card <reasoningEngine resource name>")
        remote = client.agent_engines.get(
            name=f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/reasoningEngines/{name}"
        )
        card = remote.handle_authenticated_agent_card()
        print(json.dumps(card if isinstance(card, dict) else card.model_dump(mode="json", by_alias=True), indent=2))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
