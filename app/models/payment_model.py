import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, IdMixin, TimestampMixin


class PaymentProvider(str, enum.Enum):
    click = "click"
    payme = "payme"


class PaymentStatus(str, enum.Enum):
    created = "created"                  # havola berildi, to'lov kutilmoqda
    paid = "paid"
    failed = "failed"
    refund_required = "refund_required"  # pul qaytarilishi kerak
    refunded = "refunded"


class Payment(Base, IdMixin, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_payment_external"),)

    booking_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bookings.id", ondelete="RESTRICT"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    provider: Mapped[PaymentProvider] = mapped_column(Enum(PaymentProvider))
    amount: Mapped[int] = mapped_column(BigInteger)  # so'm
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), default=PaymentStatus.created, index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(100))  # Click/Payme tranzaksiya ID
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))