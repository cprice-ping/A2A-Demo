"""Local pre-deployment test for the GAP flight agent — fails in seconds,
not minutes (the NotFlux lesson: engine-start failures at deploy time give
only a generic "failed to start"; most causes are visible locally).

Exercises, in order:
  1. imports — the full gap_agent module graph resolves in THIS venv
     (same package set the runtime installs from REQUIREMENTS)
  2. card — build_gap_agent's card passes GAP's constraints (HTTP+JSON,
     protocol 1.0, streaming off, securitySchemes preserved)
  3. set_up — card URL rewrite + executor construction
  4. pickling — cloudpickle round-trips the gap_agent object the way the
     stager will (failures here are exactly what "failed to start" hides)

Usage: python gap/local_test.py   (from the deploy venv)
"""

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "flight-agent", "src"))

os.environ.setdefault("AS_ISSUER", "https://a2a-token-as.ping-devops.com")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "cprice---agentic-demos")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-west1")
os.environ["GOOGLE_CLOUD_AGENT_ENGINE_ID"] = "local-test"

failures: list[str] = []


def check(name: str, fn) -> object | None:
    try:
        result = fn()
        print(f"  OK {name}")
        return result
    except Exception as exc:
        print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
        failures.append(name)
        return None


print("1/4 imports")
import flight_agent.gap_agent as gap_mod  # noqa: E402

G = check("flight_agent.gap_agent module", lambda: gap_mod)

print("2/4 card constraints")


def _card():
    a = G.gap_agent
    c = a.agent_card
    iface = list(c.supported_interfaces)[0]
    assert iface.protocol_binding == "HTTP+JSON", iface.protocol_binding
    assert iface.protocol_version == "1.0", iface.protocol_version
    assert c.capabilities.streaming is False
    schemes = dict(c.security_schemes or {})
    assert "pingone" in schemes, f"pingone scheme lost: {list(schemes)}"
    return a


AGENT = check("HTTP+JSON / 1.0 / streaming off / pingone scheme", _card)

print("3/4 cloudpickle round-trip (stager pickles the object BEFORE set_up)")


def _pickle():
    import cloudpickle

    blob = cloudpickle.dumps(G.gap_agent)
    restored = cloudpickle.loads(blob)
    assert restored.agent_card.name == G.gap_agent.agent_card.name
    return len(blob)


size = check("cloudpickle round-trip", _pickle)
if size:
    print(f"     ({size} bytes)")

print("4/4 set_up (card URL rewrite + executor build) — runtime-side")


def _set_up():
    AGENT.set_up()
    url = list(AGENT.agent_card.supported_interfaces)[0].url
    assert "reasoningEngines" in url, url
    assert AGENT.agent_executor is not None
    return AGENT


check("card URL -> reasoningEngines endpoint; executor built", _set_up)

print()
if failures:
    print("FAILED:", *failures, sep="\n  - ")
    sys.exit(1)
print("local pre-deploy checks passed — safe to run gap/deploy_flight.py create")
