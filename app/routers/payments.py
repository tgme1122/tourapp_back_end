import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import require_roles
from app.models.payment_model import Payment
from app.models.user_model import User, UserRole
from app.schemas.payment_schema import PaymentCreate, PaymentOut
from app.services import payment_service

router = APIRouter(prefix="/payments", tags=["payments"])
traveler_only = require_roles(UserRole.traveler)


@router.post("", response_model=PaymentOut, status_code=201)
def create_payment(
    data: PaymentCreate, user: User = Depends(traveler_only), db: Session = Depends(get_db)
):
    """Click/Payme tanlanganda chaqiriladi. `payUrl` provayder ulangach to'ldiriladi."""
    return payment_service.create_payment(db, user, data.booking_id, data.provider)


@router.get("/{payment_id}", response_model=PaymentOut)
def get_payment(
    payment_id: uuid.UUID, user: User = Depends(traveler_only), db: Session = Depends(get_db)
):
    """To'lovdan qaytgach frontend holatni shu yo'l bilan tekshiradi."""
    return payment_service.get_payment(db, user, payment_id)


@router.post("/{payment_id}/simulate-success", response_model=PaymentOut)
def simulate_success(
    payment_id: uuid.UUID, user: User = Depends(traveler_only), db: Session = Depends(get_db)
):
    """FAQAT TEST: haqiqiy to'lovsiz bronni tasdiqlaydi (PAYMENT_SIMULATION=true)."""
    if not settings.PAYMENT_SIMULATION:
        raise HTTPException(404, "Not Found")
    payment_service.get_payment(db, user, payment_id)  # egasini tekshiradi
    payment_service.mark_paid(db, payment_id, external_id=f"SIM-{uuid.uuid4().hex[:12]}")
    return payment_service.get_payment(db, user, payment_id)