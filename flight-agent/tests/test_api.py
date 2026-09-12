"""Tests for the REST API layer (mounted standalone — no agent stack needed)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from flight_agent.api.routes import router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "service": "flight-agent"}


def test_airports(client):
    r = client.get("/api/airports")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 6
    codes = {a["code"] for a in body["airports"]}
    assert {"SFO", "LAX", "JFK", "ORD", "MIA", "LHR"} == codes


def test_search_shape(client):
    r = client.get("/api/flights/search", params={"origin": "SFO", "destination": "JFK", "date": "2026-09-20"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(body["flights"]) >= 1
    f = body["flights"][0]
    for key in ("flight_id", "airline", "flight_no", "origin", "destination", "date", "depart", "price", "total_price"):
        assert key in f


def test_search_bad_params(client):
    r = client.get("/api/flights/search", params={"origin": "SFO", "destination": "JFK", "date": "bad"})
    assert r.status_code == 400


def test_book_and_get_roundtrip(client):
    r = client.get("/api/flights/search", params={"origin": "SFO", "destination": "JFK", "date": "2026-09-20"})
    fid = r.json()["flights"][0]["flight_id"]

    r = client.post("/api/flights/book", json={"flight_id": fid, "passengers": 2})
    assert r.status_code == 200
    booking = r.json()["booking"]
    assert booking["booking_id"].startswith("BK-")
    assert booking["status"] == "CONFIRMED"
    assert booking["passengers"] == 2
    assert booking["total"] == pytest.approx(booking["price_per_passenger"] * 2)

    r = client.get(f"/api/bookings/{booking['booking_id']}")
    assert r.status_code == 200
    assert r.json()["booking"]["booking_id"] == booking["booking_id"]


def test_book_unknown_flight(client):
    r = client.post("/api/flights/book", json={"flight_id": "NOPE-2026-09-20", "passengers": 1})
    assert r.status_code == 404


def test_book_bad_passengers(client):
    r = client.post("/api/flights/book", json={"flight_id": "SW100-2026-09-20", "passengers": 0})
    assert r.status_code == 400


def test_get_unknown_booking(client):
    r = client.get("/api/bookings/BK-NOPE00")
    assert r.status_code == 404
