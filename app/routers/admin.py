import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_roles
from app.models.agency_model import AgencyProfile, AgencyStatus
from app.models.user_model import User, UserRole
from app.schemas.admin_schema import (
    AdminAgencyOut, AgencyCountsOut, DocumentCheck, PromoCreate, PromoResultOut,
    ReasonRequest,AdminUserDetailOut, AdminUserOut, UserCountsOut
)
from app.services import admin_service
from app.services.email_service import send_agency_decision
from typing import Literal

from app.models.booking_model import BookingStatus
from app.models.tour_model import TourCategory, TourStatus
from app.schemas.admin_schema import (
    AdminTourBookingOut, AdminTourDetailOut, AdminTourOut, TourCountsOut,
)
from app.services import admin_tour_service

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require_roles(UserRole.admin)


def _decision(profile: AgencyProfile, background: BackgroundTasks) -> AdminAgencyOut:
    out = AdminAgencyOut.model_validate(profile)
    background.add_task(
        send_agency_decision, out.owner_email, out.name, out.status.value, out.rejection_reason
    )
    return out


@router.get("/agencies", response_model=list[AdminAgencyOut])
def list_agencies(
    status: AgencyStatus | None = None,
    q: str | None = Query(None, max_length=100),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return admin_service.list_agencies(db, status, q, limit, offset)


# "/{agency_id}" dan OLDIN turishi kerak
@router.get("/agencies/counts", response_model=AgencyCountsOut)
def counts(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return admin_service.counts(db)


@router.get("/agencies/{agency_id}", response_model=AdminAgencyOut)
def agency_detail(
    agency_id: uuid.UUID, _: User = Depends(admin_only), db: Session = Depends(get_db)
):
    return admin_service.get_agency(db, agency_id)


@router.post("/agencies/{agency_id}/approve", response_model=AdminAgencyOut)
def approve(
    agency_id: uuid.UUID,
    background: BackgroundTasks,
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return _decision(admin_service.approve(db, admin, agency_id), background)


@router.post("/agencies/{agency_id}/reject", response_model=AdminAgencyOut)
def reject(
    agency_id: uuid.UUID,
    data: ReasonRequest,
    background: BackgroundTasks,
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return _decision(admin_service.reject(db, admin, agency_id, data.reason), background)


@router.post("/agencies/{agency_id}/suspend", response_model=AdminAgencyOut)
def suspend(
    agency_id: uuid.UUID,
    data: ReasonRequest,
    background: BackgroundTasks,
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return _decision(admin_service.suspend(db, admin, agency_id, data.reason), background)


@router.patch("/agencies/{agency_id}/documents/{document_id}", response_model=AdminAgencyOut)
def check_document(
    agency_id: uuid.UUID,
    document_id: uuid.UUID,
    data: DocumentCheck,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return admin_service.check_document(db, agency_id, document_id, data)


@router.post("/promo", response_model=PromoResultOut)
def send_promo(
    data: PromoCreate, _: User = Depends(admin_only), db: Session = Depends(get_db)
):
    return PromoResultOut(sent=admin_service.send_promo(db, data))

# ---------- Foydalanuvchilar ----------
@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    role: UserRole | None = None,
    is_active: bool | None = Query(None, alias="isActive"),
    q: str | None = Query(None, max_length=100),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return admin_service.list_users(db, role, is_active, q, limit, offset)


# "/{user_id}" dan OLDIN turishi kerak
@router.get("/users/counts", response_model=UserCountsOut)
def user_counts(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return admin_service.user_counts(db)


@router.get("/users/{user_id}", response_model=AdminUserDetailOut)
def user_detail(
    user_id: uuid.UUID, _: User = Depends(admin_only), db: Session = Depends(get_db)
):
    return admin_service.get_user_detail(db, user_id)


@router.post("/users/{user_id}/block", response_model=AdminUserOut)
def block_user(
    user_id: uuid.UUID, admin: User = Depends(admin_only), db: Session = Depends(get_db)
):
    return admin_service.set_user_active(db, admin, user_id, False)


@router.post("/users/{user_id}/unblock", response_model=AdminUserOut)
def unblock_user(
    user_id: uuid.UUID, admin: User = Depends(admin_only), db: Session = Depends(get_db)
):
    return admin_service.set_user_active(db, admin, user_id, True)

# ---------- Turlar (faqat o'qish) ----------
@router.get("/tours", response_model=list[AdminTourOut])
def list_tours(
    status: TourStatus | None = None,
    agency_id: uuid.UUID | None = Query(None, alias="agencyId"),
    category: TourCategory | None = None,
    country: str | None = None,
    q: str | None = Query(None, max_length=100),
    sort: Literal["newest", "bookings", "price", "rating"] = "newest",
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return admin_tour_service.list_tours(
        db, status, agency_id, category, country, q, sort, limit, offset
    )


# "/{tour_id}" dan OLDIN turishi kerak
@router.get("/tours/counts", response_model=TourCountsOut)
def tour_counts(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return admin_tour_service.counts(db)


@router.get("/tours/{tour_id}", response_model=AdminTourDetailOut)
def tour_detail(
    tour_id: uuid.UUID, _: User = Depends(admin_only), db: Session = Depends(get_db)
):
    return admin_tour_service.get_detail(db, tour_id)


@router.get("/tours/{tour_id}/bookings", response_model=list[AdminTourBookingOut])
def tour_bookings(
    tour_id: uuid.UUID,
    status: BookingStatus | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return admin_tour_service.tour_bookings(db, tour_id, status, limit, offset)