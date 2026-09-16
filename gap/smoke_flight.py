"""Smoke-test the deployed GAP flight agent (authenticated path).

Exercises the whole GAP chain: SDK auth -> gateway -> engine -> ADK
executor -> in-process tools -> Gemini -> artifact back. No identity
token is attached (anonymous run); the loyalty chain needs the planner
side (a2a_request_meta_provider) and is exercised in P3.

Usage:
  ~/.venvs/gap-deploy/bin/python gap/smoke_flight.py "your prompt"
  ~/.venvs/gap-deploy/bin/python gap/smoke_flight.py card
"""

from __future__ import annotations

import asyncio
import os
import sys

ENGINE = os.environ.get(
    "GAP_FLIGHT_ENGINE",
    "projects/3682147732/locations/us-west1/reasoningEngines/268377594200588288",
)


def _client():
    from agentplatform import Client

    return Client(project="3682147732", location="us-west1")


def _texts(result) -> list[str]:
    """Collect text parts from the response (task or event list shapes)."""
    items = result if isinstance(result, list) else [result]
    out: list[str] = []
    for item in items:
        task = getattr(item, "task", None) or item
        arts = getattr(task, "artifacts", None) or []
        for art in arts:
            for part in getattr(art, "parts", None) or []:
                if getattr(part, "text", None):
                    out.append(part.text)
        msg = getattr(task, "message", None) or getattr(item, "message", None)
        if msg:
            for part in getattr(msg, "parts", None) or []:
                if getattr(part, "text", None):
                    out.append(part.text)
    return out


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "ask"
    remote = _client().runtimes.get(name=ENGINE)

    if action == "card":
        from a2a.utils.constants import TransportProtocol  # noqa: F401
        card = asyncio.run(remote.handle_authenticated_agent_card())
        print(str(card)[:600])
        return

    prompt = (
        sys.argv[2]
        if len(sys.argv) > 2
        else "Search flights SFO to JFK on 2026-09-20 for 1 passenger"
    )
    from a2a.types import Message, Part, Role, SendMessageRequest

    msg = Message(
        message_id="m-smoke",
        role=Role.ROLE_USER,
        parts=[Part(text=prompt)],
        # Identity rides here once the planner attaches it (P3 wiring).
        metadata={"a2a_demo_identity": ""},
    )
    result = asyncio.run(
        remote.on_message_send(request=SendMessageRequest(message=msg))
    )
    texts = _texts(result)
    print("\n".join(texts)[:1200] if texts else f"(no text) {str(result)[:300]}")


if __name__ == "__main__":
    main()
