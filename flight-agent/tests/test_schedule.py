"""Tests for deterministic schedule synthesis."""

from flight_agent.api import data


def test_search_is_deterministic():
    a = data.search_flights("SFO", "JFK", "2026-09-20")
    b = data.search_flights("SFO", "JFK", "2026-09-20")
    assert a == b


def test_search_same_route_different_dates_differ():
    a = data.search_flights("SFO", "JFK", "2026-09-20")
    b = data.search_flights("SFO", "JFK", "2026-09-21")
    assert a["flights"] != b["flights"]


def test_search_validates_passengers():
    for bad in (0, 10, -1):
        result = data.search_flights("SFO", "JFK", "2026-09-20", passengers=bad)
        assert "error" in result


def test_search_validates_dates():
    result = data.search_flights("SFO", "JFK", "09/20/2026")
    assert "error" in result


def test_search_unknown_route_returns_empty():
    result = data.search_flights("SFO", "MIA", "2026-09-20")
    assert result == {"flights": [], "count": 0}


def test_search_unknown_city_is_error():
    result = data.search_flights("Nowhere", "JFK", "2026-09-20")
    assert "error" in result


def test_search_resolves_city_names():
    a = data.search_flights("San Francisco", "New York", "2026-09-20")
    b = data.search_flights("SFO", "JFK", "2026-09-20")
    assert a == b


def test_max_price_filters():
    full = data.search_flights("SFO", "JFK", "2026-09-20")
    capped = data.search_flights("SFO", "JFK", "2026-09-20", max_price=250)
    assert all(f["price"] <= 250 for f in capped["flights"])
    assert len(capped["flights"]) <= len(full["flights"])


def test_flight_ids_embed_date():
    result = data.search_flights("SFO", "JFK", "2026-09-20")
    assert result["count"] >= 1
    for f in result["flights"]:
        assert f["flight_id"].endswith("-2026-09-20")


def test_get_flight_roundtrip():
    result = data.search_flights("SFO", "JFK", "2026-09-20")
    fid = result["flights"][0]["flight_id"]
    assert data.get_flight(fid) == result["flights"][0]


def test_get_flight_unknown():
    assert data.get_flight("NOPE-2026-09-20") is None
    assert data.get_flight("garbage") is None
