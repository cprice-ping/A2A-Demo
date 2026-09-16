"""MCP server exposing the hotel domain as tools (served at /mcp)."""

from __future__ import annotations

from fastmcp import FastMCP

from . import store
from . import auth as auth_module
from .api import data

mcp = FastMCP("hotels")


@mcp.tool
def list_cities() -> dict:
    """List cities this agent serves (code and name)."""
    return {"cities": data.CITIES, "count": len(data.CITIES)}


@mcp.tool
def search_hotels(
    city: str,
    check_in: str | None = None,
    check_out: str | None = None,
    guests: int = 1,
    max_price_per_night: float | None = None,
) -> dict:
    """Search hotels in a city (code or name like "NYC" or "New York").

    Optionally give check_in and check_out (YYYY-MM-DD) to get nights and
    total_price per property. Returns {hotels: [...], count}.
    """
    return data.search_hotels(
        city,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        max_price_per_night=max_price_per_night,
    )


@mcp.tool
def get_hotel(hotel_id: str) -> dict:
    """Get one hotel by hotel_id, e.g. NYC-HARBOR."""
    hotel = data.get_hotel(hotel_id)
    if not hotel:
        return {"error": f"Unknown hotel_id {hotel_id!r}"}
    return {"hotel": hotel}


@mcp.tool
def book_hotel(hotel_id: str, check_in: str, check_out: str, guests: int = 1) -> dict:
    """Book a hotel by hotel_id for a date range. Returns {booking: {...}}."""
    return _book_hotel_impl(hotel_id, check_in, check_out, guests)


def _book_hotel_impl(hotel_id: str, check_in: str, check_out: str, guests: int = 1) -> dict:
    """Plain booking (no identity awareness) — shared by the MCP tool."""
    hotel = data.get_hotel(hotel_id)
    if not hotel:
        return {"error": f"Unknown hotel_id {hotel_id!r}"}
    try:
        booking = store.create_hotel_booking(hotel, check_in, check_out, guests, loyalty=None)
    except ValueError as e:
        return {"error": str(e)}
    return {"booking": booking}


async def book_hotel_identity_aware(hotel_id: str, check_in: str, check_out: str, guests: int = 1) -> dict:
    """ADK-native booking wrapper that runs in the request context.

    The MCP server is a separate HTTP hop, so the middleware's contextvars
    (current_identity / current_token) are empty by the time an MCP tool
    runs. This wrapper runs on the agent itself, in the /a2a request's async
    context — the delegated identity and raw token ARE visible here, so the
    loyalty pull gets a real person token and the discount lands. Falls
    through to the plain booking path when unauthenticated.
    """
    identity = auth_module.current_identity.get()
    loyalty = None
    if identity and identity.get("sub") and auth_module.current_token.get():
        from .loyalty import lookup_loyalty

        loyalty = lookup_loyalty(auth_module.current_token.get())
    hotel = data.get_hotel(hotel_id)
    if not hotel:
        return {"error": f"Unknown hotel_id {hotel_id!r}"}
    try:
        booking = store.create_hotel_booking(hotel, check_in, check_out, guests, loyalty=loyalty)
    except ValueError as e:
        return {"error": str(e)}
    return {"booking": booking}


@mcp.tool
def get_booking(booking_id: str) -> dict:
    """Get a hotel booking by booking_id (HB-...)."""
    booking = store.get_hotel_booking(booking_id)
    if not booking:
        return {"error": f"Unknown booking_id {booking_id!r}"}
    return {"booking": booking}
