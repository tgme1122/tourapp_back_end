import hashlib
import json
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import settings
from app.crypto import decrypt_text, encrypt_text, mask_passport
from app.database import SessionLocal
from app.models.agency_model import AgencyMemberRole
from app.models.booking_model import (
    Booking, BookingAddon, BookingStatus, BookingTraveler, IdempotencyKey,
)
from app.models.notification_model import NotificationType
from app.models.payment_model import Payment, PaymentStatus
from app.models.tour_model import Departure, Tour, TourStatus
from app.models.tour_option_model import TourAddon
from app.models.user_model import User
from app.schemas.booking_schema import (
    BookingAddonOut, BookingCreate, BookingOut, CancelPreviewOut, CustomerOut,
    QuoteOut, QuoteRequest, TravelerFullOut, TravelerMaskedOut,
)
from app.schemas.tour_option_schema import PolicyRule
from app.realtime import manager
from app.services import notification_service, tour_option_service
from app.time_utils import today_uz
from app.services.storage_service import media_url

ACTIVE = (BookingStatus.pending_payment, BookingStatus.confirmed)
PAID = (BookingStatus.confirmed, BookingStatus.completed)
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 0/O, 1/I kabi o'xshashlarsiz
MONTHS = ["Yan", "Fev", "Mar", "Apr", "May", "Iyn", "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"]
EXPIRY_BATCH = 100
IDEMPOTENCY_TTL = timedelta(hours=48)


# ---------- Yordamchilar ----------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Bron topilmadi")


def _end_date(b: Booking) -> date:
    return b.departure.start_date + timedelta(days=b.tour.days - 1)


def _format_range(start: date, end: date) -> str:
    if start == end:
        return f"{start.day} {MONTHS[start.month - 1]} {start.year}"
    if start.year != end.year:
        return (f"{start.day} {MONTHS[start.month - 1]} {start.year} – "
                f"{end.day} {MONTHS[end.month - 1]} {end.year}")
    if start.month != end.month:
        return (f"{start.day} {MONTHS[start.month - 1]} – "
                f"{end.day} {MONTHS[end.month - 1]} {end.year}")
    return f"{start.day}–{end.day} {MONTHS[end.month - 1]} {end.year}"


def _is_agency_member(b: Booking, user: User) -> bool:
    return bool(user.agency_profile and b.tour.agency_id == user.agency_profile.id)


def _select():
    return select(Booking).options(
        joinedload(Booking.tour).selectinload(Tour.images),
        joinedload(Booking.tour).joinedload(Tour.agency),
        joinedload(Booking.departure),
        joinedload(Booking.user),
        selectinload(Booking.addons),
        selectinload(Booking.travelers),
    )


def _load(db: Session, booking_id: uuid.UUID) -> Booking | None:
    return db.scalars(_select().where(Booking.id == booking_id)).first()


def _to_out(b: Booking, with_customer: bool = False) -> BookingOut:
    tour = b.tour
    start, end = b.departure.start_date, _end_date(b)
    return BookingOut(
        id=b.id, code=b.code, tour_id=tour.id, title=tour.title, city=tour.city,
        country=tour.country, agency=tour.agency.name, agency_id=tour.agency_id,
        image=media_url(tour.images[0].path) if tour.images else None,
        dates=_format_range(start, end), start_date=start, end_date=end,
        departure_id=b.departure_id, guests=b.guests, unit_price=b.unit_price,
        addons_total=b.addons_total, total=b.total, status=b.status,
        hold_expires_at=b.hold_expires_at if b.status == BookingStatus.pending_payment else None,
        note=b.note, contact_phone=b.contact_phone, contact_email=b.contact_email,
        cancel_reason=b.cancel_reason, cancelled_by=b.cancelled_by,
        refund_percent=b.refund_percent, refund_amount=b.refund_amount,
        cancellation_policy=[PolicyRule(**r) for r in (b.policy_snapshot or [])],
        addons=[
            BookingAddonOut(addon_id=a.addon_id, name=a.name, unit_price=a.unit_price,
                            quantity=a.quantity, total=a.total)
            for a in b.addons
        ],
        travelers=[
            TravelerMaskedOut(
                id=t.id, first_name=t.first_name, last_name=t.last_name,
                birth_date=t.birth_date, passport_mask=t.passport_mask,
                passport_expiry=t.passport_expiry,
            )
            for t in b.travelers
        ],
        created_at=b.created_at,
        customer=CustomerOut(name=b.user.full_name, phone=b.user.phone, email=b.user.email)
        if with_customer else None,
    )


def _new_code(db: Session) -> str:
    for _ in range(10):
        code = "SY-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if not db.scalar(select(Booking.id).where(Booking.code == code)):
            return code
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Bron kodini yaratib bo'lmadi")


def _transition(db: Session, booking_id: uuid.UUID, from_statuses: tuple, **values) -> bool:
    """Holatni atomik o'zgartiradi. Boshqa so'rov oldin o'zgartirgan bo'lsa False."""
    res = db.execute(
        update(Booking)
        .where(Booking.id == booking_id, Booking.status.in_(from_statuses))
        .values(**values)
    )
    return res.rowcount == 1


def _return_seats(db: Session, departure_id: uuid.UUID, guests: int) -> None:
    db.execute(
        update(Departure)
        .where(Departure.id == departure_id)
        .values(seats_left=Departure.seats_left + guests)
    )


# ---------- Narx hisobi ----------
def _get_bookable(db: Session, tour_id: uuid.UUID, departure_id: uuid.UUID):
    tour = db.get(Tour, tour_id)
    if not tour or tour.status != TourStatus.published or not tour.agency.verified:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tour topilmadi")
    dep = db.get(Departure, departure_id)
    if not dep or dep.tour_id != tour.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Jo'nash topilmadi")
    if dep.start_date <= today_uz():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bu jo'nash sanasiga bron qilib bo'lmaydi")
    return tour, dep


def _price(db: Session, tour: Tour, guests: int, addon_ids: list[uuid.UUID]):
    ids = list(dict.fromkeys(addon_ids))
    lines: list[tuple[TourAddon, int, int]] = []
    if ids:
        found = {
            a.id: a
            for a in db.scalars(
                select(TourAddon).where(
                    TourAddon.tour_id == tour.id,
                    TourAddon.id.in_(ids),
                    TourAddon.is_active.is_(True),
                )
            )
        }
        if len(found) != len(ids):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tanlangan qo'shimcha xizmat mavjud emas")
        for i in ids:
            a = found[i]
            qty = guests if a.per_person else 1
            lines.append((a, qty, a.price * qty))
    base = tour.price * guests
    addons_total = sum(t for _, _, t in lines)
    return base, lines, addons_total, base + addons_total


def quote(db: Session, data: QuoteRequest) -> QuoteOut:
    tour, dep = _get_bookable(db, data.tour_id, data.departure_id)
    base, lines, addons_total, total = _price(db, tour, data.guests, data.addon_ids)
    policy, is_default = tour_option_service.effective_policy(db, tour.id)
    return QuoteOut(
        tour_id=tour.id, departure_id=dep.id, start_date=dep.start_date,
        end_date=dep.start_date + timedelta(days=tour.days - 1),
        guests=data.guests, unit_price=tour.price, base_total=base,
        addons=[BookingAddonOut(addon_id=a.id, name=a.name, unit_price=a.price,
                                quantity=q, total=t) for a, q, t in lines],
        addons_total=addons_total, total=total,
        seats_left=dep.seats_left, available=dep.seats_left >= data.guests,
        hold_minutes=settings.BOOKING_HOLD_MINUTES,
        cancellation_policy=[PolicyRule(**r) for r in policy],
        is_default_policy=is_default,
    )


# ---------- Idempotency ----------
def _request_hash(data: BookingCreate) -> str:
    raw = json.dumps(data.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _find_key(db: Session, user_id: uuid.UUID, key: str) -> IdempotencyKey | None:
    return db.scalars(
        select(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
    ).first()


def _replay(db: Session, record: IdempotencyKey, req_hash: str) -> BookingOut:
    if record.request_hash != req_hash:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Idempotency-Key boshqa so'rov uchun ishlatilgan",
        )
    return _to_out(_load(db, record.booking_id))


# ---------- Yaratish (joyni ushlab turish) ----------
def create_booking(db: Session, user: User, data: BookingCreate, idem_key: str) -> BookingOut:
    req_hash = _request_hash(data)
    existing = _find_key(db, user.id, idem_key)
    if existing:
        return _replay(db, existing, req_hash)

    tour, dep = _get_bookable(db, data.tour_id, data.departure_id)
    end = dep.start_date + timedelta(days=tour.days - 1)
    for i, t in enumerate(data.travelers, 1):
        if t.passport_expiry < end:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{i}-sayohatchi pasporti tur tugaguncha amal qilishi kerak",
            )

    base, lines, addons_total, total = _price(db, tour, data.guests, data.addon_ids)
    policy, _ = tour_option_service.effective_policy(db, tour.id)

    already_paid = db.scalar(
        select(Booking.id).where(
            Booking.user_id == user.id,
            Booking.departure_id == dep.id,
            Booking.status == BookingStatus.confirmed,
        )
    )
    if already_paid:
        raise HTTPException(status.HTTP_409_CONFLICT, "Siz bu jo'nashga allaqachon bron qilgansiz")

    try:
        # Shu odamning shu jo'nashdagi to'lanmagan eski holdi bo'lsa, bo'shatamiz
        stale = db.execute(
            select(Booking.id, Booking.guests).where(
                Booking.user_id == user.id,
                Booking.departure_id == dep.id,
                Booking.status == BookingStatus.pending_payment,
            )
        ).all()
        for sid, sguests in stale:
            if _transition(db, sid, (BookingStatus.pending_payment,),
                           status=BookingStatus.expired, hold_expires_at=None):
                _return_seats(db, dep.id, sguests)

        # Atomik: yetarli joy bo'lsa kamayadi, bo'lmasa 0 qator o'zgaradi
        res = db.execute(
            update(Departure)
            .where(Departure.id == dep.id, Departure.seats_left >= data.guests)
            .values(seats_left=Departure.seats_left - data.guests)
        )
        if res.rowcount == 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "Yetarli bo'sh joy qolmagan")

        booking = Booking(
            code=_new_code(db), user_id=user.id, tour_id=tour.id, departure_id=dep.id,
            guests=data.guests, unit_price=tour.price, addons_total=addons_total, total=total,
            status=BookingStatus.pending_payment,
            hold_expires_at=_now() + timedelta(minutes=settings.BOOKING_HOLD_MINUTES),
            contact_phone=data.contact_phone or user.phone,
            contact_email=str(data.contact_email) if data.contact_email else user.email,
            note=data.note.strip() if data.note else None,
            policy_snapshot=policy,
        )
        booking.addons = [
            BookingAddon(addon_id=a.id, name=a.name, unit_price=a.price, quantity=q, total=t)
            for a, q, t in lines
        ]
        booking.travelers = [
            BookingTraveler(
                first_name=t.first_name, last_name=t.last_name, birth_date=t.birth_date,
                passport_enc=encrypt_text(t.passport_number),
                passport_mask=mask_passport(t.passport_number),
                passport_expiry=t.passport_expiry,
            )
            for t in data.travelers
        ]
        db.add(booking)
        db.flush()
        db.add(IdempotencyKey(
            user_id=user.id, key=idem_key, request_hash=req_hash, booking_id=booking.id
        ))
        notification_service.notify(
            db, user.id, NotificationType.booking, "Joyingiz band qilindi",
            f"«{tour.title}»: joy {settings.BOOKING_HOLD_MINUTES} daqiqaga band qilindi. "
            "To'lovni shu vaqt ichida amalga oshiring",
            "bookings",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_key(db, user.id, idem_key)
        if existing:  # bir vaqtda kelgan bir xil so'rov
            return _replay(db, existing, req_hash)
        raise HTTPException(status.HTTP_409_CONFLICT, "So'rov to'qnashdi, qayta urinib ko'ring")
    except Exception:
        db.rollback()
        raise

    manager.emit_one(user.id, {"type": "booking_update", "bookingId": str(booking.id)})
    manager.emit_one(user.id, {"type": "notification"})
    return _to_out(_load(db, booking.id))


# ---------- O'qish ----------
def complete_finished(db: Session) -> int:
    """Tur tugagan `confirmed` bronlarni `completed` qiladi."""
    finished = (
        select(Departure.id)
        .join(Tour, Tour.id == Departure.tour_id)
        .where(Departure.start_date + (Tour.days - 1) < today_uz())
    )
    res = db.execute(
        update(Booking)
        .where(Booking.status == BookingStatus.confirmed, Booking.departure_id.in_(finished))
        .values(status=BookingStatus.completed)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return res.rowcount


def list_user_bookings(
    db: Session, user: User, status_filter: BookingStatus | None, limit: int, offset: int
) -> list[BookingOut]:
    complete_finished(db)
    stmt = _select().where(Booking.user_id == user.id)
    if status_filter:
        stmt = stmt.where(Booking.status == status_filter)
    else:  # muddati o'tgan holdlar tarixni to'ldirmasin
        stmt = stmt.where(Booking.status != BookingStatus.expired)
    stmt = stmt.order_by(Booking.created_at.desc(), Booking.id).limit(limit).offset(offset)
    return [_to_out(b) for b in db.scalars(stmt)]


def list_agency_bookings(
    db: Session, user: User, status_filter: BookingStatus | None, limit: int, offset: int
) -> list[BookingOut]:
    complete_finished(db)
    stmt = (
        _select()
        .join(Tour, Tour.id == Booking.tour_id)
        .where(
            Tour.agency_id == user.agency_profile.id,
            # to'lanmagan holdlar agentlikka ko'rinmaydi
            Booking.status.notin_((BookingStatus.pending_payment, BookingStatus.expired)),
        )
    )
    if status_filter:
        stmt = stmt.where(Booking.status == status_filter)
    stmt = stmt.order_by(Booking.created_at.desc(), Booking.id).limit(limit).offset(offset)
    return [_to_out(b, with_customer=True) for b in db.scalars(stmt)]


def get_booking(db: Session, user: User, booking_id: uuid.UUID) -> BookingOut:
    complete_finished(db)
    b = _load(db, booking_id)
    if not b:
        raise _not_found()
    traveler = b.user_id == user.id
    agency = _is_agency_member(b, user)
    if not (traveler or agency):
        raise _not_found()  # begona bron mavjudligini oshkor qilmaymiz
    if not traveler and b.status in (BookingStatus.pending_payment, BookingStatus.expired):
        raise _not_found()
    return _to_out(b, with_customer=not traveler)


def traveler_details(db: Session, user: User, booking_id: uuid.UUID) -> list[TravelerFullOut]:
    """To'liq pasport ma'lumoti: faqat agentlik admini, faqat to'langan bronda."""
    b = _load(db, booking_id)
    if not b or not _is_agency_member(b, user):
        raise _not_found()
    if b.status not in PAID:
        raise HTTPException(status.HTTP_409_CONFLICT, "Pasport ma'lumoti faqat to'langan bronda ochiladi")
    return [
        TravelerFullOut(
            id=t.id, first_name=t.first_name, last_name=t.last_name, birth_date=t.birth_date,
            passport_mask=t.passport_mask, passport_expiry=t.passport_expiry,
            passport_number=decrypt_text(t.passport_enc),
        )
        for t in b.travelers
    ]


# ---------- Bekor qilish ----------
def _block_reason(b: Booking, user: User) -> str | None:
    is_traveler = b.user_id == user.id
    is_agency = _is_agency_member(b, user)
    if is_agency and user.agency_role != AgencyMemberRole.manager:
        return "Bronni faqat agentlik admini bekor qila oladi"
    if b.status not in ACTIVE:
        return "Bu bronni bekor qilib bo'lmaydi"
    if is_traveler and b.departure.start_date <= today_uz():
        return "Tur boshlangan, bronni bekor qilib bo'lmaydi"
    if _end_date(b) < today_uz():
        return "Tur yakunlangan, bekor qilib bo'lmaydi"
    return None


def _refund(b: Booking, by: str) -> tuple[int, int]:
    if b.status != BookingStatus.confirmed:  # to'lanmagan: qaytariladigan pul yo'q
        return 0, 0
    if by == "agency":
        pct = 100
    else:
        days_left = (b.departure.start_date - today_uz()).days
        pct = tour_option_service.refund_percent(b.policy_snapshot or [], days_left)
    return pct, b.total * pct // 100


def _party(db: Session, user: User, booking_id: uuid.UUID):
    b = _load(db, booking_id)
    if not b:
        raise _not_found()
    is_traveler = b.user_id == user.id
    is_agency = _is_agency_member(b, user)
    if not (is_traveler or is_agency):
        raise _not_found()
    if is_agency and b.status in (BookingStatus.pending_payment, BookingStatus.expired):
        raise _not_found()
    return b, is_traveler


def cancel_preview(db: Session, user: User, booking_id: uuid.UUID) -> CancelPreviewOut:
    b, is_traveler = _party(db, user, booking_id)
    reason = _block_reason(b, user)
    pct, amount = _refund(b, "traveler" if is_traveler else "agency")
    return CancelPreviewOut(
        can_cancel=reason is None, reason=reason,
        paid=b.status == BookingStatus.confirmed,
        refund_percent=pct, refund_amount=amount,
    )


def cancel_booking(
    db: Session, user: User, booking_id: uuid.UUID, reason: str | None
) -> BookingOut:
    b, is_traveler = _party(db, user, booking_id)
    blocked = _block_reason(b, user)
    if blocked:
        code = status.HTTP_403_FORBIDDEN if "admini" in blocked else status.HTTP_409_CONFLICT
        if "boshlangan" in blocked:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, blocked)

    by = "traveler" if is_traveler else "agency"
    was_confirmed = b.status == BookingStatus.confirmed
    pct, amount = _refund(b, by)
    guests, departure_id, tour_id = b.guests, b.departure_id, b.tour_id
    title, code, tour_agency_id, owner_id = b.tour.title, b.code, b.tour.agency_id, b.user_id
    customer = b.user.full_name
    clean_reason = reason.strip() if reason else None

    try:
        if not _transition(
            db, b.id, (b.status,),
            status=BookingStatus.cancelled, cancelled_at=_now(), cancelled_by=by,
            cancel_reason=clean_reason, hold_expires_at=None,
            refund_percent=pct if was_confirmed else None,
            refund_amount=amount if was_confirmed else None,
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, "Bron holati o'zgargan, qayta urinib ko'ring")

        _return_seats(db, departure_id, guests)

        if was_confirmed:
            db.execute(
                update(Tour).where(Tour.id == tour_id)
                .values(bookings_count=func.greatest(Tour.bookings_count - 1, 0))
            )
            if amount > 0:
                db.execute(
                    update(Payment)
                    .where(Payment.booking_id == b.id, Payment.status == PaymentStatus.paid)
                    .values(status=PaymentStatus.refund_required)
                )

        refund_text = f" Qaytariladigan summa: {amount:,} so'm ({pct}%).".replace(",", " ") if amount else ""
        if is_traveler:
            if was_confirmed:  # agentlik faqat to'langan bron bekor bo'lganini biladi
                notification_service.notify_agency(
                    db, tour_agency_id, NotificationType.booking, "Bron bekor qilindi",
                    f"{customer} {code} bronini bekor qildi", "bookings",
                )
            notification_service.notify(
                db, owner_id, NotificationType.booking, "Bron bekor qilindi",
                f"«{title}» ({code}) bekor qilindi.{refund_text}", "bookings",
            )
        else:
            extra = f" Sabab: {clean_reason}." if clean_reason else ""
            notification_service.notify(
                db, owner_id, NotificationType.booking, "Bron bekor qilindi",
                f"«{title}» ({code}) agentlik tomonidan bekor qilindi.{extra}{refund_text}",
                "bookings",
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    targets = [owner_id]
    if is_traveler and was_confirmed:
        targets.extend(notification_service.agency_recipient_ids(db, tour_agency_id))
    manager.emit(targets, {"type": "booking_update", "bookingId": str(booking_id)})
    manager.emit(targets, {"type": "notification"})
    return _to_out(_load(db, booking_id), with_customer=not is_traveler)


# ---------- Muddati o'tgan holdlar (fon vazifa) ----------
def expire_overdue(db: Session, batch: int = EXPIRY_BATCH) -> int:
    """Muddati o'tgan to'lanmagan bronlarni `expired` qiladi va joyni qaytaradi."""
    rows = db.scalars(
        select(Booking)
        .where(
            Booking.status == BookingStatus.pending_payment,
            Booking.hold_expires_at < _now(),
        )
        .order_by(Booking.hold_expires_at)
        .limit(batch)
        .with_for_update(skip_locked=True)  # bir nechta server bir vaqtda ishlasa ham xavfsiz
    ).all()
    for b in rows:
        b.status = BookingStatus.expired
        b.hold_expires_at = None
        _return_seats(db, b.departure_id, b.guests)
        notification_service.notify(
            db, b.user_id, NotificationType.booking, "Bron muddati tugadi",
            f"«{b.tour.title}» ({b.code}): to'lov vaqtida amalga oshirilmadi, joy qaytarildi",
            "bookings",
        )
    expired_user_ids = [b.user_id for b in rows]
    db.commit()
    if expired_user_ids:
        manager.emit(expired_user_ids, {"type": "booking_update"})
        manager.emit(expired_user_ids, {"type": "notification"})
    return len(rows)


def run_maintenance() -> None:
    db = SessionLocal()
    try:
        while expire_overdue(db) >= EXPIRY_BATCH:
            pass
        complete_finished(db)
        db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < _now() - IDEMPOTENCY_TTL))
        db.commit()
    finally:
        db.close()


# ---------- Sharh uchun ----------
def has_finished_booking(db: Session, user_id: uuid.UUID, tour_id: uuid.UUID) -> bool:
    bookings = db.scalars(
        _select().where(
            Booking.user_id == user_id,
            Booking.tour_id == tour_id,
            Booking.status.in_(PAID),
        )
    )
    today = today_uz()
    return any(_end_date(b) < today for b in bookings)