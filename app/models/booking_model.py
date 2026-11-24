import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, Uuid, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, IdMixin, TimestampMixin
from app.models.tour_model import Departure, Tour
from app.models.user_model import User


class BookingStatus(str, enum.Enum):
    pending_payment = "pending_payment"
    confirmed = "confirmed"
    completed = "completed"
    cancelled = "cancelled"
    expired = "expired"
    refunded = "refunded"


class Booking(Base, IdMixin, TimestampMixin):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("guests > 0", name="ck_booking_guests"),
        Index("ix_bookings_hold", "status", "hold_expires_at"),
    )

    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)

    # Moliyaviy ma'lumot bo'lgani uchun RESTRICT
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    tour_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tours.id", ondelete="RESTRICT"), index=True
    )
    departure_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tour_departures.id", ondelete="RESTRICT"), index=True
    )

    guests: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[int] = mapped_column(BigInteger)       # bron paytidagi 1 kishi narxi
    addons_total: Mapped[int] = mapped_column(BigInteger, default=0)
    total: Mapped[int] = mapped_column(BigInteger)            # unit_price * guests + addons_total

    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus), default=BookingStatus.pending_payment, index=True
    )
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    contact_phone: Mapped[str | None] = mapped_column(String(20))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)

    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[str | None] = mapped_column(String(10))  # traveler | agency
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    refund_percent: Mapped[int | None] = mapped_column(Integer)
    refund_amount: Mapped[int | None] = mapped_column(BigInteger)

    # Bron paytidagi bekor qilish shartlari nusxasi:
    # [{"days_before": 14, "refund_percent": 100}, ...]
    policy_snapshot: Mapped[list] = mapped_column(JSONB, default=list)

    user: Mapped[User] = relationship()
    tour: Mapped[Tour] = relationship()
    departure: Mapped[Departure] = relationship()
    addons: Mapped[list["BookingAddon"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan"
    )
    travelers: Mapped[list["BookingTraveler"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan",
        order_by="BookingTraveler.created_at",
    )


class BookingAddon(Base, IdMixin):
    """Tanlangan qo'shimcha xizmat (narx va nom bron paytida nusxalanadi)."""
    __tablename__ = "booking_addons"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    addon_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tour_addons.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(120))
    unit_price: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(BigInteger)

    booking: Mapped[Booking] = relationship(back_populates="addons")


class BookingTraveler(Base, IdMixin):
    __tablename__ = "booking_travelers"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    first_name: Mapped[str] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(60))
    birth_date: Mapped[date] = mapped_column(Date)
    passport_enc: Mapped[str] = mapped_column(Text)        # Fernet bilan shifrlangan
    passport_mask: Mapped[str] = mapped_column(String(20))  # AB*****67 (ko'rsatish uchun)
    passport_expiry: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    booking: Mapped[Booking] = relationship(back_populates="travelers")


class IdempotencyKey(Base, IdMixin):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    booking_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bookings.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )