import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.agency_model import AgencyMember
from app.models.notification_model import Notification, NotificationType
from app.models.tour_model import SavedTour, Tour
from app.models.user_model import User, UserRole
from app.realtime import manager
from app.schemas.notification_schema import NotificationOut, NotificationTargetOut
from app.time_utils import UZ_TZ, today_uz


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


# ---------- Yaratish (commit CHAQIRUVCHIDA) ----------
def notify(
    db: Session,
    user_id: uuid.UUID,
    type_: NotificationType,
    title: str,
    text: str,
    target_kind: str | None = None,
    target_id: uuid.UUID | None = None,
) -> Notification:
    n = Notification(
        user_id=user_id, type=type_, title=title[:200], text=text[:500],
        target_kind=target_kind, target_id=target_id,
    )
    db.add(n)
    return n


def notify_many(
    db: Session,
    user_ids: list[uuid.UUID],
    type_: NotificationType,
    title: str,
    text: str,
    target_kind: str | None = None,
    target_id: uuid.UUID | None = None,
) -> int:
    for uid in user_ids:
        notify(db, uid, type_, title, text, target_kind, target_id)
    return len(user_ids)


def agency_recipient_ids(db: Session, agency_id: uuid.UUID) -> list[uuid.UUID]:
    """Agentlikning barcha faol xodimlari (egasi va managerlar)."""
    return list(
        db.scalars(
            select(AgencyMember.user_id)
            .join(User, User.id == AgencyMember.user_id)
            .where(AgencyMember.agency_id == agency_id, User.is_active.is_(True))
        )
    )


def notify_agency(
    db: Session,
    agency_id: uuid.UUID,
    type_: NotificationType,
    title: str,
    text: str,
    target_kind: str | None = None,
    target_id: uuid.UUID | None = None,
) -> int:
    return notify_many(
        db, agency_recipient_ids(db, agency_id), type_, title, text, target_kind, target_id
    )


def notify_new_message(
    db: Session,
    recipient_id: uuid.UUID,
    sender_name: str,
    conversation_id: uuid.UUID,
    text: str,
    from_agency: bool,
) -> None:
    # Foydalanuvchi agentlik xabarlarini o'chirib qo'ygan bo'lsa
    if from_agency:
        recipient = db.get(User, recipient_id)
        if not recipient or not recipient.agency_messages_enabled:
            return

    preview = text if len(text) <= 120 else text[:117] + "..."

    # Shu suhbat bo'yicha o'qilmagan bildirishnoma bor bo'lsa, yangilaymiz
    existing = db.scalars(
        select(Notification).where(
            Notification.user_id == recipient_id,
            Notification.type == NotificationType.message,
            Notification.target_kind == "chat",
            Notification.target_id == conversation_id,
            Notification.read_at.is_(None),
        )
    ).first()
    if existing:
        existing.title = sender_name[:200]
        existing.text = preview
        existing.created_at = _now()
        return

    notify(db, recipient_id, NotificationType.message, sender_name, preview,
           "chat", conversation_id)


def price_drop_recipient_ids(db: Session, tour_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(SavedTour.user_id)
            .join(User, User.id == SavedTour.user_id)
            .where(
                SavedTour.tour_id == tour_id,
                User.price_drop_enabled.is_(True),
                User.is_active.is_(True),
            )
        )
    )


def notify_price_drop(db: Session, tour: Tour, previous_price: int) -> int:
    user_ids = price_drop_recipient_ids(db, tour.id)
    return notify_many(
        db, user_ids, NotificationType.price_drop,
        "Narx tushdi",
        f"{tour.title}: {_money(previous_price)} so'mdan {_money(tour.price)} so'mgacha",
        "tour", tour.id,
    )


def broadcast_promo(
    db: Session, title: str, text: str, target_tour_id: uuid.UUID | None = None
) -> int:
    """Admin qismida ishlatiladi: barcha faol oddiy foydalanuvchilarga."""
    user_ids = list(
        db.scalars(
            select(User.id).where(User.role == UserRole.traveler, User.is_active.is_(True))
        )
    )
    n = notify_many(
        db, user_ids, NotificationType.promo, title, text,
        "tour" if target_tour_id else None, target_tour_id,
    )
    db.commit()
    manager.emit(user_ids, {"type": "notification"})
    return n


# ---------- O'qish ----------
def _day_label(created_at: datetime) -> str:
    diff = (today_uz() - created_at.astimezone(UZ_TZ).date()).days
    if diff <= 0:
        return "Bugun"
    return "Kecha" if diff == 1 else "Avvalroq"


def _to_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        type=n.type,
        title=n.title,
        text=n.text,
        time=n.created_at,
        day=_day_label(n.created_at),
        read=n.read_at is not None,
        target=NotificationTargetOut(kind=n.target_kind, id=n.target_id)
        if n.target_kind
        else None,
    )


def list_notifications(
    db: Session, user: User, unread_only: bool, limit: int, offset: int
) -> list[NotificationOut]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id).limit(limit).offset(offset)
    return [_to_out(n) for n in db.scalars(stmt)]


def unread_count(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    ) or 0


# ---------- O'zgartirish ----------
def mark_read(db: Session, user: User, notification_id: uuid.UUID) -> None:
    exists = db.scalar(
        select(Notification.id).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bildirishnoma topilmadi")
    db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.read_at.is_(None))
        .values(read_at=_now())
    )
    db.commit()
    manager.emit_one(user.id, {"type": "notifications_sync"})


def mark_all_read(db: Session, user: User) -> None:
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=_now())
    )
    db.commit()
    manager.emit_one(user.id, {"type": "notifications_sync"})


def delete_notification(db: Session, user: User, notification_id: uuid.UUID) -> None:
    res = db.execute(
        delete(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if res.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bildirishnoma topilmadi")
    db.commit()
    manager.emit_one(user.id, {"type": "notifications_sync"})