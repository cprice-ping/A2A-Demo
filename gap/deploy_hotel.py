"""Deploy the hotel agent to GAP Agent Runtime (project 3682147732 / us-west1).

Usage:
  python gap/deploy_hotel.py create   # first deployment
  python gap/deploy_hotel.py upgrade  # redeploy preserving reasoningEngineId
  python gap/deploy_hotel.py card <engine-id>  # fetch the authenticated card

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
DISPLAY_NAME = "a2a-hotel-agent"

# GCS bucket GAP stages the agent package into (in this project, regional
# us-west1 or US multi-region). Ensure it exists before create/upgrade.
STAGING_BUCKET = os.environ.get(
    "STAGING_BUCKET", f"{PROJECT_NUMBER}-agent-engines-staging"
)

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

# The flight_agent package is staged via extra_packages (set in main()).
# cloudpickle stores flight_agent.* by reference (importable modules aren't
# serialized by value), so the runtime image must contain the package or
# unpickling dies with ModuleNotFoundError — surfacing only as the generic
# "failed to start" engine error (the real cause is in the engine's stderr
# log under aiplatform.googleapis.com/reasoning_engine_stderr).

# Engine env (DeploymentSpec.env — GAP-native): identity + loyalty config,
# same as the flight engine but keyed to the hotels relationship URI.
ENGINE_ENV = {
    "AS_ISSUER": os.environ.get("AS_ISSUER", ""),
    "AS_CLIENT_ID": os.environ.get("AS_CLIENT_ID", ""),
    "AS_CLIENT_SECRET": os.environ.get("AS_CLIENT_SECRET", ""),
    "P1_PROFILE_AUDIENCE": "planner-profile-api",
    "P1_PROFILE_SCOPE": "loyalty:read",
    "PLANNER_PROFILE_URL": os.environ.get(
        "GAP_PLANNER_PROFILE_URL",
        "https://a2a-travel-planner.ping-devops.com/api/profile/loyalty",
    ),
    "GAP_RELATIONSHIP_AUDIENCE": os.environ.get("GAP_HOTEL_AUDIENCE", "a2a://hotels"),
    "AUTHORIZED_ACTORS": os.environ.get("AUTHORIZED_ACTORS", "travel-planner"),
}


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


def _engine_resource_name(remote) -> str:
    """Resource name from a create/update result (Runtime wraps the
    reasoningEngine in api_resource; there is no .name)."""
    res = getattr(remote, "api_resource", None)
    return getattr(res, "name", "") or str(remote)


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "create"
    if action in ("create", "upgrade"):
        _ensure_staging_bucket()
    client = _client()

    # Import the agent module with repo paths on sys.path (the template
    # pickles the module tree at deploy time).
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    package_src = os.path.join(repo_root, "hotel-agent", "src")
    sys.path.insert(0, package_src)
    from hotel_agent.gap_agent import gap_agent  # noqa: E402
    # extra_packages takes the PACKAGE DIRECTORY, relative to the CURRENT
    # WORKING DIRECTORY. The stager tars with tar.add(path) verbatim: an
    # ABSOLUTE path stores "Users/cprice/.../flight_agent/" in the tarball
    # (ground truth: the staged dependencies.tar.gz) and the container
    # can't import it; a RELATIVE name stores "flight_agent/..." which
    # unpacks importable. (Engine stderr: "Pickle load failed: Missing
    # module ... No module named 'flight_agent'".) Chdir to the src dir
    # for the staging call so the relative name resolves.
    extra_packages = ["hotel_agent"]  # relative → tars as hotel_agent/...
    os.chdir(package_src)

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
                "extra_packages": extra_packages,
                "env_vars": ENGINE_ENV,
            },
        )
        print("created:", _engine_resource_name(remote))
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
                "extra_packages": extra_packages,
                "env_vars": ENGINE_ENV,
            },
        )
        print("updated:", _engine_resource_name(remote))
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
