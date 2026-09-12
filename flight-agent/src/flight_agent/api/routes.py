"""REST API layer for the flight domain (mounted at /api)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import store
from . import data

router = APIRouter()


class BookFlightRequest(BaseModel):
    flight_id: str
    passengers: int = 1


@router.get("/health")
def health() -> dict:
    return {"ok": True, "service": "flight-agent"}


@router.get("/airports")
def list_airports() -> dict:
    return {"airports": data.AIRPORTS, "count": len(data.AIRPORTS)}


@router.get("/flights/search")
def search_flights(
    origin: str,
    destination: str,
    date: str,
    passengers: int = 1,
    max_price: float | None = None,
) -> dict:
    result = data.search_flights(origin, destination, date, passengers=passengers, max_price=max_price)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/flights/book")
def book_flight(req: BookFlightRequest) -> dict:
    flight = data.get_flight(req.flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail=f"Unknown flight_id {req.flight_id!r}")
    if not 1 <= req.passengers <= 9:
        raise HTTPException(status_code=400, detail="passengers must be between 1 and 9")
    booking = store.create_flight_booking(flight, req.passengers)
    return {"booking": booking}


@router.get("/bookings/{booking_id}")
def get_booking(booking_id: str) -> dict:
    booking = store.get_flight_booking(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail=f"Unknown booking_id {booking_id!r}")
    return {"booking": booking}
