import uuid

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_agency_viewer, get_approved_agency, get_current_user, require_roles,
)
from app.models.booking_model import BookingStatus
from app.models.user_model import User, UserRole
from app.schemas.booking_schema import (
    BookingCancel, BookingCreate, BookingOut, CancelPreviewOut, QuoteOut, QuoteRequest,
    TravelerFullOut,
)
from app.services import booking_service

router = APIRouter(prefix="/bookings", tags=["bookings"])
traveler_only = require_roles(UserRole.traveler)


# ---------- Oddiy foydalanuvchi ----------
@router.post("/quote", response_model=QuoteOut)
def quote(data: QuoteRequest, user: User = Depends(traveler_only), db: Session = Depends(get_db)):
    """Narx hisobi. Hech narsani saqlamaydi va joy ushlamaydi."""
    return booking_service.quote(db, data)


@router.post("", response_model=BookingOut, status_code=201)
def create_booking(
    data: BookingCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=80),
    user: User = Depends(traveler_only),
    db: Session = Depends(get_db),
):
    """Joyni 10 daqiqaga ushlaydi (`pending_payment`). Bir xil kalit = bir xil bron."""
    return booking_service.create_booking(db, user, data, idempotency_key)


@router.get("", response_model=list[BookingOut])
def my_bookings(
    status: BookingStatus | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(traveler_only),
    db: Session = Depends(get_db),
):
    return booking_service.list_user_bookings(db, user, status, limit, offset)


# ---------- Agentlik: ko'rish (egasi ham, manager ham) ----------
# "/{booking_id}" dan OLDIN turishi kerak
@router.get("/agency", response_model=list[BookingOut])
def agency_bookings(
    status: BookingStatus | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_agency_viewer),
    db: Session = Depends(get_db),
):
    return booking_service.list_agency_bookings(db, user, status, limit, offset)


@router.get("/{booking_id}", response_model=BookingOut)
def booking_detail(
    booking_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return booking_service.get_booking(db, user, booking_id)


@router.get("/{booking_id}/cancel-preview", response_model=CancelPreviewOut)
def cancel_preview(
    booking_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Bekor qilishdan oldin qancha pul qaytishini ko'rsatadi."""
    return booking_service.cancel_preview(db, user, booking_id)


@router.get("/{booking_id}/travelers", response_model=list[TravelerFullOut])
def booking_travelers(
    booking_id: uuid.UUID,
    user: User = Depends(get_approved_agency),  # faqat manager
    db: Session = Depends(get_db),
):
    return booking_service.traveler_details(db, user, booking_id)


# Traveler o'z bronini, manager agentlik bronini bekor qiladi (service ichida tekshiriladi)
@router.post("/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(
    booking_id: uuid.UUID,
    data: BookingCancel | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return booking_service.cancel_booking(db, user, booking_id, data.reason if data else None)