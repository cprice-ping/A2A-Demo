"""Deploy the flight agent to GAP Agent Runtime (project 3682147732 / us-west1).

Usage:
  python gap/deploy_flight.py create   # first deployment
  python gap/deploy_flight.py upgrade  # redeploy preserving reasoningEngineId
  python gap/deploy_flight.py card <engine-id>  # fetch the authenticated card

Client-side env: a dedicated venv (the global env may carry older ADK pins
that conflict with aiplatform 2.x):
  python3 -m venv ~/.venvs/gap-deploy
  ~/.venvs/gap-deploy/bin/pip install "google-cloud-aiplatform[agent_engines]>=2.1,<3"
Prereqs: ADC (gcloud auth application-default login), Cloud Resource
Manager API enabled, and a GCS staging bucket (STAGING_BUCKET env or the
default below — created on first run).
"""

from __future__ import annotations

import json
import os
import sys

PROJECT_NUMBER = "3682147732"
PROJECT_ID = "cprice---agentic-demos"
LOCATION = "us-west1"
DISPLAY_NAME = "a2a-flight-agent"

# GCS bucket GAP stages the agent package into (in this project, regional
# us-west1 or US multi-region). Ensure it exists before create/upgrade.
STAGING_BUCKET = os.environ.get(
    "STAGING_BUCKET", f"{PROJECT_NUMBER}-agent-engines-staging"
)

# App runtime configuration: GAP runs our module and calls build_gap_agent().
# App runtime configuration: GAP runs our module and calls build_gap_agent().
# pydantic + cloudpickle are required by the runtime's pickle/build pipeline
# (the SDK warns on missing requirements at create time; missing them fails
# engine start with only a generic "failed to start" error).
REQUIREMENTS = [
    "google-cloud-aiplatform[agent_engines]>=2.1,<3",
    "google-adk[a2a]>=2.9,<3",
    "a2a-sdk>=1.0",
    "pyjwt>=2.8",
    "httpx",
    "pydantic>=2",
    "cloudpickle",
]

EXTRA_PACKAGES = ["../flight-agent/src"]  # the flight_agent package itself


def _ensure_staging_bucket() -> None:
    """Create the staging bucket if absent (first deployment only)."""
    from google.cloud import storage

    client = storage.Client(project=PROJECT_ID)
    try:
        client.get_bucket(STAGING_BUCKET)
    except Exception:
        bucket = client.bucket(STAGING_BUCKET)
        bucket.storage_class = "STANDARD"
        bucket.create(location=LOCATION)
        print(f"created staging bucket: gs://{STAGING_BUCKET}")


def _client():
    from agentplatform import Client

    return Client(project=PROJECT_NUMBER, location=LOCATION)


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "create"
    if action in ("create", "upgrade"):
        _ensure_staging_bucket()
    client = _client()

    # Import the agent module with repo paths on sys.path (the template
    # pickles the module tree at deploy time).
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(repo_root, "flight-agent", "src"))
    from flight_agent.gap_agent import gap_agent  # noqa: E402

    if action == "create":
        # agentplatform (post-2.0 SDK): client.runtimes.create(runtime=None,
        # agent=…, config=AgentRuntimeConfig-dict) replaces vertexai's
        # client.agent_engines.create.
        remote = client.runtimes.create(
            agent=gap_agent,
            config={
                "display_name": DISPLAY_NAME,
                "requirements": REQUIREMENTS,
                "staging_bucket": f"gs://{STAGING_BUCKET}",
            },
        )
        print("created:", remote.name)
    elif action == "upgrade":
        # Preserve the existing reasoningEngineId: resolve by display name.
        # The list API doesn't filter by display_name server-side; scan locally.
        engines = list(client.runtimes.list(config={}))
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
        remote = client.runtimes.update(
            name=target.name,
            agent=gap_agent,
            config={
                "requirements": REQUIREMENTS,
                "staging_bucket": f"gs://{STAGING_BUCKET}",
            },
        )
        print("updated:", remote.name)
    elif action == "card":
        name = sys.argv[2] if len(sys.argv) > 2 else None
        if not name:
            raise SystemExit("card <reasoningEngine resource name>")
        remote = client.runtimes.get(
            name=f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/reasoningEngines/{name}"
        )
        card = remote.handle_authenticated_agent_card()
        print(json.dumps(card if isinstance(card, dict) else card.model_dump(mode="json", by_alias=True), indent=2))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
