"""The flight agent: ADK LlmAgent with MCP tools + AG-UI frontend tools."""

from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StreamableHTTPConnectionParams
from ag_ui_adk import AGUIToolset

from . import mcp_server

MCP_SELF_URL = os.environ.get("MCP_SELF_URL", "http://localhost:8080/mcp")

FRONTEND_TOOLS = ["render_flight_search", "render_flight_booking"]

# The MCP server's book_flight is excluded from what these agents see: it
# runs over a separate HTTP hop where the middleware's identity contextvars
# are empty, so it can never apply loyalty. book_flight_identity_aware below
# is a native ADK tool the agent calls instead — it runs IN the A2A request's
# async context, where identity + the raw token are actually set. MCP still
# serves plain book_flight to non-agent HTTP callers.
def _exclude_book_flight(tool, readonly_context=None) -> bool:
    return tool.name != "book_flight"


INSTRUCTION = """
You are flight_agent, a flight search and booking assistant.

## Tools
- list_airports, search_flights, get_flight, get_booking are the ONLY source
  of flight data. Never invent flights, prices, or booking ids.
- book_flight_identity_aware books a flight (applies the caller's loyalty
  discount automatically when they're signed in — nothing else to do for that).
- The render_* tools are FRONTEND tools: the user's chat UI renders their arguments
  as visual cards. Their results mean "rendered OK" — do not restate the data.

## Search procedure
1. Resolve city names to airport codes with list_airports (accepts codes and city
   names like "NYC" or "San Francisco").
2. search_flights(origin, destination, date YYYY-MM-DD, passengers, max_price).
3. If the user hasn't given a date, ask for one. Never guess dates.
4. After a search, ALWAYS call render_flight_search with the query and the flights
   list VERBATIM from the tool response (the UI renders them as a card). In your
   text reply, say one short sentence and do NOT re-list the flights.
5. Apply max_price or airline preferences with the tool's parameters when possible;
   filter the rendered list yourself only if the tool can't.

## Booking procedure
1. Confirm the flight and passenger count with the user BEFORE calling
   book_flight_identity_aware.
2. After a successful booking, call render_flight_booking with the booking object
   VERBATIM, and reply with one sentence including the booking id.
3. If a tool returns {"error": ...}, tell the user plainly what went wrong and
   suggest the next step. Never hide errors.

## Style
Short, direct sentences. No markdown tables of results — cards show them.
""".strip()

root_agent = Agent(
    name="flight_agent",
    model="gemini-2.5-flash",
    description="Flight specialist: search and book flights between SFO, LAX, JFK, ORD, MIA and LHR.",
    instruction=INSTRUCTION,
    tools=[
        McpToolset(
            connection_params=StreamableHTTPConnectionParams(url=MCP_SELF_URL),
            tool_filter=_exclude_book_flight,
        ),
        AGUIToolset(tool_filter=FRONTEND_TOOLS),
        mcp_server.book_flight_identity_aware,
    ],
)

# The A2A-facing instance serves agent-to-agent callers (e.g. the travel
# planner). Frontend render tools make no sense there (there is no browser on
# the other end) — instead the agent returns the structured data in its reply
# so the CALLER can render it.
A2A_INSTRUCTION = """
You are flight_agent, a flight search and booking specialist called by another
agent over A2A. There is no human reading your words — your caller renders UI
from your reply.

## Tools
list_airports, search_flights, get_flight, get_booking are the ONLY source of
flight data. Never invent flights, prices, or booking ids. Book with
book_flight_identity_aware (applies the caller's loyalty discount automatically
when the delegated identity carries one).

## Responding
- Resolve city names to airport codes with list_airports first.
- After a search, your reply MUST include the full flights list as JSON,
  exactly as the tool returned it: {"query": {...}, "flights": [...]}. Do not
  summarize it into prose — the caller needs the raw records verbatim.
- After a booking, include the full booking object as JSON.
- If a tool returns {"error": ...}, reply with that error JSON plainly.
""".strip()

a2a_agent = Agent(
    name="flight_agent",
    model="gemini-2.5-flash",
    description="Flight specialist: search and book flights between SFO, LAX, JFK, ORD, MIA and LHR.",
    instruction=A2A_INSTRUCTION,
    tools=[
        McpToolset(
            connection_params=StreamableHTTPConnectionParams(url=MCP_SELF_URL),
            tool_filter=_exclude_book_flight,
        ),
        mcp_server.book_flight_identity_aware,
    ],
)
