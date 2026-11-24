import uuid

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_agency_viewer, get_approved_agency, get_optional_user, require_roles,
)
from app.models.tour_model import TourCategory
from app.models.user_model import User, UserRole
from app.schemas.tour_schema import (
    DepartureIn, DepartureOut, DurationKey, MyTourOut, PriceRangeKey, ReviewIn,
    ReviewOut, SortKey, TourCardOut, TourCreate, TourDetailResponse,
    TourImageOut, TourUpdate,
)
from app.services import tour_service
from app.services.tour_service import TourFilters

router = APIRouter(prefix="/tours", tags=["tours"])


# ---------- Ommaviy ----------
@router.get("", response_model=list[TourCardOut])
def list_tours(
    q: str | None = Query(None, max_length=100),
    categories: list[TourCategory] | None = Query(None),
    country: str | None = None,
    price_range: PriceRangeKey | None = Query(None, alias="priceRange"),
    duration: DurationKey | None = None,
    min_rating: float | None = Query(None, ge=0, le=5, alias="minRating"),
    hot_only: bool = Query(False, alias="hotOnly"),
    sort: SortKey = "popular",
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_optional_user),
):
    filters = TourFilters(
        q=q, categories=categories, country=country, price_range=price_range,
        duration=duration, min_rating=min_rating, hot_only=hot_only,
        sort=sort, limit=limit, offset=offset,
    )
    return tour_service.list_tours(db, filters, viewer)


# ---------- Foydalanuvchi ("/{tour_id}" dan OLDIN turishi kerak) ----------
@router.get("/countries", response_model=list[str])
def tour_countries(db: Session = Depends(get_db)):
    return tour_service.list_countries(db)


@router.get("/saved", response_model=list[TourCardOut])
def saved_tours(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_roles(UserRole.traveler)),
    db: Session = Depends(get_db),
):
    return tour_service.list_saved(db, user, limit, offset)


# ---------- Agentlik: ko'rish (egasi ham, manager ham) ----------
@router.get("/mine", response_model=list[MyTourOut])
def my_tours(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_agency_viewer),
    db: Session = Depends(get_db),
):
    return tour_service.list_my_tours(db, user, limit, offset)


# ---------- Agentlik: boshqarish (faqat manager) ----------
@router.post("", response_model=TourDetailResponse, status_code=201)
def create_tour(
    data: TourCreate, user: User = Depends(get_approved_agency), db: Session = Depends(get_db)
):
    tour = tour_service.create_tour(db, user, data)
    return tour_service.get_detail(db, tour.id, user)


# ---------- Detail ----------
@router.get("/{tour_id}", response_model=TourDetailResponse)
def tour_detail(
    tour_id: uuid.UUID,
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_optional_user),
):
    return tour_service.get_detail(db, tour_id, viewer)


@router.patch("/{tour_id}", response_model=TourDetailResponse)
def update_tour(
    tour_id: uuid.UUID,
    data: TourUpdate,
    user: User = Depends(get_approved_agency),
    db: Session = Depends(get_db),
):
    tour = tour_service.get_own_tour(db, user, tour_id)
    tour_service.update_tour(db, tour, data)
    return tour_service.get_detail(db, tour_id, user)


@router.delete("/{tour_id}", status_code=204)
def archive_tour(
    tour_id: uuid.UUID, user: User = Depends(get_approved_agency), db: Session = Depends(get_db)
):
    tour = tour_service.get_own_tour(db, user, tour_id)
    tour_service.archive_tour(db, tour)
    return Response(status_code=204)


# ---------- Rasmlar ----------
@router.post("/{tour_id}/images", response_model=list[TourImageOut], status_code=201)
def upload_images(
    tour_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    user: User = Depends(get_approved_agency),
    db: Session = Depends(get_db),
):
    tour = tour_service.get_own_tour(db, user, tour_id)
    return tour_service.add_images(db, tour, files)


@router.delete("/{tour_id}/images/{image_id}", status_code=204)
def delete_image(
    tour_id: uuid.UUID,
    image_id: uuid.UUID,
    user: User = Depends(get_approved_agency),
    db: Session = Depends(get_db),
):
    tour = tour_service.get_own_tour(db, user, tour_id)
    tour_service.delete_image(db, tour, image_id)
    return Response(status_code=204)


# ---------- Jo'nashlar ----------
@router.post("/{tour_id}/departures", response_model=DepartureOut, status_code=201)
def add_departure(
    tour_id: uuid.UUID,
    data: DepartureIn,
    user: User = Depends(get_approved_agency),
    db: Session = Depends(get_db),
):
    tour = tour_service.get_own_tour(db, user, tour_id)
    return tour_service.add_departure(db, tour, data)


@router.delete("/{tour_id}/departures/{departure_id}", status_code=204)
def delete_departure(
    tour_id: uuid.UUID,
    departure_id: uuid.UUID,
    user: User = Depends(get_approved_agency),
    db: Session = Depends(get_db),
):
    tour = tour_service.get_own_tour(db, user, tour_id)
    tour_service.delete_departure(db, tour, departure_id)
    return Response(status_code=204)


# ---------- Saqlash va sharh (oddiy foydalanuvchi) ----------
@router.put("/{tour_id}/save", status_code=204)
def save_tour(
    tour_id: uuid.UUID,
    user: User = Depends(require_roles(UserRole.traveler)),
    db: Session = Depends(get_db),
):
    tour_service.save_tour(db, user, tour_id)
    return Response(status_code=204)


@router.delete("/{tour_id}/save", status_code=204)
def unsave_tour(
    tour_id: uuid.UUID,
    user: User = Depends(require_roles(UserRole.traveler)),
    db: Session = Depends(get_db),
):
    tour_service.unsave_tour(db, user, tour_id)
    return Response(status_code=204)


@router.get("/{tour_id}/reviews", response_model=list[ReviewOut])
def tour_reviews(
    tour_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_optional_user),
):
    return tour_service.list_tour_reviews(db, tour_id, viewer, limit, offset)


@router.post("/{tour_id}/reviews", response_model=ReviewOut, status_code=201)
def add_review(
    tour_id: uuid.UUID,
    data: ReviewIn,
    user: User = Depends(require_roles(UserRole.traveler)),
    db: Session = Depends(get_db),
):
    return tour_service.add_review(db, user, tour_id, data)


@router.put("/{tour_id}/reviews", response_model=ReviewOut)
def update_review(
    tour_id: uuid.UUID,
    data: ReviewIn,
    user: User = Depends(require_roles(UserRole.traveler)),
    db: Session = Depends(get_db),
):
    return tour_service.update_review(db, user, tour_id, data)