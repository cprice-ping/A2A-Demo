"""MCP server exposing the flight domain as tools (served at /mcp).

The same operations the REST API exposes, framed for LLM consumption:
plain dict returns, errors as {"error": ...} so the model can read them.
"""

from __future__ import annotations

from fastmcp import FastMCP

from . import store
from . import auth as auth_module
from .api import data

mcp = FastMCP("flights")


@mcp.tool
def list_airports() -> dict:
    """List airports this agent serves (code, city, name)."""
    return {"airports": data.AIRPORTS, "count": len(data.AIRPORTS)}


@mcp.tool
def search_flights(
    origin: str,
    destination: str,
    date: str,
    passengers: int = 1,
    max_price: float | None = None,
) -> dict:
    """Search flights between two airports/cities on a date (YYYY-MM-DD).

    Returns {flights: [...], count} where each flight has flight_id, airline,
    flight_no, depart, duration_text, price and total_price (price x passengers).
    """
    return data.search_flights(origin, destination, date, passengers=passengers, max_price=max_price)


@mcp.tool
def get_flight(flight_id: str) -> dict:
    """Get one flight by flight_id (from a previous search), e.g. SW100-2026-09-20."""
    flight = data.get_flight(flight_id)
    if not flight:
        return {"error": f"Unknown flight_id {flight_id!r}"}
    return {"flight": flight}


@mcp.tool
def book_flight(flight_id: str, passengers: int = 1) -> dict:
    """Book a flight by flight_id for N passengers. Returns {booking: {...}}.

    When the call is authenticated (A2A identity present), the loyalty
    program is applied: member tier discount on the total.
    """
    flight = data.get_flight(flight_id)
    if not flight:
        return {"error": f"Unknown flight_id {flight_id!r}"}
    if not 1 <= passengers <= 9:
        return {"error": "passengers must be between 1 and 9"}
    identity = auth_module.current_identity.get()
    loyalty = None
    if identity and identity.get("sub"):
        from .loyalty import lookup_loyalty

        loyalty = lookup_loyalty(identity["sub"])
    booking = store.create_flight_booking(flight, passengers, loyalty=loyalty)
    return {"booking": booking}


@mcp.tool
def get_booking(booking_id: str) -> dict:
    """Get a flight booking by booking_id (BK-...)."""
    booking = store.get_flight_booking(booking_id)
    if not booking:
        return {"error": f"Unknown booking_id {booking_id!r}"}
    return {"booking": booking}
