"""MCP server exposing the hotel domain as tools (served at /mcp)."""

from __future__ import annotations

from fastmcp import FastMCP

from . import store
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
    hotel = data.get_hotel(hotel_id)
    if not hotel:
        return {"error": f"Unknown hotel_id {hotel_id!r}"}
    try:
        booking = store.create_hotel_booking(hotel, check_in, check_out, guests)
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
