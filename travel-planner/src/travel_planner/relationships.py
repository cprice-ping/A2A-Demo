"""GAP target relationships — the planner's side of the business contract.

Specialists deployed on GAP Agent Runtime don't advertise their auth
contract: GAP serves cards from a fixed field allowlist (no
securitySchemes), and in cross-org reality no operator publishes their
terms anonymously. The card says WHAT the agent can do; the contract
says UNDER WHAT TERMS you may ask. Those terms are a human business
agreement (see GCP-DEPLOYMENT.md "The business relationship"), and the
planner represents its side of each relationship HERE — the machine-
readable form of what the operators agreed.

Self-hosted targets (compose/k8s) stay card-driven: their cards carry
the `pingone` security scheme and the planner reads it (agent.card_security).
GAP targets are config-driven: this module fills TARGET_TENANTS[t]["security"]
from the relationship record instead of the card, and supplies the card
fetched through Google's authenticated path (platform credential).

Env per GAP target (prefix <KEY> from TARGET_RELATIONSHIPS keys):
  <KEY>_ENGINE          reasoningEngines resource name
  <KEY>_AUDIENCE        resource URI the AS mints tokens for (a2a://hotels)
  <KEY>_SCOPE           delegated scope (a2a:book)
"""

from __future__ import annotations

import os
from typing import Any

from .trace import record


def _engine_a2a_base(engine: str) -> str:
    """The A2A base URL GAP exposes for a reasoningEngines resource."""
    parts = engine.split("/")
    project, location, engine_id = parts[1], parts[3], parts[5]
    return (
        f"https://{location}-aiplatform.googleapis.com/v1beta1/projects/"
        f"{project}/locations/{location}/reasoningEngines/{engine_id}/a2a"
    )


def _card_url(engine: str) -> str:
    return f"{_engine_a2a_base(engine)}/v1/card"


def load_relationships() -> dict[str, dict[str, Any]]:
    """Read TARGET_RELATIONSHIPS_* env into per-target contract records.

    A relationship exists only if its engine env var is set — an empty
    env means this planner has no (or an unactivated) business
    relationship with that specialist in the GAP flavor.
    """
    rels: dict[str, dict[str, Any]] = {}
    for key, env_prefix in (
        ("flight-agent", "GAP_FLIGHT"),
        ("hotel-agent", "GAP_HOTEL"),
    ):
        engine = os.environ.get(f"{env_prefix}_ENGINE", "")
        if not engine:
            continue
        rels[key] = {
            "engine": engine,
            "card_url": _card_url(engine),
            "audience": os.environ.get(f"{env_prefix}_AUDIENCE", ""),
            "scope": os.environ.get(f"{env_prefix}_SCOPE", "a2a:book"),
            "token_url": os.environ.get("AS_ISSUER", "") + "/token",
        }
    return rels


# GAP relationships, filled by agent.py when env declares them.
TARGET_RELATIONSHIPS: dict[str, dict[str, Any]] = load_relationships()
