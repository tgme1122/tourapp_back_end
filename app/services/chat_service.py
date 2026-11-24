import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models.agency_model import AgencyMember, AgencyMemberRole
from app.models.chat_model import Conversation, Message, MessageType
from app.models.notification_model import Notification, NotificationType
from app.models.tour_model import Tour, TourStatus
from app.models.user_model import User
from app.realtime import manager
from app.schemas.chat_schema import AttachmentOut, ConversationOut, MessageOut
from app.security import create_chat_ticket, verify_chat_ticket
from app.services import notification_service
from app.services.storage_service import delete_file, private_file, save_chat_attachment


# ---------- Yordamchilar ----------
def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Suhbat topilmadi")


def _initials(name: str) -> str:
    return "".join(p[0] for p in name.split()[:2]).upper() or "?"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _side(conv: Conversation, user: User) -> str | None:
    if conv.user_id == user.id:
        return "traveler"
    if user.agency_profile and conv.agency_id == user.agency_profile.id:
        return "agency"
    return None


def _is_manager(user: User) -> bool:
    return user.agency_role == AgencyMemberRole.manager


def _participant_filter(user: User):
    """Foydalanuvchi qatnashadigan suhbatlar sharti."""
    if user.agency_profile:
        return Conversation.agency_id == user.agency_profile.id
    return Conversation.user_id == user.id


def _select():
    return select(Conversation).options(
        joinedload(Conversation.user),
        joinedload(Conversation.agency),
        joinedload(Conversation.tour),
    )


def _get_conv(db: Session, user: User, conv_id: uuid.UUID) -> tuple[Conversation, str]:
    conv = db.scalars(_select().where(Conversation.id == conv_id)).first()
    side = _side(conv, user) if conv else None
    if not conv or not side:
        raise _not_found()  # begona suhbat mavjudligini oshkor qilmaymiz
    return conv, side


def _unread_map(db: Session, user: User, conv_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not conv_ids:
        return {}
    rows = db.execute(
        select(Message.conversation_id, func.count(Message.id))
        .where(
            Message.conversation_id.in_(conv_ids),
            Message.sender_id != user.id,
            Message.read_at.is_(None),
        )
        .group_by(Message.conversation_id)
    )
    return {cid: cnt for cid, cnt in rows}


def _online_agencies(db: Session, agency_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not agency_ids:
        return set()
    rows = db.execute(
        select(AgencyMember.agency_id, AgencyMember.user_id).where(
            AgencyMember.agency_id.in_(agency_ids)
        )
    )
    return {aid for aid, uid in rows if manager.is_online(uid)}


def _to_out(conv: Conversation, side: str, unread: int, *, online: bool) -> ConversationOut:
    if side == "traveler":
        name, verified = conv.agency.name, conv.agency.verified
    else:
        name, verified = conv.user.full_name, False
    return ConversationOut(
        id=conv.id,
        agency=name,
        initials=_initials(name),
        verified=verified,
        online=online,
        tour_id=conv.tour_id,
        tour_title=conv.tour.title,
        last_message=conv.last_message_text or "",
        time=conv.last_message_at or conv.created_at,
        unread=unread,
    )


def _preview_label(
    msg_type: MessageType,
    text: str | None,
    duration_sec: int | None = None,
    att_name: str | None = None,
) -> str:
    clean = (text or "").strip()
    if clean:
        return clean
    if msg_type == MessageType.image:
        return "📷 Rasm"
    if msg_type == MessageType.voice:
        if duration_sec is not None:
            m, s = divmod(max(0, duration_sec), 60)
            return f"🎤 Ovozli xabar ({m}:{s:02d})"
        return "🎤 Ovozli xabar"
    if msg_type == MessageType.file:
        return f"📎 {att_name}" if att_name else "📎 Fayl"
    return ""


def _msg_out(m: Message, user: User) -> MessageOut:
    attachment = None
    if m.attachment_path:
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        ticket = create_chat_ticket(m.id)
        attachment = AttachmentOut(
            url=f"{base}/chats/{m.conversation_id}/attachments/{m.id}?ticket={ticket}",
            name=m.attachment_name,
            mime=m.attachment_mime,
            size=m.attachment_size,
            duration_sec=m.duration_sec,
        )
    return MessageOut(
        id=m.id,
        type=m.type,
        text=m.text or "",
        attachment=attachment,
        mine=m.sender_id == user.id,
        time=m.created_at,
        read=m.read_at is not None,
    )


# ---------- Suhbatlar ----------
def list_conversations(db: Session, user: User, limit: int, offset: int) -> list[ConversationOut]:
    stmt = (
        _select()
        .where(_participant_filter(user), Conversation.last_message_at.is_not(None))
        .order_by(Conversation.last_message_at.desc())
        .limit(limit)
        .offset(offset)
    )
    convs = list(db.scalars(stmt))
    unread = _unread_map(db, user, [c.id for c in convs])
    traveler_agency_ids = list({c.agency_id for c in convs if _side(c, user) == "traveler"})
    online_agencies = _online_agencies(db, traveler_agency_ids)
    result: list[ConversationOut] = []
    for c in convs:
        side = _side(c, user)
        is_on = c.agency_id in online_agencies if side == "traveler" else manager.is_online(c.user_id)
        result.append(_to_out(c, side, unread.get(c.id, 0), online=is_on))
    return result


def start_conversation(
    db: Session, user: User, tour_id: uuid.UUID, first_message: str | None
) -> ConversationOut:
    tour = db.get(Tour, tour_id)
    if not tour or tour.status != TourStatus.published or not tour.agency.verified:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tour topilmadi")

    where = (
        Conversation.user_id == user.id,
        Conversation.agency_id == tour.agency_id,
        Conversation.tour_id == tour.id,
    )
    conv = db.scalars(_select().where(*where)).first()
    if not conv:
        try:
            db.add(Conversation(user_id=user.id, agency_id=tour.agency_id, tour_id=tour.id))
            db.commit()
        except IntegrityError:  # ikki so'rov bir vaqtda kelgan holat
            db.rollback()
        conv = db.scalars(_select().where(*where)).first()

    if first_message and first_message.strip():
        _add_message(db, conv, user, first_message.strip())

    unread = _unread_map(db, user, [conv.id]).get(conv.id, 0)
    is_on = conv.agency_id in _online_agencies(db, [conv.agency_id])
    return _to_out(conv, "traveler", unread, online=is_on)


# ---------- Xabarlar ----------
def _save_message(
    db: Session,
    conv: Conversation,
    user: User,
    msg_type: MessageType,
    text: str | None,
    *,
    attachment_path: str | None = None,
    attachment_name: str | None = None,
    attachment_mime: str | None = None,
    attachment_size: int | None = None,
    duration_sec: int | None = None,
) -> Message:
    clean_text = text.strip() if text and text.strip() else None
    msg = Message(
        conversation_id=conv.id,
        sender_id=user.id,
        type=msg_type,
        text=clean_text,
        attachment_path=attachment_path,
        attachment_name=attachment_name,
        attachment_mime=attachment_mime,
        attachment_size=attachment_size,
        duration_sec=duration_sec,
    )
    db.add(msg)
    db.flush()
    preview = _preview_label(msg_type, clean_text, duration_sec, attachment_name)
    conv.last_message_text = preview[:200]
    conv.last_message_at = msg.created_at

    agency_ids = notification_service.agency_recipient_ids(db, conv.agency_id)
    if user.id == conv.user_id:
        # Mijoz yozdi: agentlikning hamma xodimlariga
        recipient_ids = agency_ids
        for rid in recipient_ids:
            notification_service.notify_new_message(
                db, rid, user.full_name, conv.id, preview, from_agency=False
            )
    else:
        # Agentlik yozdi: mijozga
        recipient_ids = [conv.user_id]
        notification_service.notify_new_message(
            db, conv.user_id, conv.agency.name, conv.id, preview, from_agency=True
        )

    conv_id = str(conv.id)
    all_participants = [conv.user_id, *agency_ids]
    db.commit()
    db.refresh(msg)
    manager.emit(all_participants, {"type": "chat_message", "conversationId": conv_id})
    manager.emit(recipient_ids, {"type": "notification"})
    return msg


def _add_message(db: Session, conv: Conversation, user: User, text: str) -> Message:
    return _save_message(db, conv, user, MessageType.text, text)


def send_message(db: Session, user: User, conv_id: uuid.UUID, text: str) -> MessageOut:
    conv, side = _get_conv(db, user, conv_id)
    if side == "agency" and not _is_manager(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Xabarni faqat agentlik admini yoza oladi"
        )
    return _msg_out(_add_message(db, conv, user, text), user)


def send_attachment(
    db: Session,
    user: User,
    conv_id: uuid.UUID,
    msg_type: MessageType,
    file: UploadFile,
    *,
    text: str | None = None,
    duration_sec: int | None = None,
) -> MessageOut:
    if msg_type == MessageType.text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Noto'g'ri biriktirma turi")
    conv, side = _get_conv(db, user, conv_id)
    if side == "agency" and not _is_manager(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Xabarni faqat agentlik admini yoza oladi"
        )
    if text and len(text.strip()) > 2000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Matn 2000 belgidan oshmasligi kerak")

    clean_dur = max(0, min(duration_sec, 3600)) if duration_sec is not None else None
    rel_path, mime, size = save_chat_attachment(file, f"chats/{conv.id}", msg_type.value)
    orig_name = (file.filename or "").strip()[:200] or None
    try:
        msg = _save_message(
            db,
            conv,
            user,
            msg_type,
            text,
            attachment_path=rel_path,
            attachment_name=orig_name,
            attachment_mime=mime,
            attachment_size=size,
            duration_sec=clean_dur,
        )
    except Exception:
        db.rollback()
        delete_file(rel_path, private=True)
        raise
    return _msg_out(msg, user)


def get_attachment(
    db: Session,
    conv_id: uuid.UUID,
    message_id: uuid.UUID,
    ticket: str | None,
    user: User | None,
):
    msg = db.scalars(
        select(Message)
        .options(joinedload(Message.conversation))
        .where(Message.id == message_id, Message.conversation_id == conv_id)
    ).first()
    if not msg or not msg.attachment_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fayl topilmadi")

    allowed = False
    if ticket and verify_chat_ticket(ticket, message_id):
        allowed = True
    elif user and _side(msg.conversation, user):
        allowed = True
    if not allowed:
        if not user and not ticket:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Token yaroqsiz yoki muddati o'tgan",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fayl topilmadi")

    path = private_file(msg.attachment_path)
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fayl topilmadi")
    mime = msg.attachment_mime or "application/octet-stream"
    inline = mime.startswith(("image/", "audio/")) or mime == "application/pdf"
    filename = msg.attachment_name or path.name
    return path, mime, filename, inline


def list_messages(
    db: Session,
    user: User,
    conv_id: uuid.UUID,
    before: datetime | None,
    after: datetime | None,
    limit: int,
) -> list[MessageOut]:
    conv, side = _get_conv(db, user, conv_id)
    stmt = select(Message).where(Message.conversation_id == conv.id)

    if after:  # polling: faqat yangilari
        messages = list(
            db.scalars(
                stmt.where(Message.created_at > after)
                .order_by(Message.created_at.asc())
                .limit(limit)
            )
        )
    else:      # birinchi yuklash yoki eski xabarlar (before)
        if before:
            stmt = stmt.where(Message.created_at < before)
        messages = list(db.scalars(stmt.order_by(Message.created_at.desc()).limit(limit)))
        messages.reverse()

    result = [_msg_out(m, user) for m in messages]
    # Egasi xabarlarni "o'qilgan" qilmaydi (faqat kuzatadi)
    _mark_read(db, user, conv.id, mark_messages=side == "traveler" or _is_manager(user))
    return result


def _mark_read(db: Session, user: User, conv_id: uuid.UUID, mark_messages: bool = True) -> None:
    now = _now()
    msgs_changed = 0
    if mark_messages:
        res = db.execute(
            update(Message)
            .where(
                Message.conversation_id == conv_id,
                Message.sender_id != user.id,
                Message.read_at.is_(None),
            )
            .values(read_at=now)
        )
        msgs_changed = res.rowcount or 0
    res = db.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.type == NotificationType.message,
            Notification.target_kind == "chat",
            Notification.target_id == conv_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    notifs_changed = res.rowcount or 0
    db.commit()

    # Faqat haqiqatan o'zgarish bo'lgandagina signal yuboramiz. Aks holda xabarlarni
    # so'rash -> signal -> qayta so'rash degan cheksiz sikl hosil bo'ladi.
    if msgs_changed:
        manager.emit_one(user.id, {"type": "chat_read", "conversationId": str(conv_id)})
    if notifs_changed:
        manager.emit_one(user.id, {"type": "notifications_sync"})


def mark_conversation_read(db: Session, user: User, conv_id: uuid.UUID) -> None:
    conv, side = _get_conv(db, user, conv_id)
    _mark_read(db, user, conv.id, mark_messages=side == "traveler" or _is_manager(user))


def unread_total(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count(Message.id))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            _participant_filter(user),
            Message.sender_id != user.id,
            Message.read_at.is_(None),
        )
    ) or 0