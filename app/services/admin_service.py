import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.agency_model import AgencyMember, AgencyProfile, AgencyStatus
from app.models.booking_model import Booking
from app.models.tour_model import Review, SavedTour, Tour, TourStatus
from app.models.user_model import User, UserRole
from app.realtime import manager
from app.schemas.admin_schema import (
    AdminAgencyOut, AdminUserDetailOut, AdminUserOut, AgencyCountsOut,
    DocumentCheck, PromoCreate, UserBookingItem, UserCountsOut, UserReviewItem,
    UserTourItem,
)
from app.services import agency_service, notification_service

APPROVABLE_FROM = (AgencyStatus.pending, AgencyStatus.rejected, AgencyStatus.suspended)


# =============================================================== Agentliklar
def _load(db: Session, agency_id: uuid.UUID, lock: bool = False) -> AgencyProfile:
    stmt = (
        select(AgencyProfile)
        .options(selectinload(AgencyProfile.documents), joinedload(AgencyProfile.user))
        .where(AgencyProfile.id == agency_id)
    )
    if lock:
        stmt = stmt.with_for_update(of=AgencyProfile)  # ikki admin bir vaqtda hal qilmasin
    profile = db.scalars(stmt).first()
    if not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agentlik topilmadi")
    return profile


def _stamp(profile: AgencyProfile, admin: User) -> None:
    profile.reviewed_by = admin.id
    profile.reviewed_at = datetime.now(timezone.utc)


def list_agencies(
    db: Session, status_filter: AgencyStatus | None, q: str | None, limit: int, offset: int
) -> list[AdminAgencyOut]:
    stmt = select(AgencyProfile).options(
        selectinload(AgencyProfile.documents), joinedload(AgencyProfile.user)
    )
    if status_filter:
        stmt = stmt.where(AgencyProfile.status == status_filter)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                AgencyProfile.name.ilike(like),
                AgencyProfile.tax_id.ilike(like),
                AgencyProfile.license_number.ilike(like),
            )
        )
    stmt = stmt.order_by(AgencyProfile.created_at.desc(), AgencyProfile.id).limit(limit).offset(offset)
    return [AdminAgencyOut.model_validate(p) for p in db.scalars(stmt)]


def counts(db: Session) -> AgencyCountsOut:
    rows = db.execute(
        select(AgencyProfile.status, func.count(AgencyProfile.id)).group_by(AgencyProfile.status)
    )
    return AgencyCountsOut(**{s.value: c for s, c in rows})


def get_agency(db: Session, agency_id: uuid.UUID) -> AdminAgencyOut:
    return AdminAgencyOut.model_validate(_load(db, agency_id))


def approve(db: Session, admin: User, agency_id: uuid.UUID) -> AgencyProfile:
    p = _load(db, agency_id, lock=True)
    if p.status not in APPROVABLE_FROM:
        raise HTTPException(status.HTTP_409_CONFLICT, "Agentlik allaqachon tasdiqlangan")
    if not p.user.is_email_verified:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Agentlik emailini hali tasdiqlamagan")
    missing = agency_service.missing_documents(p)
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Yetishmayotgan hujjatlar: {', '.join(missing)}"
        )

    p.status = AgencyStatus.approved
    p.rejection_reason = None
    for d in p.documents:
        d.is_checked = True
    _stamp(p, admin)
    db.commit()
    manager.emit_one(p.user_id, {"type": "agency_status"})
    manager.emit_admins({"type": "admin_update"})
    return p


def reject(db: Session, admin: User, agency_id: uuid.UUID, reason: str) -> AgencyProfile:
    p = _load(db, agency_id, lock=True)
    if p.status != AgencyStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "Faqat kutilayotgan arizani rad etish mumkin")
    p.status = AgencyStatus.rejected
    p.rejection_reason = reason
    _stamp(p, admin)
    db.commit()
    manager.emit_one(p.user_id, {"type": "agency_status"})
    manager.emit_admins({"type": "admin_update"})
    return p


def suspend(db: Session, admin: User, agency_id: uuid.UUID, reason: str) -> AgencyProfile:
    p = _load(db, agency_id, lock=True)
    if p.status != AgencyStatus.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, "Faqat tasdiqlangan agentlikni bloklash mumkin")
    p.status = AgencyStatus.suspended
    p.rejection_reason = reason
    _stamp(p, admin)
    db.commit()
    manager.emit_one(p.user_id, {"type": "agency_status"})
    manager.emit_admins({"type": "admin_update"})
    return p


def check_document(
    db: Session, agency_id: uuid.UUID, doc_id: uuid.UUID, data: DocumentCheck
) -> AdminAgencyOut:
    p = _load(db, agency_id)
    doc = next((d for d in p.documents if d.id == doc_id), None)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hujjat topilmadi")
    doc.is_checked = data.is_checked
    db.commit()
    db.refresh(p)
    return AdminAgencyOut.model_validate(p)


def send_promo(db: Session, data: PromoCreate) -> int:
    if data.tour_id:
        tour = db.get(Tour, data.tour_id)
        if not tour or tour.status != TourStatus.published:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Tour topilmadi")
    return notification_service.broadcast_promo(db, data.title, data.text, data.tour_id)


# =============================================================== Foydalanuvchilar
def _user_options():
    return joinedload(User.membership).joinedload(AgencyMember.agency)


def _user_out(u: User) -> AdminUserOut:
    p = u.agency_profile
    return AdminUserOut(
        id=u.id, first_name=u.first_name, last_name=u.last_name, email=u.email,
        phone=u.phone, avatar_url=u.avatar_url, role=u.role, language=u.language,
        is_active=u.is_active, is_email_verified=u.is_email_verified,
        created_at=u.created_at,
        agency_id=p.id if p else None,
        agency_name=p.name if p else None,
        agency_status=p.status if p else None,
    )


def _get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.scalars(select(User).options(_user_options()).where(User.id == user_id)).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi")
    return user


def list_users(
    db: Session, role: UserRole | None, is_active: bool | None,
    q: str | None, limit: int, offset: int,
) -> list[AdminUserOut]:
    stmt = select(User).options(_user_options())
    if role:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    if q and q.strip():
        like = f"%{q.strip()}%"
        full_name = func.concat(User.first_name, " ", User.last_name)
        stmt = stmt.where(
            or_(full_name.ilike(like), User.email.ilike(like), User.phone.ilike(like))
        )
    stmt = stmt.order_by(User.created_at.desc(), User.id).limit(limit).offset(offset)
    return [_user_out(u) for u in db.scalars(stmt)]


def user_counts(db: Session) -> UserCountsOut:
    row = db.execute(
        select(
            func.count(User.id),
            func.count(case((User.role == UserRole.traveler, 1))),
            func.count(case((User.role == UserRole.agency, 1))),
            func.count(case((User.role == UserRole.admin, 1))),
            func.count(case((User.is_active.is_(True), 1))),
            func.count(case((User.is_active.is_(False), 1))),
        )
    ).one()
    return UserCountsOut(
        total=row[0], travelers=row[1], agencies=row[2],
        admins=row[3], active=row[4], blocked=row[5],
    )


def get_user_detail(db: Session, user_id: uuid.UUID) -> AdminUserDetailOut:
    u = _get_user(db, user_id)

    limit = 50

    def tour_item(t: Tour) -> UserTourItem:
        return UserTourItem(
            id=t.id, title=t.title, city=t.city, price=t.price, status=t.status.value
        )

    bookings = db.scalars(
        select(Booking)
        .options(joinedload(Booking.tour))
        .where(Booking.user_id == u.id)
        .order_by(Booking.created_at.desc())
        .limit(limit)
    ).all()
    reviews = db.scalars(
        select(Review)
        .options(joinedload(Review.tour))
        .where(Review.user_id == u.id)
        .order_by(Review.created_at.desc())
        .limit(limit)
    ).all()
    saved = db.scalars(
        select(Tour)
        .join(SavedTour, SavedTour.tour_id == Tour.id)
        .where(SavedTour.user_id == u.id)
        .order_by(SavedTour.created_at.desc())
        .limit(limit)
    ).all()
    own_tours = []
    if u.agency_profile:
        own_tours = db.scalars(
            select(Tour)
            .where(Tour.agency_id == u.agency_profile.id)
            .order_by(Tour.created_at.desc())
            .limit(limit)
        ).all()

    return AdminUserDetailOut(
        **_user_out(u).model_dump(),
        bookings=[
            UserBookingItem(
                id=b.id, tour_id=b.tour_id, tour_title=b.tour.title, guests=b.guests,
                status=b.status.value, total=b.total, created_at=b.created_at,
            )
            for b in bookings
        ],
        reviews=[
            UserReviewItem(
                id=r.id, tour_title=r.tour.title, rating=r.rating, text=r.text,
                created_at=r.created_at,
            )
            for r in reviews
        ],
        saved_tours=[tour_item(t) for t in saved],
        tours=[tour_item(t) for t in own_tours],
    )


def set_user_active(
    db: Session, admin: User, user_id: uuid.UUID, active: bool
) -> AdminUserOut:
    u = _get_user(db, user_id)
    if u.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O'zingizni bloklab bo'lmaydi")
    if u.role == UserRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Adminni bloklab bo'lmaydi")
    if u.is_active == active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Foydalanuvchi allaqachon faol" if active else "Foydalanuvchi allaqachon bloklangan",
        )
    u.is_active = active
    db.commit()
    db.refresh(u)
    return _user_out(u)