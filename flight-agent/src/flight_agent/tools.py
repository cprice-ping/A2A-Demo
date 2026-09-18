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
from .loyalty import MEMBERS


async def book_flight_identity_aware(flight_id: str, passengers: int = 1) -> dict:
    """Book a flight; applies the delegated caller's loyalty discount.

    Booking is PERSON-SCOPED: it refuses to run without a VALIDATED
    delegated identity. Identity comes from the request context
    (contextvars on the self-hosted path, the executor adapter's
    injection on GAP). No identity → an explicit error the LLM relays to
    the caller ("authentication required to book") — never an anonymous
    booking. (Searching stays anonymous-allowed; the extension is
    required=False for search, not booking.)
    """
    identity = auth_module.current_identity.get()
    if not (identity and identity.get("sub")):
        from .trace import record

        record(
            "flight-agent",
            "auth.booking_refused",
            {"reason": "no validated person identity in request context"},
        )
        return {
            "error": "Booking requires an authenticated traveler identity "
            "(delegated token missing or invalid) — no booking made."
        }
    # Loyalty: PUSH model — the planner attached the person's member
    # REFERENCE for this program outside the OBO bearer; we resolve the
    # VALUE against OUR OWN membership records (a pushed reference is a
    # hint to look up, never the tier itself). Self-hosted flavor
    # fallback: pull the linkage from the planner profile API.
    loyalty = None
    loyalty_ref = identity.get("loyalty_ref", "")
    if loyalty_ref:
        member = MEMBERS.get(loyalty_ref)
        if member:
            from .trace import record

            record(
                "flight-agent",
                "auth.loyalty",
                {"member_id": loyalty_ref, "tier": member["tier"], "via": "pushed-ref"},
            )
            loyalty = {
                "member_id": loyalty_ref,
                "tier": member["tier"],
                "discount_pct": member["discount_pct"],
            }
        else:
            from .trace import record

            record(
                "flight-agent",
                "auth.loyalty",
                {"member_id": loyalty_ref, "tier": None, "via": "pushed-ref-unknown"},
            )
    elif auth_module.current_token.get():
        from .loyalty import lookup_loyalty

        loyalty = lookup_loyalty(auth_module.current_token.get())
    flight = data.get_flight(flight_id)
    if not flight:
        return {"error": f"Unknown flight_id {flight_id!r}"}
    if not 1 <= passengers <= 9:
        return {"error": "passengers must be between 1 and 9"}
    booking = store.create_flight_booking(flight, passengers, loyalty=loyalty)
    return {"booking": booking}
