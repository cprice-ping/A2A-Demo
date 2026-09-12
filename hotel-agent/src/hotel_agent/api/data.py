"""Representative hotel data: cities, properties, and search/enrichment logic."""

from __future__ import annotations

import datetime as dt

# Cities the hotel agent serves — deliberately the same set as the flight
# agent's destinations so planner trips can always pair a flight with lodging.
CITIES: list[dict] = [
    {"code": "NYC", "name": "New York"},
    {"code": "LAX", "name": "Los Angeles"},
    {"code": "MIA", "name": "Miami"},
    {"code": "LHR", "name": "London"},
    {"code": "SFO", "name": "San Francisco"},
    {"code": "ORD", "name": "Chicago"},
]

CITY_CODES = {c["code"] for c in CITIES}

# City aliases (lowercased) -> code
CITY_TO_CODE = {
    "new york": "NYC",
    "nyc": "NYC",
    "los angeles": "LAX",
    "miami": "MIA",
    "london": "LHR",
    "san francisco": "SFO",
    "chicago": "ORD",
}

PROPERTIES: list[dict] = [
    {
        "hotel_id": "NYC-HARBOR",
        "name": "Harbor View Inn",
        "city": "NYC",
        "stars": 3,
        "price_per_night": 189.00,
        "amenities": ["WiFi", "Gym", "Breakfast"],
        "description": "Comfortable mid-range hotel near Battery Park with views of the harbor.",
    },
    {
        "hotel_id": "NYC-MIDTOWN",
        "name": "Midtown Grand",
        "city": "NYC",
        "stars": 4,
        "price_per_night": 299.00,
        "amenities": ["WiFi", "Spa", "Restaurant", "Gym"],
        "description": "Upscale tower steps from Times Square with rooftop bar.",
    },
    {
        "hotel_id": "LAX-AIRPORT",
        "name": "Airport Hotel LA",
        "city": "LAX",
        "stars": 3,
        "price_per_night": 159.00,
        "amenities": ["WiFi", "Shuttle", "Breakfast"],
        "description": "Reliable stay two miles from LAX with free shuttle.",
    },
    {
        "hotel_id": "LAX-MARINA",
        "name": "Marina Bay Suites",
        "city": "LAX",
        "stars": 4,
        "price_per_night": 279.00,
        "amenities": ["WiFi", "Pool", "Spa", "Parking"],
        "description": "All-suite hotel overlooking Marina del Rey.",
    },
    {
        "hotel_id": "MIA-SOBE",
        "name": "South Beach Resort",
        "city": "MIA",
        "stars": 4,
        "price_per_night": 249.00,
        "amenities": ["WiFi", "Pool", "Beach", "Restaurant"],
        "description": "Beachfront art-deco classic in the heart of South Beach.",
    },
    {
        "hotel_id": "LHR-CENTRAL",
        "name": "London Central",
        "city": "LHR",
        "stars": 3,
        "price_per_night": 220.00,
        "amenities": ["WiFi", "Breakfast", "Bar"],
        "description": "Victorian townhouse hotel a short walk from Hyde Park.",
    },
    {
        "hotel_id": "SFO-GOLDENGATE",
        "name": "Golden Gate Inn",
        "city": "SFO",
        "stars": 3,
        "price_per_night": 209.00,
        "amenities": ["WiFi", "Breakfast", "Gym"],
        "description": "Boutique inn in Nob Hill with bay views.",
    },
    {
        "hotel_id": "ORD-LOOP",
        "name": "Loop Business Hotel",
        "city": "ORD",
        "stars": 3,
        "price_per_night": 179.00,
        "amenities": ["WiFi", "Business Center", "Restaurant"],
        "description": "No-nonsense business hotel in the Loop, steps from the L.",
    },
]

DATE_FORMAT = "%Y-%m-%d"


def resolve_city(value: str) -> str | None:
    v = (value or "").strip().upper()
    if v in CITY_CODES:
        return v
    return CITY_TO_CODE.get((value or "").strip().lower())


def _parse_date(date: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(date, DATE_FORMAT).date()
    except (TypeError, ValueError):
        return None


def search_hotels(
    city: str,
    check_in: str | None = None,
    check_out: str | None = None,
    guests: int = 1,
    max_price_per_night: float | None = None,
) -> dict:
    """Search properties in a city, enriched with nights/total when dates given."""
    code = resolve_city(city)
    if not code:
        return {"error": f"Unknown city {city!r}"}
    if not isinstance(guests, int) or not 1 <= guests <= 20:
        return {"error": "guests must be between 1 and 20"}

    nights = None
    if check_in or check_out:
        if not check_in or not check_out:
            return {"error": "Provide both check_in and check_out, or neither"}
        ci = _parse_date(check_in)
        co = _parse_date(check_out)
        if ci is None or co is None:
            return {"error": f"Invalid dates; expected YYYY-MM-DD (got {check_in!r}, {check_out!r})"}
        nights = (co - ci).days
        if nights <= 0:
            return {"error": "check_out must be after check_in"}

    results = []
    for p in PROPERTIES:
        if p["city"] != code:
            continue
        if max_price_per_night is not None and p["price_per_night"] > float(max_price_per_night):
            continue
        h = dict(p)
        h["guests"] = guests
        if nights is not None:
            h["check_in"] = ci.isoformat()
            h["check_out"] = co.isoformat()
            h["nights"] = nights
            h["total_price"] = round(p["price_per_night"] * nights, 2)
        results.append(h)

    return {"hotels": results, "count": len(results)}


def get_hotel(hotel_id: str) -> dict | None:
    for p in PROPERTIES:
        if p["hotel_id"] == hotel_id:
            return dict(p)
    return None
