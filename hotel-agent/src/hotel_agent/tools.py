"""Identity-aware booking tool, shared by both agent flavors.

The MCP server is a separate HTTP hop, so the auth middleware's
contextvars (current_identity / current_token) are empty by the time an
MCP tool executes — the delegated identity never reaches a book_* MCP
tool. These native ADK tools run ON the agent, in the A2A request's
async context (self-hosted: middleware contextvars are set; GAP: the
executor adapter has injected the identity), so the loyalty pull gets a
real person token and the discount lands.

This module deliberately avoids mcp_server's fastmcp import — GAP has
no MCP server, and the GAP import graph must not require it.
"""

from __future__ import annotations

from . import auth as auth_module
from .api import data
from . import store


async def book_hotel_identity_aware(
    hotel_id: str, check_in: str, check_out: str, guests: int = 1
) -> dict:
    """Book a hotel; applies the delegated caller's loyalty discount.

    Identity comes from the request context (contextvars on the
    self-hosted path, the executor adapter's injection on GAP) — a bare
    client token never carries a person, so loyalty applies only when a
    delegated identity is present and the chained profile exchange
    succeeds.
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


# ---- In-process domain tools (GAP surface) -----------------------------------
#
# The self-hosted MCP server keeps serving these over HTTP for non-agent
# callers; on GAP these wrappers ARE the agent's tool surface.


def list_cities() -> dict:
    """List cities this agent serves (code and name)."""
    return {"cities": data.CITIES, "count": len(data.CITIES)}


def search_hotels(
    city: str,
    check_in: str | None = None,
    check_out: str | None = None,
    guests: int = 1,
    max_price_per_night: float | None = None,
) -> dict:
    """Search hotels in a city (code or name like "NYC" or "New York").

    Optionally give check_in and check_out (YYYY-MM-DD) to get nights and
    totals. Returns {hotels: [...], count}.
    """
    return data.search_hotels(
        city,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        max_price_per_night=max_price_per_night,
    )


def get_hotel(hotel_id: str) -> dict:
    """Get one hotel by hotel_id (from a previous search), e.g. NYC-HARBOR."""
    hotel = data.get_hotel(hotel_id)
    if not hotel:
        return {"error": f"Unknown hotel_id {hotel_id!r}"}
    return {"hotel": hotel}


def get_booking(booking_id: str) -> dict:
    """Get a hotel booking by booking_id (HB-...)."""
    booking = store.get_hotel_booking(booking_id)
    if not booking:
        return {"error": f"Unknown booking_id {booking_id!r}"}
    return {"booking": booking}
