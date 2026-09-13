"""In-memory booking store for the hotel agent (HB- prefixed ids)."""

from __future__ import annotations

import datetime as dt
import secrets
import threading

_lock = threading.Lock()
_hotel_bookings: dict[str, dict] = {}


def _new_hotel_booking_id() -> str:
    return f"HB-{secrets.token_hex(3).upper()}"


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def create_hotel_booking(
    hotel: dict, check_in: str, check_out: str, guests: int, loyalty: dict | None = None
) -> dict:
    """Create a confirmed booking from a hotel record (nights pre-enriched or computed).

    loyalty (when present) is {member_id, tier, discount_pct} resolved from
    the authenticated identity — the discount applies to the total.
    """
    ci = dt.datetime.strptime(check_in, "%Y-%m-%d").date()
    co = dt.datetime.strptime(check_out, "%Y-%m-%d").date()
    nights = (co - ci).days
    if nights <= 0:
        raise ValueError("check_out must be after check_in")

    booking_id = _new_hotel_booking_id()
    total = round(hotel["price_per_night"] * nights, 2)
    if loyalty and loyalty.get("discount_pct"):
        total = round(total * (1 - loyalty["discount_pct"] / 100), 2)
    booking = {
        "booking_id": booking_id,
        "hotel_id": hotel["hotel_id"],
        "name": hotel["name"],
        "city": hotel["city"],
        "stars": hotel["stars"],
        "check_in": ci.isoformat(),
        "check_out": co.isoformat(),
        "nights": nights,
        "guests": guests,
        "price_per_night": hotel["price_per_night"],
        "total": total,
        "currency": "USD",
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
        _hotel_bookings[booking_id] = booking
    return dict(booking)


def get_hotel_booking(booking_id: str) -> dict | None:
    with _lock:
        b = _hotel_bookings.get(booking_id)
    return dict(b) if b else None
