"""The hotel agent: ADK agent with MCP tools + AG-UI frontend tools."""

from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StreamableHTTPConnectionParams
from ag_ui_adk import AGUIToolset

from . import instructions, mcp_server

MCP_SELF_URL = os.environ.get("MCP_SELF_URL", "http://localhost:8081/mcp")

FRONTEND_TOOLS = ["render_hotel_search", "render_hotel_booking"]

# The MCP server's book_hotel is excluded from what these agents see: it runs
# over a separate HTTP hop where the middleware's identity contextvars are
# empty, so it can never apply loyalty. book_hotel_identity_aware below is a
# native ADK tool the agent calls instead — it runs IN the A2A request's
# async context, where identity + the raw token are actually set. MCP still
# serves plain book_hotel to non-agent HTTP callers.
def _exclude_book_hotel(tool, readonly_context=None) -> bool:
    return tool.name != "book_hotel"


INSTRUCTION = """
You are hotel_agent, a hotel search and booking assistant.

## Tools
- list_cities, search_hotels, get_hotel, get_booking are the ONLY source of
  hotel data. Never invent hotels, prices, or booking ids.
- book_hotel_identity_aware books a hotel (applies the caller's loyalty
  discount automatically when they're signed in — nothing else to do for that).
- The render_* tools are FRONTEND tools: the user's chat UI renders their
  arguments as visual cards. Their results mean "rendered OK" — do not restate
  the data in text.

## Search procedure
1. Resolve city names with list_cities if the user's city is ambiguous.
2. search_hotels(city, check_in YYYY-MM-DD, check_out YYYY-MM-DD, guests,
   max_price_per_night). If the user gives a length of stay instead of dates
   ("2 nights from Sep 20"), compute the dates yourself and search.
3. After a search, ALWAYS call render_hotel_search with the query and the
   hotels list VERBATIM. In your text reply, one short sentence; do NOT
   re-list the hotels.
4. If the user asks about one property, answer from get_hotel — no render
   call needed unless they want the list again.

## Booking procedure
1. Confirm the hotel, dates, and guest count with the user BEFORE calling
   book_hotel_identity_aware.
2. After a successful booking, call render_hotel_booking with the booking
   object VERBATIM, and reply with one sentence including the booking id.
3. If a tool returns {"error": ...}, tell the user plainly what went wrong and
   suggest the next step. Never hide errors.

## Style
Short, direct sentences. No markdown tables of results — cards show them.
""".strip()

root_agent = Agent(
    name="hotel_agent",
    model="gemini-2.5-flash",
    description="Hotel specialist: search and book hotels in NYC, LAX, MIA, LHR, SFO and ORD.",
    instruction=INSTRUCTION,
    tools=[
        McpToolset(
            connection_params=StreamableHTTPConnectionParams(url=MCP_SELF_URL),
            tool_filter=_exclude_book_hotel,
        ),
        AGUIToolset(tool_filter=FRONTEND_TOOLS),
        mcp_server.book_hotel_identity_aware,
    ],
)

# The A2A-facing instance serves agent-to-agent callers (e.g. the travel
# planner). Frontend render tools make no sense there (there is no browser on
# the other end) — instead the agent returns the structured data in its reply
# so the CALLER can render it.
A2A_INSTRUCTION = instructions.A2A_INSTRUCTION

a2a_agent = Agent(
    name="hotel_agent",
    model="gemini-2.5-flash",
    description="Hotel specialist: search and book hotels in NYC, LAX, MIA, LHR, SFO and ORD.",
    instruction=A2A_INSTRUCTION,
    tools=[
        McpToolset(
            connection_params=StreamableHTTPConnectionParams(url=MCP_SELF_URL),
            tool_filter=_exclude_book_hotel,
        ),
        mcp_server.book_hotel_identity_aware,
    ],
)
