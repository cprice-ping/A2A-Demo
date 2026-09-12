"""The travel planner: a host agent delegating to flight/hotel specialists over A2A."""

from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from ag_ui_adk import AGUIToolset

FLIGHT_CARD_URL = os.environ["FLIGHT_AGENT_CARD_URL"]
HOTEL_CARD_URL = os.environ["HOTEL_AGENT_CARD_URL"]

RENDER_TOOLS = [
    "render_flight_search",
    "render_flight_booking",
    "render_hotel_search",
    "render_hotel_booking",
]

flight_agent = RemoteA2aAgent(
    name="flight_agent",
    description=(
        "Flight specialist: searches and books flights between SFO, LAX, JFK, "
        "ORD, MIA and LHR. Delegate ALL flight search and booking here."
    ),
    agent_card=FLIGHT_CARD_URL,
    use_legacy=False,
)

hotel_agent = RemoteA2aAgent(
    name="hotel_agent",
    description=(
        "Hotel specialist: searches and books hotels by city and stay dates. "
        "Delegate ALL hotel search and booking here."
    ),
    agent_card=HOTEL_CARD_URL,
    use_legacy=False,
)

INSTRUCTION = """
You are travel_planner, a trip planning coordinator. You do NOT handle flights
or hotels yourself — you delegate to two specialists over A2A:
- flight_agent: flight search and booking (airports SFO, LAX, JFK, ORD, MIA, LHR)
- hotel_agent: hotel search and booking by city and dates

## Delegation rules
- Decompose the trip request: which flights are needed, which lodging.
- Send flight requests to flight_agent and hotel requests to hotel_agent.
  They return structured results — pass them through VERBATIM, never invent
  or modify flights, hotels, prices, or booking ids.
- To BOOK, confirm the specific choice with the user first, then delegate the
  booking request to the right specialist and report its confirmation verbatim.
- Coordinate dates yourself: hotel check-in should match the arrival date of
  the outbound flight, check-out after the return flight. If the user gives a
  date range, derive the missing dates rather than asking again.

## Rendering results
After receiving results from a specialist, call the matching render_* tool so
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
    sub_agents=[flight_agent, hotel_agent],
    tools=[AGUIToolset(tool_filter=RENDER_TOOLS)],
)
