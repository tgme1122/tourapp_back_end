import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.agency_model import AgencyMember, AgencyMemberRole, AgencyStatus
from app.models.chat_model import Message
from app.models.user_model import User, UserRole
from app.realtime import manager
from app.schemas.agency_schema import MemberCreate, MemberOut, MemberUpdate
from app.security import hash_password
from app.services.user_service import _ensure_unique

MAX_MEMBERS = 10


def _out(m: AgencyMember) -> MemberOut:
    u = m.user
    return MemberOut(
        user_id=u.id, first_name=u.first_name, last_name=u.last_name, email=u.email,
        phone=u.phone, role=m.role, is_active=u.is_active, created_at=m.created_at,
    )


def list_members(db: Session, owner: User) -> list[MemberOut]:
    rows = db.scalars(
        select(AgencyMember)
        .options(joinedload(AgencyMember.user))
        .where(AgencyMember.agency_id == owner.agency_profile.id)
        .order_by(AgencyMember.created_at)
    )
    return [_out(m) for m in rows]


def create_manager(db: Session, owner: User, data: MemberCreate) -> MemberOut:
    profile = owner.agency_profile
    if profile.status != AgencyStatus.approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agentligingiz hali tasdiqlanmagan")

    count = db.scalar(
        select(func.count(AgencyMember.id)).where(AgencyMember.agency_id == profile.id)
    ) or 0
    if count >= MAX_MEMBERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Ko'pi bilan {MAX_MEMBERS} ta xodim")

    _ensure_unique(db, data.email, data.phone)
    user = User(
        first_name=data.first_name.strip(),
        last_name=data.last_name.strip(),
        email=data.email.lower(),
        phone=data.phone,
        password_hash=hash_password(data.password),
        role=UserRole.agency,
        is_email_verified=True,  # egasi kafolatlaydi
    )
    user.membership = AgencyMember(agency_id=profile.id, role=AgencyMemberRole.manager)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _out(user.membership)


def _get_manager(db: Session, owner: User, user_id: uuid.UUID) -> AgencyMember:
    member = db.scalars(
        select(AgencyMember)
        .options(joinedload(AgencyMember.user))
        .where(
            AgencyMember.user_id == user_id,
            AgencyMember.agency_id == owner.agency_profile.id,  # begona agentlik xodimiga tegmaydi
        )
    ).first()
    if not member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Xodim topilmadi")
    if member.role == AgencyMemberRole.owner:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Egasini o'zgartirib bo'lmaydi")
    return member


def set_active(db: Session, owner: User, user_id: uuid.UUID, active: bool) -> MemberOut:
    member = _get_manager(db, owner, user_id)
    member.user.is_active = active  # token darrov ishlamay qoladi
    if not active:
        member.user.token_version += 1
    db.commit()
    db.refresh(member)
    if not active:
        manager.close_user(member.user_id)
    return _out(member)


def update_manager(
    db: Session, owner: User, user_id: uuid.UUID, data: MemberUpdate
) -> MemberOut:
    member = _get_manager(db, owner, user_id)
    u = member.user
    values = data.model_dump(exclude_unset=True)

    new_email = values.get("email")
    new_phone = values.get("phone")
    conds = []
    if new_email and new_email.lower() != u.email.lower():
        conds.append(func.lower(User.email) == new_email.lower())
    if new_phone and new_phone != u.phone:
        conds.append(User.phone == new_phone)
    if conds:
        conflict = db.scalar(select(User).where(or_(*conds), User.id != u.id))
        if conflict:
            field = (
                "Email"
                if new_email and conflict.email.lower() == new_email.lower()
                else "Telefon raqam"
            )
            raise HTTPException(status.HTTP_409_CONFLICT, f"{field} allaqachon ro'yxatdan o'tgan")

    if "first_name" in values and values["first_name"] is not None:
        u.first_name = values["first_name"]
    if "last_name" in values and values["last_name"] is not None:
        u.last_name = values["last_name"]
    if new_email:
        u.email = new_email.lower()
    if new_phone:
        u.phone = new_phone
    password_changed = bool(values.get("password"))
    if password_changed:
        u.password_hash = hash_password(values["password"])
        u.token_version += 1

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email yoki telefon raqam band")
    db.refresh(member)
    if password_changed:
        manager.close_user(u.id)
    return _out(member)


def delete_manager(db: Session, owner: User, user_id: uuid.UUID) -> None:
    member = _get_manager(db, owner, user_id)
    sent_messages = db.scalar(
        select(func.count(Message.id)).where(Message.sender_id == user_id)
    ) or 0
    if sent_messages > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu xodim chatlarda xabar yozgani uchun o'chirib bo'lmaydi. Uni nofaol qilishingiz mumkin.",
        )
    db.delete(member.user)
    db.commit()