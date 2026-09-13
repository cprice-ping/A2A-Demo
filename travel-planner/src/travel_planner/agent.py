"""The travel planner: a host agent delegating to flight/hotel specialists over A2A."""

from __future__ import annotations

import json
import os

import httpx
from google.protobuf.json_format import Parse

from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.tools.agent_tool import AgentTool
from ag_ui_adk import AGUIToolset
from a2a.types import AgentCard

from . import auth as auth_module
from .trace import record, record_exchange
from typing import Any

FLIGHT_CARD_URL = os.environ["FLIGHT_AGENT_CARD_URL"]
HOTEL_CARD_URL = os.environ["HOTEL_AGENT_CARD_URL"]

RENDER_TOOLS = [
    "render_flight_search",
    "render_flight_booking",
    "render_hotel_search",
    "render_hotel_booking",
]


def fetch_card(url: str) -> AgentCard:
    """Fetch an agent card over HTTP and return it as an AgentCard object.

    RemoteA2aAgent only accepts plain-http card URLs on loopback hosts, which
    breaks container-network hostnames (flight-agent:8080). Fetching here and
    passing the object is the documented escape hatch: a directly-passed card
    did not come off the network inside ADK, so its transport is the caller's
    responsibility — that's fine on a trusted compose/k8s network.
    """
    record("travel-planner", "a2a.card_fetch", {"url": url})
    resp = httpx.get(url, timeout=15.0)
    resp.raise_for_status()
    return Parse(resp.content, AgentCard())


def _make_traced_client(target: str) -> httpx.AsyncClient:
    """AsyncClient recording full outbound A2A exchanges for the trace panel.

    httpx event hooks run around the whole send, so the response hook has
    access to the request object; we capture both bodies verbatim (SSE
    responses are buffered via astream passthrough — handled by reading
    aread() only for buffered responses; for streams we record what the
    hooks see: request body + response status, plus the response body when
    the transport hands it back non-streamed).
    """

    async def log_request(request: httpx.Request) -> None:
        # Identity: exchange the human's planner token at the target tenant
        # and send the result as the A2A call's bearer. Card fetches
        # (.well-known) stay anonymous.
        if (
            ".well-known" not in str(request.url.path)
            and auth_module.user_token_var.get()
        ):
            try:
                token = auth_module.exchange_token(target, auth_module.user_token_var.get())
                if token:
                    request.headers["Authorization"] = f"Bearer {token}"
            except Exception as exc:  # exchange failure → proceed anonymous
                record(
                    "travel-planner",
                    "auth.token_exchange_failed",
                    {"target": target, "error": str(exc)},
                )

        request_body = None
        text = ""
        rpc = None
        try:
            body = json.loads(request.content)
            rpc = body.get("method")
            message = (body.get("params") or {}).get("message") or {}
            text = next(
                (
                    p.get("text")
                    for p in message.get("parts", [])
                    if isinstance(p, dict) and p.get("text")
                ),
                "",
            )
            request_body = body
        except Exception:
            pass
        record(
            "travel-planner",
            "a2a.outbound",
            {"target": target, "rpc": rpc, "text": str(text)[:140]},
        )
        # Stash for the response hook. NOTE: use a plain attribute —
        # request.extensions belongs to httpcore transport plumbing, which
        # treats values there as callables.
        request.trace_meta = {"request_body": request_body, "target": target}

    async def log_response(response: httpx.Response) -> None:
        meta = getattr(response.request, "trace_meta", None) or {}
        if not meta:
            return
        request_body = meta.get("request_body")
        target = meta.get("target", "unknown")
        content_type = response.headers.get("content-type", "")
        is_sse = "text/event-stream" in content_type
        response_obj: Any
        if is_sse:
            # Response body is a stream consumed by the A2A client; record
            # status only (the SPECIALIST's own trace holds the full exchange).
            response_obj = {"streamed": True}
        else:
            try:
                response_obj = json.loads(response.content)
            except Exception:
                response_obj = None
        record_exchange(
            source="travel-planner",
            direction="outbound",
            path=str(response.request.url.path),
            request=request_body,
            response=response_obj,
            status=response.status_code,
            elapsed_ms=None,
            sse=is_sse,
            peer=meta.get("target", target),
        )

    return httpx.AsyncClient(
        timeout=600.0,
        event_hooks={"request": [log_request], "response": [log_response]},
    )


flight_specialist = RemoteA2aAgent(
    name="flight_specialist",
    description=(
        "Searches and books flights between SFO, LAX, JFK, ORD, MIA and LHR."
    ),
    agent_card=fetch_card(FLIGHT_CARD_URL),
    use_legacy=False,
    httpx_client=_make_traced_client("flight-agent"),
)

hotel_specialist = RemoteA2aAgent(
    name="hotel_specialist",
    description="Searches and books hotels by city and stay dates.",
    agent_card=fetch_card(HOTEL_CARD_URL),
    use_legacy=False,
    httpx_client=_make_traced_client("hotel-agent"),
)

# AgentTool keeps the planner in control of the loop: it CALLS each specialist
# like a function (one request -> structured result back) instead of using
# LLM-driven transfers, which let one specialist absorb the whole conversation.
flight_tool = AgentTool(agent=flight_specialist)
hotel_tool = AgentTool(agent=hotel_specialist)

INSTRUCTION = """
You are travel_planner, a trip planning coordinator. You do NOT search flights
or hotels yourself — you have two specialist TOOLS (each one is a remote agent
reached over the A2A protocol):

- flight_specialist: flight search and booking (airports SFO, LAX, JFK, ORD, MIA, LHR)
- hotel_specialist: hotel search and booking by city and dates

## Delegation rules
- Decompose the user's trip into legs. Call flight_specialist for the flight
  leg and hotel_specialist for the lodging leg — as separate tool calls, each
  asking for exactly that leg ("search flights SFO->JFK 2026-09-20, 2
  passengers" — nothing about hotels in the flight call).
- A trip request needs BOTH calls before you reply. After the flight results
  come back, call hotel_specialist next.
- Tool results are structured data — pass them through VERBATIM, never invent
  or modify flights, hotels, prices, or booking ids.
- To BOOK, confirm the specific choice with the user first, then call the
  specialist's booking request and report its confirmation verbatim.
- Coordinate dates yourself: hotel check-in should match the arrival date of
  the outbound flight, check-out after the return flight. If the user gives a
  length of stay, derive dates rather than asking again.

## Rendering results
After each specialist's results come back, call the matching render_* tool so
the UI shows a card — render_flight_search / render_flight_booking with flight
data, render_hotel_search / render_hotel_booking with hotel data. Pass the
specialist's data through VERBATIM. In your text, one short sentence; never
re-list results that are already on a card.

## Style
Short, direct sentences. Surface any specialist errors plainly.
""".strip()

root_agent = Agent(
    name="travel_planner",
    model="gemini-2.5-flash",
    description="Plans trips by delegating to flight and hotel specialist agents.",
    instruction=INSTRUCTION,
    tools=[flight_tool, hotel_tool, AGUIToolset(tool_filter=RENDER_TOOLS)],
)
