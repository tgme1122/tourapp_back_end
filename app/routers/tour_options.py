import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_agency_viewer, get_approved_agency
from app.models.user_model import User
from app.schemas.tour_option_schema import (
    AddonIn, AddonOut, AddonUpdate, BookingOptionsOut, PolicyIn, PolicyOut,
)
from app.services import tour_option_service as svc

router = APIRouter(prefix="/tours", tags=["tour-options"])


# Ommaviy: bron ekrani uchun xizmatlar va bekor qilish shartlari
@router.get("/{tour_id}/booking-options", response_model=BookingOptionsOut)
def booking_options(tour_id: uuid.UUID, db: Session = Depends(get_db)):
    return svc.booking_options(db, tour_id)


# Agentlik: ko'rish (egasi ham, manager ham)
@router.get("/{tour_id}/addons", response_model=list[AddonOut])
def list_addons(
    tour_id: uuid.UUID, user: User = Depends(get_agency_viewer), db: Session = Depends(get_db)
):
    return svc.agency_addons(db, user, tour_id)


@router.get("/{tour_id}/cancellation-policy", response_model=PolicyOut)
def get_policy(
    tour_id: uuid.UUID, user: User = Depends(get_agency_viewer), db: Session = Depends(get_db)
):
    return svc.get_policy(db, user, tour_id)


# Agentlik: boshqarish (faqat manager)
@router.post("/{tour_id}/addons", response_model=AddonOut, status_code=201)
def add_addon(
    tour_id: uuid.UUID,
    data: AddonIn,
    user: User = Depends(get_approved_agency),
    db: Session = Depends(get_db),
):
    return svc.add_addon(db, user, tour_id, data)


@router.patch("/{tour_id}/addons/{addon_id}", response_model=AddonOut)
def update_addon(
    tour_id: uuid.UUID,
    addon_id: uuid.UUID,
    data: AddonUpdate,
    user: User = Depends(get_approved_agency),
    db: Session = Depends(get_db),
):
    return svc.update_addon(db, user, tour_id, addon_id, data)


@router.delete("/{tour_id}/addons/{addon_id}", status_code=204)
def delete_addon(
    tour_id: uuid.UUID,
    addon_id: uuid.UUID,
    user: User = Depends(get_approved_agency),
    db: Session = Depends(get_db),
):
    svc.delete_addon(db, user, tour_id, addon_id)
    return Response(status_code=204)


@router.put("/{tour_id}/cancellation-policy", response_model=PolicyOut)
def set_policy(
    tour_id: uuid.UUID,
    data: PolicyIn,
    user: User = Depends(get_approved_agency),
    db: Session = Depends(get_db),
):
    """`rules: []` yuborilsa, default shart (14+ kun 100%, 7-13 kun 50%, undan kam 0%) ishlaydi."""
    return svc.set_policy(db, user, tour_id, data)