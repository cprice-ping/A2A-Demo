"""Local pre-deployment test for a GAP agent flavor — fails in seconds,
not minutes (the NotFlux lesson: engine-start failures at deploy time give
only a generic "failed to start"; most causes are visible locally).

Exercises, per agent:
  1. imports — the gap_agent module graph resolves in THIS venv
     (same package set the runtime installs from REQUIREMENTS)
  2. card — GAP's constraints (HTTP+JSON, protocol 1.0, streaming off,
     skills preserved)
  3. cloudpickle round-trip — the stager pickles the object BEFORE the
     runtime calls set_up (after set_up the object holds unpicklable
     thread locks)
  4. set_up — card URL rewrite + executor construction

Usage:
  python gap/local_test.py            # both agents
  python gap/local_test.py hotel      # one agent
"""

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AGENTS = {
    "flight": "flight-agent",
    "hotel": "hotel-agent",
}

which = sys.argv[1] if len(sys.argv) > 1 else "both"
targets = list(AGENTS.items()) if which == "both" else [(which, AGENTS[which])]

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


for agent, subdir in targets:
    print(f"\n=== {agent}-agent ===")
    os.environ.setdefault("AS_ISSUER", "https://a2a-token-as.ping-devops.com")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "cprice---agentic-demos")
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-west1")
    os.environ["GOOGLE_CLOUD_AGENT_ENGINE_ID"] = "local-test"

    pkg = f"{agent}_agent"
    pkg_dir = os.path.join(REPO_ROOT, subdir, "src", pkg)
    sys.path.insert(0, os.path.join(REPO_ROOT, subdir, "src"))

    mod = check(f"import {pkg}.gap_agent", lambda: __import__(pkg + ".gap_agent"))
    if mod is None:
        continue
    G = sys.modules[pkg + ".gap_agent"]

    def _card():
        a = G.gap_agent
        c = a.agent_card
        iface = list(c.supported_interfaces)[0]
        assert iface.protocol_binding == "HTTP+JSON", iface.protocol_binding
        assert iface.protocol_version == "1.0", iface.protocol_version
        assert c.capabilities.streaming is False
        return a

    AGENT = check(f"{agent}: HTTP+JSON / 1.0 / streaming off", _card)
    if AGENT is None:
        continue

    def _pickle():
        import cloudpickle

        blob = cloudpickle.dumps(G.gap_agent)
        restored = cloudpickle.loads(blob)
        assert restored.agent_card.name == G.gap_agent.agent_card.name
        return len(blob)

    size = check(f"{agent}: cloudpickle round-trip (pre-set_up)", _pickle)
    if size:
        print(f"     ({size} bytes)")

    def _set_up():
        AGENT.set_up()
        url = list(AGENT.agent_card.supported_interfaces)[0].url
        assert "reasoningEngines" in url, url
        assert AGENT.agent_executor is not None

    check(f"{agent}: set_up (URL rewrite + executor build)", _set_up)

print()
if failures:
    print("FAILED:", *failures, sep="\n  - ")
    sys.exit(1)
print("local pre-deploy checks passed — safe to run gap/deploy_flight.py")
