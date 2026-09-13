"""In-memory booking store. Process-local and non-durable — fine for a demo.

Booking IDs are prefixed per domain so `get_booking` can dispatch on prefix
when both agent stacks are mirrored (flights BK-, hotels HB-).
"""

from __future__ import annotations

import datetime as dt
import secrets
import threading

_lock = threading.Lock()
_flight_bookings: dict[str, dict] = {}


def _new_flight_booking_id() -> str:
    return f"BK-{secrets.token_hex(3).upper()}"


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def create_flight_booking(flight: dict, passengers: int, loyalty: dict | None = None) -> dict:
    """Create a confirmed flight booking from a search-result flight record.

    loyalty (when present) is {member_id, tier, discount_pct} resolved from
    the authenticated identity — the discount applies to the total.
    """
    booking_id = _new_flight_booking_id()
    total = flight["price"] * passengers
    if loyalty and loyalty.get("discount_pct"):
        total = round(total * (1 - loyalty["discount_pct"] / 100), 2)
    booking = {
        "booking_id": booking_id,
        "flight_id": flight["flight_id"],
        "airline": flight["airline"],
        "flight_no": flight["flight_no"],
        "origin": flight["origin"],
        "destination": flight["destination"],
        "date": flight["date"],
        "depart": flight["depart"],
        "passengers": passengers,
        "price_per_passenger": flight["price"],
        "total": total,
        "currency": flight.get("currency", "USD"),
        "status": "CONFIRMED",
        "created_at": _now_iso(),
    }
    if loyalty:
        booking["loyalty"] = {
            "member_id": loyalty["member_id"],
            "tier": loyalty["tier"],
            "discount_pct": loyalty["discount_pct"],
        }
    with _lock:
        _flight_bookings[booking_id] = booking
    return dict(booking)


def get_flight_booking(booking_id: str) -> dict | None:
    with _lock:
        b = _flight_bookings.get(booking_id)
    return dict(b) if b else None
