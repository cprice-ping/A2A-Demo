"""REST API for the hotel domain (mounted at /api)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import store
from . import data

router = APIRouter()


class BookHotelRequest(BaseModel):
    hotel_id: str
    check_in: str
    check_out: str
    guests: int = 1


@router.get("/health")
def health() -> dict:
    return {"ok": True, "service": "hotel-agent"}


@router.get("/cities")
def list_cities() -> dict:
    return {"cities": data.CITIES, "count": len(data.CITIES)}


@router.get("/hotels/search")
def search_hotels(
    city: str,
    check_in: str | None = None,
    check_out: str | None = None,
    guests: int = 1,
    max_price_per_night: float | None = None,
) -> dict:
    result = data.search_hotels(
        city,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        max_price_per_night=max_price_per_night,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/hotels/book")
def book_hotel(req: BookHotelRequest) -> dict:
    hotel = data.get_hotel(req.hotel_id)
    if not hotel:
        raise HTTPException(status_code=404, detail=f"Unknown hotel_id {req.hotel_id!r}")
    try:
        booking = store.create_hotel_booking(hotel, req.check_in, req.check_out, req.guests)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"booking": booking}


@router.get("/bookings/{booking_id}")
def get_booking(booking_id: str) -> dict:
    booking = store.get_hotel_booking(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail=f"Unknown booking_id {booking_id!r}")
    return {"booking": booking}
