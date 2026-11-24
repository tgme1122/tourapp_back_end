import uuid
from datetime import datetime

from app.models.payment_model import PaymentProvider, PaymentStatus
from app.schemas.base import CamelModel


class PaymentCreate(CamelModel):
    booking_id: uuid.UUID
    provider: PaymentProvider


class PaymentOut(CamelModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    provider: PaymentProvider
    amount: int
    status: PaymentStatus
    pay_url: str | None = None      # Click/Payme ulangach to'ldiriladi
    expires_at: datetime | None = None