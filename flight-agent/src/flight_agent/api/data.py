"""Representative flight data: airports, routes, and deterministic schedule synthesis.

There is no real inventory — searches synthesize a schedule for any requested
date from the route catalog. Synthesis is deterministic per (origin, destination,
date) so repeated searches (including LLM retries) return identical results.
"""

from __future__ import annotations

import datetime as dt
import re
import random

# --- Airports ---------------------------------------------------------------

AIRPORTS: list[dict] = [
    {"code": "SFO", "city": "San Francisco", "name": "San Francisco Intl"},
    {"code": "LAX", "city": "Los Angeles", "name": "Los Angeles Intl"},
    {"code": "JFK", "city": "New York", "name": "John F. Kennedy Intl"},
    {"code": "ORD", "city": "Chicago", "name": "O'Hare Intl"},
    {"code": "MIA", "city": "Miami", "name": "Miami Intl"},
    {"code": "LHR", "city": "London", "name": "London Heathrow"},
]

AIRPORTS_BY_CODE = {a["code"]: a for a in AIRPORTS}

# Cities an airport code can be referred to by (lowercased) -> code
CITY_TO_CODE = {
    "san francisco": "SFO",
    "los angeles": "LAX",
    "new york": "JFK",
    "nyc": "JFK",
    "chicago": "ORD",
    "miami": "MIA",
    "london": "LHR",
}

# --- Route catalog ----------------------------------------------------------
# base schedule per route; prices jitter deterministically per date

ROUTES: list[dict] = [
    {"origin": "SFO", "destination": "JFK", "airline": "SkyWay", "flight_no": "SW100", "depart": "08:30", "duration_min": 330, "base_price": 289.00},
    {"origin": "JFK", "destination": "SFO", "airline": "SkyWay", "flight_no": "SW101", "depart": "07:15", "duration_min": 370, "base_price": 299.00},
    {"origin": "SFO", "destination": "JFK", "airline": "PacificAir", "flight_no": "PA220", "depart": "12:45", "duration_min": 345, "base_price": 319.00},
    {"origin": "JFK", "destination": "SFO", "airline": "PacificAir", "flight_no": "PA221", "depart": "17:30", "duration_min": 385, "base_price": 309.00},
    {"origin": "SFO", "destination": "LAX", "airline": "PacificAir", "flight_no": "PA310", "depart": "09:00", "duration_min": 85, "base_price": 129.00},
    {"origin": "LAX", "destination": "SFO", "airline": "PacificAir", "flight_no": "PA311", "depart": "18:20", "duration_min": 90, "base_price": 125.00},
    {"origin": "JFK", "destination": "LHR", "airline": "AtlanticOne", "flight_no": "AO50", "depart": "21:10", "duration_min": 420, "base_price": 589.00},
    {"origin": "LHR", "destination": "JFK", "airline": "AtlanticOne", "flight_no": "AO51", "depart": "10:40", "duration_min": 455, "base_price": 549.00},
    {"origin": "ORD", "destination": "MIA", "airline": "SkyWay", "flight_no": "SW440", "depart": "06:50", "duration_min": 190, "base_price": 179.00},
    {"origin": "MIA", "destination": "ORD", "airline": "SkyWay", "flight_no": "SW441", "depart": "14:15", "duration_min": 200, "base_price": 169.00},
    {"origin": "LAX", "destination": "JFK", "airline": "TransAm", "flight_no": "TA80", "depart": "08:00", "duration_min": 300, "base_price": 249.00},
    {"origin": "JFK", "destination": "LAX", "airline": "TransAm", "flight_no": "TA81", "depart": "15:00", "duration_min": 335, "base_price": 259.00},
    {"origin": "SFO", "destination": "ORD", "airline": "TransAm", "flight_no": "TA220", "depart": "10:30", "duration_min": 250, "base_price": 199.00},
    {"origin": "ORD", "destination": "SFO", "airline": "TransAm", "flight_no": "TA221", "depart": "19:45", "duration_min": 275, "base_price": 205.00},
]


def resolve_airport(value: str) -> str | None:
    """Resolve a user-supplied airport code or city name to an airport code."""
    v = (value or "").strip().upper()
    if v in AIRPORTS_BY_CODE:
        return v
    return CITY_TO_CODE.get((value or "").strip().lower())


# --- Schedule synthesis -----------------------------------------------------

DATE_FORMAT = "%Y-%m-%d"


def _stable_hash(text: str) -> int:
    """hash() is salted per process; use a stable digest instead."""
    import hashlib

    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def _parse_date(date: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(date, DATE_FORMAT).date()
    except (TypeError, ValueError):
        return None


def _add_minutes(hhmm: str, minutes: int) -> str:
    base = dt.datetime.strptime(hhmm, "%H:%M") + dt.timedelta(minutes=minutes)
    return base.strftime("%H:%M")


def _duration_text(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60:02d}m"


def search_flights(
    origin: str,
    destination: str,
    date: str,
    passengers: int = 1,
    max_price: float | None = None,
) -> dict:
    """Search synthesized schedules. Returns {flights: [...], count} or {error}."""
    orig = resolve_airport(origin)
    dest = resolve_airport(destination)
    if not orig:
        return {"error": f"Unknown origin {origin!r}"}
    if not dest:
        return {"error": f"Unknown destination {destination!r}"}
    if orig == dest:
        return {"error": "Origin and destination must differ"}
    if not isinstance(passengers, int) or not 1 <= passengers <= 9:
        return {"error": "passengers must be between 1 and 9"}

    d = _parse_date(date)
    if d is None:
        return {"error": f"Invalid date {date!r}; expected YYYY-MM-DD"}

    routes = [r for r in ROUTES if r["origin"] == orig and r["destination"] == dest]
    if not routes:
        return {"flights": [], "count": 0}

    # Deterministic jitter: 2-4 of the route's flights operate on any given date.
    seed = _stable_hash(f"{orig}{dest}{d.isoformat()}")
    jitter = (seed % 1000) / 1000.0  # 0..1
    n_operating = 2 + (seed % (len(routes) - 1)) if len(routes) > 2 else len(routes)

    flights = []
    for i, r in enumerate(routes[:n_operating]):
        # per-flight pseudo-random offsets derived from seed + index
        fseed = _stable_hash(f"{seed}-{i}")
        minute_offset = (fseed % 40) - 20  # ±20 min around the scheduled departure
        price_jitter = 1.0 + (((fseed >> 8) % 500) / 1000.0 - 0.25)  # 0.75x .. 1.25x
        price = round(r["base_price"] * price_jitter, 2)

        flight_id = f"{r['flight_no']}-{d.isoformat()}"
        flights.append({
            "flight_id": flight_id,
            "airline": r["airline"],
            "flight_no": r["flight_no"],
            "origin": orig,
            "destination": dest,
            "date": d.isoformat(),
            "depart": _add_minutes(r["depart"], minute_offset),
            "duration_min": r["duration_min"] + (minute_offset % 15),
            "duration_text": _duration_text(r["duration_min"] + (minute_offset % 15)),
            "price": price,
            "price_per_passenger": price,
            "passengers": passengers,
            "total_price": round(price * passengers, 2),
            "currency": "USD",
        })

    if max_price is not None:
        flights = [f for f in flights if f["price"] <= float(max_price)]

    flights.sort(key=lambda f: f["depart"])
    return {"flights": flights, "count": len(flights)}


def get_flight(flight_id: str) -> dict | None:
    """Look up a single flight by id (ids embed their date)."""
    # flight_id form: <FLIGHTNO>-<YYYY-MM-DD>, e.g. SW100-2026-09-20
    match = re.fullmatch(r"([A-Za-z]+\d+)-(\d{4}-\d{2}-\d{2})", flight_id.strip())
    if not match:
        return None
    flight_part, date_part = match.groups()
    d = _parse_date(date_part)
    if d is None:
        return None
    for r in ROUTES:
        if flight_part.upper() == r["flight_no"].upper():
            result = search_flights(r["origin"], r["destination"], d.isoformat())
            for f in result.get("flights", []):
                if f["flight_id"] == flight_id:
                    return f
    return None
