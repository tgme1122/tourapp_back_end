import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.tour_model import Tour, TourStatus
from app.models.tour_option_model import TourAddon, TourCancellationRule
from app.models.user_model import User
from app.schemas.tour_option_schema import (
    AddonIn, AddonOut, AddonUpdate, BookingOptionsOut, PolicyIn, PolicyOut, PolicyRule,
)

MAX_ADDONS = 20
DEFAULT_POLICY = [
    {"days_before": 14, "refund_percent": 100},
    {"days_before": 7, "refund_percent": 50},
    {"days_before": 0, "refund_percent": 0},
]


# ---------- Yordamchilar ----------
def _own_tour(db: Session, user: User, tour_id: uuid.UUID) -> Tour:
    tour = db.get(Tour, tour_id)
    if not tour or not user.agency_profile or tour.agency_id != user.agency_profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tour topilmadi")
    return tour


def effective_policy(db: Session, tour_id: uuid.UUID) -> tuple[list[dict], bool]:
    """(qoidalar, default_mi). Qoidalar `days_before` kamayish tartibida."""
    rows = db.scalars(
        select(TourCancellationRule)
        .where(TourCancellationRule.tour_id == tour_id)
        .order_by(TourCancellationRule.days_before.desc())
    ).all()
    if not rows:
        return [dict(r) for r in DEFAULT_POLICY], True
    return [
        {"days_before": r.days_before, "refund_percent": r.refund_percent} for r in rows
    ], False


def refund_percent(policy: list[dict], days_left: int) -> int:
    for rule in sorted(policy, key=lambda r: -r["days_before"]):
        if days_left >= rule["days_before"]:
            return rule["refund_percent"]
    return 0


def list_addons(db: Session, tour_id: uuid.UUID, active_only: bool) -> list[TourAddon]:
    stmt = select(TourAddon).where(TourAddon.tour_id == tour_id)
    if active_only:
        stmt = stmt.where(TourAddon.is_active.is_(True))
    return list(db.scalars(stmt.order_by(TourAddon.created_at, TourAddon.id)))


# ---------- Ommaviy ----------
def booking_options(db: Session, tour_id: uuid.UUID) -> BookingOptionsOut:
    tour = db.get(Tour, tour_id)
    if not tour or tour.status != TourStatus.published or not tour.agency.verified:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tour topilmadi")
    policy, is_default = effective_policy(db, tour_id)
    return BookingOptionsOut(
        addons=[AddonOut.model_validate(a) for a in list_addons(db, tour_id, True)],
        cancellation_policy=[PolicyRule(**r) for r in policy],
        is_default_policy=is_default,
        hold_minutes=settings.BOOKING_HOLD_MINUTES,
    )


# ---------- Agentlik ----------
def agency_addons(db: Session, user: User, tour_id: uuid.UUID) -> list[AddonOut]:
    _own_tour(db, user, tour_id)
    return [AddonOut.model_validate(a) for a in list_addons(db, tour_id, False)]


def add_addon(db: Session, user: User, tour_id: uuid.UUID, data: AddonIn) -> AddonOut:
    _own_tour(db, user, tour_id)
    count = db.scalar(select(func.count(TourAddon.id)).where(TourAddon.tour_id == tour_id)) or 0
    if count >= MAX_ADDONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Ko'pi bilan {MAX_ADDONS} ta xizmat")
    addon = TourAddon(tour_id=tour_id, **data.model_dump())
    db.add(addon)
    db.commit()
    db.refresh(addon)
    return AddonOut.model_validate(addon)


def _get_addon(db: Session, tour_id: uuid.UUID, addon_id: uuid.UUID) -> TourAddon:
    addon = db.scalars(
        select(TourAddon).where(TourAddon.id == addon_id, TourAddon.tour_id == tour_id)
    ).first()
    if not addon:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Xizmat topilmadi")
    return addon


def update_addon(
    db: Session, user: User, tour_id: uuid.UUID, addon_id: uuid.UUID, data: AddonUpdate
) -> AddonOut:
    _own_tour(db, user, tour_id)
    addon = _get_addon(db, tour_id, addon_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is None and key != "description":
            continue
        setattr(addon, key, value)
    db.commit()
    db.refresh(addon)
    return AddonOut.model_validate(addon)


def delete_addon(db: Session, user: User, tour_id: uuid.UUID, addon_id: uuid.UUID) -> None:
    _own_tour(db, user, tour_id)
    addon = _get_addon(db, tour_id, addon_id)
    db.delete(addon)  # eski bronlarda nusxasi saqlanadi
    db.commit()


def get_policy(db: Session, user: User, tour_id: uuid.UUID) -> PolicyOut:
    _own_tour(db, user, tour_id)
    rules, is_default = effective_policy(db, tour_id)
    return PolicyOut(rules=[PolicyRule(**r) for r in rules], is_default=is_default)


def set_policy(db: Session, user: User, tour_id: uuid.UUID, data: PolicyIn) -> PolicyOut:
    _own_tour(db, user, tour_id)
    db.execute(delete(TourCancellationRule).where(TourCancellationRule.tour_id == tour_id))
    for r in data.rules:
        db.add(TourCancellationRule(
            tour_id=tour_id, days_before=r.days_before, refund_percent=r.refund_percent
        ))
    db.commit()
    return get_policy(db, user, tour_id)