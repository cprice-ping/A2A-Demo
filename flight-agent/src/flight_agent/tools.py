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

    Booking requires a PERSON delegation: a validated identity with the
    a2a:book scope. The executor gate already guarantees SOME valid
    identity (no execution without one); the scope check distinguishes
    person delegations (sub=person, P1AZ grants a2a:book) from person-
    less workload sessions (sub=a workload identity — may search, never
    book; P1AZ does not grant a2a:book to workload subjects). No
    identity → refuse; person-less session → refuse with a distinct
    error. The booking lands only when a person is present through an
    authorized actor.
    """
    identity = auth_module.current_identity.get()
    # Two separate requirements, two rungs (see GCP-DEPLOYMENT.md):
    # 1. A validated identity MUST be present (the executor gate already
    #    guarantees this; checked here as defense in depth).
    # 2. The identity must be a PERSON delegation, not a person-less
    #    workload session: bookings carry person context (loyalty, whose
    #    trip) that only a person delegation has. Specialist policy: a
    #    person-less session (sub = a workload identity) may search but
    #    never book — enforced here by requiring a2a:book, which P1AZ
    #    does not grant to workload subjects.
    if not (identity and identity.get("sub")):
        from .trace import record

        record(
            "flight-agent",
            "auth.booking_refused",
            {"reason": "no validated identity in request context"},
        )
        return {
            "error": "Booking requires an authenticated traveler identity "
            "(delegated token missing or invalid) — no booking made."
        }
    if "a2a:book" not in (identity.get("scope") or ""):
        from .trace import record

        record(
            "flight-agent",
            "auth.booking_refused",
            {
                "reason": "identity lacks a2a:book scope (person-less session?)",
                "sub": identity.get("sub", ""),
            },
        )
        return {
            "error": "Booking requires a person-delegated identity with "
            "a2a:book scope — this session is not person-scoped, so no "
            "booking was made."
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
