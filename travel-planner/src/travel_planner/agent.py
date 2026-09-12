"""The travel planner: a host agent delegating to flight/hotel specialists over A2A."""

from __future__ import annotations

import os

import httpx
from google.protobuf.json_format import Parse

from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.tools.agent_tool import AgentTool
from ag_ui_adk import AGUIToolset
from a2a.types import AgentCard

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
    resp = httpx.get(url, timeout=15.0)
    resp.raise_for_status()
    return Parse(resp.content, AgentCard())


flight_specialist = RemoteA2aAgent(
    name="flight_specialist",
    description=(
        "Searches and books flights between SFO, LAX, JFK, ORD, MIA and LHR."
    ),
    agent_card=fetch_card(FLIGHT_CARD_URL),
    use_legacy=False,
)

hotel_specialist = RemoteA2aAgent(
    name="hotel_specialist",
    description="Searches and books hotels by city and stay dates.",
    agent_card=fetch_card(HOTEL_CARD_URL),
    use_legacy=False,
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
