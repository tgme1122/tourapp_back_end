import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.booking_model import Booking, BookingStatus
from app.models.notification_model import NotificationType
from app.models.payment_model import Payment, PaymentProvider, PaymentStatus
from app.models.tour_model import Departure, Tour
from app.models.user_model import User
from app.realtime import manager
from app.schemas.payment_schema import PaymentOut
from app.services import notification_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pay_url(payment: Payment) -> str | None:
    # TODO (Click/Payme qadamida): provayder bo'yicha to'lov havolasini yasash
    return None


def _out(p: Payment, expires_at: datetime | None = None) -> PaymentOut:
    return PaymentOut(
        id=p.id, booking_id=p.booking_id, provider=p.provider, amount=p.amount,
        status=p.status, pay_url=_pay_url(p), expires_at=expires_at,
    )


def create_payment(
    db: Session, user: User, booking_id: uuid.UUID, provider: PaymentProvider
) -> PaymentOut:
    b = db.get(Booking, booking_id)
    if not b or b.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bron topilmadi")
    if b.status != BookingStatus.pending_payment:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu bron uchun to'lov qilib bo'lmaydi")
    if b.hold_expires_at and b.hold_expires_at < _now():
        raise HTTPException(status.HTTP_410_GONE, "Bron muddati tugagan, qaytadan bron qiling")

    payment = db.scalars(
        select(Payment).where(
            Payment.booking_id == b.id,
            Payment.provider == provider,
            Payment.status == PaymentStatus.created,
        )
    ).first()
    if not payment:
        payment = Payment(booking_id=b.id, user_id=user.id, provider=provider, amount=b.total)
        db.add(payment)
        db.commit()
        db.refresh(payment)
    return _out(payment, b.hold_expires_at)


def get_payment(db: Session, user: User, payment_id: uuid.UUID) -> PaymentOut:
    p = db.get(Payment, payment_id)
    if not p or p.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "To'lov topilmadi")
    b = db.get(Booking, p.booking_id)
    return _out(p, b.hold_expires_at if b else None)


def mark_paid(db: Session, payment_id: uuid.UUID, external_id: str | None = None) -> Payment:
    """To'lov o'tdi. Click/Payme webhooklari shu funksiyani chaqiradi (idempotent)."""
    payment = db.scalars(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    ).first()
    if not payment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "To'lov topilmadi")
    if payment.status in (PaymentStatus.paid, PaymentStatus.refund_required, PaymentStatus.refunded):
        return payment  # qayta kelgan webhook

    booking = db.scalars(
        select(Booking).where(Booking.id == payment.booking_id).with_for_update()
    ).first()

    ok = False
    if booking.status == BookingStatus.pending_payment:
        ok = True
    elif booking.status == BookingStatus.expired:
        # Hold tugagan, lekin pul keldi: joy hali bo'sh bo'lsa, qayta olamiz
        res = db.execute(
            update(Departure)
            .where(Departure.id == booking.departure_id, Departure.seats_left >= booking.guests)
            .values(seats_left=Departure.seats_left - booking.guests)
        )
        ok = res.rowcount == 1

    tour = db.get(Tour, booking.tour_id)
    payment.external_id = external_id or payment.external_id
    payment.paid_at = _now()

    if ok:
        payment.status = PaymentStatus.paid
        booking.status = BookingStatus.confirmed
        booking.confirmed_at = _now()
        booking.hold_expires_at = None
        db.execute(
            update(Tour).where(Tour.id == tour.id).values(bookings_count=Tour.bookings_count + 1)
        )
        notification_service.notify(
            db, booking.user_id, NotificationType.booking, "To'lov muvaffaqiyatli",
            f"«{tour.title}» ({booking.code}) bronи tasdiqlandi".replace("bronи", "broni"),
            "bookings",
        )
        notification_service.notify_agency(
            db, tour.agency_id, NotificationType.booking, "Yangi bron",
            f"{booking.user.full_name} «{tour.title}» turiga {booking.guests} kishilik "
            f"bron qildi ({booking.code})",
            "bookings",
        )
    else:
        # Bron bekor/boshqa holatda: pulni qaytarish kerak
        payment.status = PaymentStatus.refund_required
        notification_service.notify(
            db, booking.user_id, NotificationType.booking, "To'lov qaytariladi",
            f"({booking.code}) bron tasdiqlanmadi, to'lagan pulingiz qaytariladi".replace("broni", "broni"),
            "bookings",
        )
    booking_id = booking.id
    traveler_id = booking.user_id
    agency_ids = notification_service.agency_recipient_ids(db, tour.agency_id) if ok else []
    db.commit()
    db.refresh(payment)
    targets = [traveler_id, *agency_ids]
    manager.emit(targets, {"type": "booking_update", "bookingId": str(booking_id)})
    manager.emit(targets, {"type": "notification"})
    return payment