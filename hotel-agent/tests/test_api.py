"""Tests for the hotel data layer and REST API."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hotel_agent.api import data
from hotel_agent.api.routes import router


# --- data layer ---

def test_search_is_city_alias_agnostic():
    a = data.search_hotels("New York")
    b = data.search_hotels("NYC")
    assert a == b
    assert a["count"] == 2


def test_search_validates_dates():
    r = data.search_hotels("NYC", check_in="2026-09-20")
    assert "error" in r
    r = data.search_hotels("NYC", check_in="2026-09-20", check_out="2026-09-19")
    assert "error" in r
    r = data.search_hotels("NYC", check_in="09/20/2026", check_out="2026-09-22")
    assert "error" in r


def test_search_enriches_nights_and_total():
    r = data.search_hotels("NYC", check_in="2026-09-20", check_out="2026-09-22")
    for h in r["hotels"]:
        assert h["nights"] == 2
        assert h["total_price"] == pytest.approx(h["price_per_night"] * 2)
        assert "check_in" in h and "check_out" in h


def test_search_without_dates_has_no_total():
    r = data.search_hotels("NYC")
    for h in r["hotels"]:
        assert "nights" not in h and "total_price" not in h


def test_max_price_per_night_filters():
    r = data.search_hotels("NYC", max_price_per_night=200)
    assert r["count"] == 1
    assert r["hotels"][0]["hotel_id"] == "NYC-HARBOR"


def test_unknown_city():
    assert "error" in data.search_hotels("Atlantis")


def test_guests_validation():
    assert "error" in data.search_hotels("NYC", guests=0)
    assert "error" in data.search_hotels("NYC", guests=21)


# --- REST API ---

@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "service": "hotel-agent"}


def test_book_and_get_roundtrip(client):
    r = client.post(
        "/api/hotels/book",
        json={"hotel_id": "NYC-HARBOR", "check_in": "2026-09-20", "check_out": "2026-09-22", "guests": 2},
    )
    assert r.status_code == 200
    booking = r.json()["booking"]
    assert booking["booking_id"].startswith("HB-")
    assert booking["status"] == "CONFIRMED"
    assert booking["nights"] == 2
    assert booking["total"] == pytest.approx(189.00 * 2)

    r = client.get(f"/api/bookings/{booking['booking_id']}")
    assert r.status_code == 200
    assert r.json()["booking"]["booking_id"] == booking["booking_id"]


def test_book_unknown_hotel(client):
    r = client.post("/api/hotels/book", json={"hotel_id": "NOPE", "check_in": "2026-09-20", "check_out": "2026-09-22"})
    assert r.status_code == 404


def test_book_bad_range(client):
    r = client.post("/api/hotels/book", json={"hotel_id": "NYC-HARBOR", "check_in": "2026-09-22", "check_out": "2026-09-20"})
    assert r.status_code == 400
