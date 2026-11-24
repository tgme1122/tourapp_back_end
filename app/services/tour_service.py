import uuid
from dataclasses import dataclass
from datetime import date
from app.services import booking_service
from app.models.agency_model import AgencyProfile, AgencyStatus

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.tour_model import (
    Departure, Review, SavedTour, Tour, TourCategory, TourImage,
    TourItineraryDay, TourStatus,
)
from app.models.user_model import User
from app.schemas.tour_schema import (
    DepartureIn, DepartureOut, ItineraryDayIn, ItineraryDayOut, MyReviewOut, MyTourOut,
    ReviewIn, ReviewOut, TourCardOut, TourCreate, TourDetailResponse,
    TourDetailsOut, TourImageOut, TourUpdate,
)
from app.services.storage_service import delete_file, media_url, save_image
from app.realtime import manager
from app.services import notification_service
from app.time_utils import UZ_TZ, today_uz

MAX_IMAGES_PER_TOUR = 10

# [pastki chegara, yuqori chegara)
PRICE_RANGES = {
    "lt1": (None, 1_000_000),
    "1to5": (1_000_000, 5_000_000),
    "5to10": (5_000_000, 10_000_000),
    "gt10": (10_000_000, None),
}
DURATIONS = {"short": (1, 3), "mid": (4, 7), "long": (8, None)}  # kunlar, ikkala chegara ham kiradi

NULLABLE_FIELDS = {"old_price", "hotel", "meals", "transport", "group_size", "language"}


@dataclass
class TourFilters:
    q: str | None = None
    categories: list[TourCategory] | None = None
    country: str | None = None
    price_range: str | None = None
    duration: str | None = None
    min_rating: float | None = None
    hot_only: bool = False
    sort: str = "popular"
    limit: int = 20
    offset: int = 0


# ---------- Yordamchilar ----------
def _initials(name: str) -> str:
    parts = name.split()
    return "".join(p[0] for p in parts[:2]).upper() or "?"

def _approved_agency_ids():
    return select(AgencyProfile.id).where(AgencyProfile.status == AgencyStatus.approved)

def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Tour topilmadi")


def _is_owner(tour: Tour, user: User | None) -> bool:
    return bool(user and user.agency_profile and tour.agency_id == user.agency_profile.id)


def _base_select():
    """Tour + o'rtacha reyting + sharhlar soni."""
    stats = (
        select(
            Review.tour_id.label("tour_id"),
            func.avg(Review.rating).label("avg_rating"),
            func.count(Review.id).label("cnt"),
        )
        .group_by(Review.tour_id)
        .subquery()
    )
    stmt = (
        select(Tour, stats.c.avg_rating, stats.c.cnt)
        .outerjoin(stats, stats.c.tour_id == Tour.id)
        .options(selectinload(Tour.images), selectinload(Tour.agency))
    )
    return stmt, stats


def _card_dicts(db: Session, rows, viewer: User | None) -> list[dict]:
    """Sahifadagi turlar uchun qo'shimcha ma'lumotlarni 3 ta so'rov bilan yig'adi."""
    if not rows:
        return []
    tour_ids = [r[0].id for r in rows]
    agency_ids = {r[0].agency_id for r in rows}

    seats: dict[uuid.UUID, int] = {}
    upcoming = db.scalars(
        select(Departure)
        .where(
            Departure.tour_id.in_(tour_ids),
            Departure.start_date >= today_uz(),
            Departure.seats_left > 0,
        )
        .order_by(Departure.start_date)
    )
    for d in upcoming:
        seats.setdefault(d.tour_id, d.seats_left)  # eng yaqin jo'nash

    agency_ratings = {
        aid: round(float(avg), 1)
        for aid, avg in db.execute(
            select(Tour.agency_id, func.avg(Review.rating))
            .join(Review, Review.tour_id == Tour.id)
            .where(Tour.agency_id.in_(agency_ids))
            .group_by(Tour.agency_id)
        )
    }

    saved: set[uuid.UUID] = set()
    if viewer:
        saved = set(
            db.scalars(
                select(SavedTour.tour_id).where(
                    SavedTour.user_id == viewer.id, SavedTour.tour_id.in_(tour_ids)
                )
            )
        )

    result = []
    for tour, avg, cnt in rows:
        result.append(
            dict(
                id=tour.id,
                city=tour.city,
                country=tour.country,
                title=tour.title,
                agency=tour.agency.name,
                agency_id=tour.agency_id,
                agency_verified=tour.agency.verified,
                agency_rating=agency_ratings.get(tour.agency_id, 0.0),
                rating=round(float(avg), 1) if avg else 0.0,
                reviews=cnt or 0,
                days=tour.days,
                price=tour.price,
                old_price=tour.old_price,
                seats_left=seats.get(tour.id),
                category=tour.category,
                image=media_url(tour.images[0].path) if tour.images else None,
                hot=tour.hot,
                trending=tour.trending,
                is_saved=tour.id in saved,
            )
        )
    return result


def _check_itinerary(days: int, itinerary: list[ItineraryDayIn]) -> None:
    nums = [i.day for i in itinerary]
    if len(nums) != len(set(nums)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Dasturda kun raqamlari takrorlanmasligi kerak")
    if any(n > days for n in nums):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Dastur kuni tour davomiyligidan oshib ketdi")


def _ensure_publishable(tour: Tour) -> None:
    if not tour.images:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nashr qilish uchun kamida 1 ta rasm yuklang")
    if not any(d.start_date >= today_uz() for d in tour.departures):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nashr qilish uchun kamida 1 ta jo'nash sanasi qo'shing")


# ---------- Ro'yxat / qidiruv ----------
def list_tours(db: Session, f: TourFilters, viewer: User | None) -> list[TourCardOut]:
    stmt, stats = _base_select()
    stmt = stmt.where(Tour.status == TourStatus.published, Tour.agency_id.in_(_approved_agency_ids()))

    if f.q:
        like = f"%{f.q.strip()}%"
        stmt = stmt.join(AgencyProfile, AgencyProfile.id == Tour.agency_id).where(
            or_(
                Tour.title.ilike(like),
                Tour.city.ilike(like),
                Tour.country.ilike(like),
                AgencyProfile.name.ilike(like),
            )
        )
    if f.categories:
        stmt = stmt.where(Tour.category.in_(f.categories))
    if f.country:
        stmt = stmt.where(func.lower(Tour.country) == f.country.lower())
    if f.price_range:
        lo, hi = PRICE_RANGES[f.price_range]
        if lo is not None:
            stmt = stmt.where(Tour.price >= lo)
        if hi is not None:
            stmt = stmt.where(Tour.price < hi)
    if f.duration:
        lo, hi = DURATIONS[f.duration]
        stmt = stmt.where(Tour.days >= lo)
        if hi is not None:
            stmt = stmt.where(Tour.days <= hi)
    if f.min_rating:
        stmt = stmt.where(func.coalesce(stats.c.avg_rating, 0) >= f.min_rating)
    if f.hot_only:
        stmt = stmt.where(Tour.hot.is_(True))

    if f.sort == "cheap":
        stmt = stmt.order_by(Tour.price.asc(), Tour.id)
    elif f.sort == "rating":
        stmt = stmt.order_by(
            func.coalesce(stats.c.avg_rating, 0).desc(),
            func.coalesce(stats.c.cnt, 0).desc(),
            Tour.id,
        )
    else:  # popular
        stmt = stmt.order_by(Tour.bookings_count.desc(), Tour.created_at.desc(), Tour.id)

    rows = db.execute(stmt.limit(f.limit).offset(f.offset)).all()
    return [TourCardOut(**d) for d in _card_dicts(db, rows, viewer)]


def list_countries(db: Session) -> list[str]:
    return list(
        db.scalars(
            select(Tour.country)
            .where(Tour.status == TourStatus.published, Tour.agency_id.in_(_approved_agency_ids()))
            .distinct()
            .order_by(Tour.country)
        )
    )


def list_saved(db: Session, user: User, limit: int = 50, offset: int = 0) -> list[TourCardOut]:
    stmt, _ = _base_select()
    stmt = (
        stmt.join(SavedTour, SavedTour.tour_id == Tour.id)
        .where(SavedTour.user_id == user.id, Tour.status == TourStatus.published, Tour.agency_id.in_(_approved_agency_ids()))
        .order_by(SavedTour.created_at.desc(), Tour.id)
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(stmt).all()
    return [TourCardOut(**d) for d in _card_dicts(db, rows, user)]


def list_my_tours(db: Session, user: User, limit: int = 50, offset: int = 0) -> list[MyTourOut]:
    stmt, _ = _base_select()
    stmt = (
        stmt.where(Tour.agency_id == user.agency_profile.id)
        .order_by(Tour.created_at.desc(), Tour.id)
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(stmt).all()
    dicts = _card_dicts(db, rows, user)
    return [MyTourOut(**d, status=r[0].status) for d, r in zip(dicts, rows)]


# ---------- Detail ----------
def list_tour_reviews(
    db: Session, tour_id: uuid.UUID, viewer: User | None, limit: int = 20, offset: int = 0
) -> list[ReviewOut]:
    tour = db.get(Tour, tour_id)
    if not tour or (
        (tour.status != TourStatus.published or not tour.agency.verified) and not _is_owner(tour, viewer)
    ):
        raise _not_found()

    reviews = db.scalars(
        select(Review)
        .options(joinedload(Review.user))
        .where(Review.tour_id == tour.id)
        .order_by(Review.created_at.desc(), Review.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        ReviewOut(
            id=r.id,
            author=r.user.full_name,
            initials=_initials(r.user.full_name),
            rating=r.rating,
            date=r.created_at.astimezone(UZ_TZ).date().isoformat(),
            text=r.text,
        )
        for r in reviews
    ]


def get_detail(db: Session, tour_id: uuid.UUID, viewer: User | None) -> TourDetailResponse:
    stmt, _ = _base_select()
    row = db.execute(stmt.where(Tour.id == tour_id)).first()
    if not row:
        raise _not_found()
    tour = row[0]
    if (tour.status != TourStatus.published or not tour.agency.verified) and not _is_owner(tour, viewer):
        raise _not_found()

    card = TourCardOut(**_card_dicts(db, [row], viewer)[0])

    reviews = db.scalars(
        select(Review)
        .options(joinedload(Review.user))
        .where(Review.tour_id == tour.id)
        .order_by(Review.created_at.desc(), Review.id)
        .limit(20)
    ).all()

    today = today_uz()
    is_owner = _is_owner(tour, viewer)
    details = TourDetailsOut(
        gallery=[media_url(i.path) for i in tour.images],
        images=[TourImageOut(id=i.id, url=media_url(i.path), position=i.position) for i in tour.images],
        description=tour.description,
        hotel=tour.hotel,
        meals=tour.meals,
        transport=tour.transport,
        group_size=tour.group_size,
        language=tour.language,
        included=tour.included or [],
        excluded=tour.excluded or [],
        itinerary=[ItineraryDayOut.model_validate(i) for i in tour.itinerary],
        departures=[
            DepartureOut.model_validate(d)
            for d in tour.departures
            if is_owner or d.start_date >= today
        ],
        reviews=[
            ReviewOut(
                id=r.id,
                author=r.user.full_name,
                initials=_initials(r.user.full_name),
                rating=r.rating,
                date=r.created_at.astimezone(UZ_TZ).date().isoformat(),
                text=r.text,
            )
            for r in reviews
        ],
    )
    return TourDetailResponse(tour=card, details=details, status=tour.status)


# ---------- Agentlik: CRUD ----------
def get_own_tour(db: Session, user: User, tour_id: uuid.UUID) -> Tour:
    tour = db.get(Tour, tour_id)
    if not tour or not _is_owner(tour, user):
        raise _not_found()  # boshqa agentlik turi mavjudligini oshkor qilmaymiz
    return tour


def create_tour(db: Session, user: User, data: TourCreate) -> Tour:
    _check_itinerary(data.days, data.itinerary)
    tour = Tour(
        agency_id=user.agency_profile.id,
        **data.model_dump(exclude={"itinerary", "departures"}),
    )
    tour.itinerary = [TourItineraryDay(**i.model_dump()) for i in data.itinerary]
    tour.departures = [
        Departure(start_date=d.start_date, seats_total=d.seats_total, seats_left=d.seats_total)
        for d in data.departures
    ]
    db.add(tour)
    db.commit()
    db.refresh(tour)
    return tour


def update_tour(db: Session, tour: Tour, data: TourUpdate) -> Tour:
    values = data.model_dump(exclude_unset=True)
    itinerary = values.pop("itinerary", None)
    new_status = values.pop("status", None)
    previous_price = tour.price

    for key, value in values.items():
        if value is None and key not in NULLABLE_FIELDS:
            continue
        setattr(tour, key, value)

    if tour.old_price is not None and tour.old_price <= tour.price:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Eski narx yangi narxdan katta bo'lishi kerak")

    if itinerary is not None:
        items = [ItineraryDayIn(**i) for i in itinerary]
        _check_itinerary(tour.days, items)
        tour.itinerary.clear()
        db.flush()
        tour.itinerary = [TourItineraryDay(**i.model_dump()) for i in items]
    elif "days" in values:
        _check_itinerary(
            tour.days, [ItineraryDayIn(day=i.day, title=i.title, text=i.text) for i in tour.itinerary]
        )

    if new_status is not None:
        if new_status == TourStatus.published:
            _ensure_publishable(tour)
        tour.status = new_status
    drop_ids: list[uuid.UUID] = []
    if tour.status == TourStatus.published and tour.price < previous_price:
        drop_ids = notification_service.price_drop_recipient_ids(db, tour.id)
        notification_service.notify_price_drop(db, tour, previous_price)

    db.commit()
    db.refresh(tour)
    if drop_ids:
        manager.emit(drop_ids, {"type": "notification"})
    return tour


def archive_tour(db: Session, tour: Tour) -> None:
    tour.status = TourStatus.archived
    db.commit()


# ---------- Rasmlar ----------
def add_images(db: Session, tour: Tour, files: list[UploadFile]) -> list[TourImageOut]:
    if len(tour.images) + len(files) > MAX_IMAGES_PER_TOUR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Bitta turga ko'pi bilan {MAX_IMAGES_PER_TOUR} ta rasm"
        )

    position = max((i.position for i in tour.images), default=-1) + 1
    saved_paths: list[str] = []
    created: list[TourImage] = []
    try:
        for f in files:
            path = save_image(f, f"tours/{tour.id}")
            saved_paths.append(path)
            img = TourImage(tour_id=tour.id, path=path, position=position)
            position += 1
            db.add(img)
            created.append(img)
        db.commit()
    except Exception:
        db.rollback()
        for p in saved_paths:  # yarim yuklangan fayllarni tozalaymiz
            delete_file(p)
        raise

    return [TourImageOut(id=i.id, url=media_url(i.path), position=i.position) for i in created]


def delete_image(db: Session, tour: Tour, image_id: uuid.UUID) -> None:
    image = next((i for i in tour.images if i.id == image_id), None)
    if not image:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rasm topilmadi")
    if tour.status == TourStatus.published and len(tour.images) == 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Nashr qilingan turda kamida 1 ta rasm bo'lishi kerak"
        )
    path = image.path
    db.delete(image)
    db.commit()
    delete_file(path)


# ---------- Jo'nashlar ----------
def add_departure(db: Session, tour: Tour, data: DepartureIn) -> DepartureOut:
    dep = Departure(
        tour_id=tour.id, start_date=data.start_date,
        seats_total=data.seats_total, seats_left=data.seats_total,
    )
    db.add(dep)
    db.commit()
    db.refresh(dep)
    return DepartureOut.model_validate(dep)


def delete_departure(db: Session, tour: Tour, departure_id: uuid.UUID) -> None:
    dep = next((d for d in tour.departures if d.id == departure_id), None)
    if not dep:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Jo'nash topilmadi")
    if dep.seats_left != dep.seats_total:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu jo'nashga bron qilingan, o'chirib bo'lmaydi")
    db.delete(dep)
    db.commit()


# ---------- Saqlash / sharh ----------
def _get_published(db: Session, tour_id: uuid.UUID) -> Tour:
    tour = db.get(Tour, tour_id)
    if not tour or tour.status != TourStatus.published or not tour.agency.verified:
        raise _not_found()

    return tour


def save_tour(db: Session, user: User, tour_id: uuid.UUID) -> None:
    _get_published(db, tour_id)
    db.merge(SavedTour(user_id=user.id, tour_id=tour_id))
    db.commit()


def unsave_tour(db: Session, user: User, tour_id: uuid.UUID) -> None:
    saved = db.get(SavedTour, (user.id, tour_id))
    if saved:
        db.delete(saved)
        db.commit()


def add_review(db: Session, user: User, tour_id: uuid.UUID, data: ReviewIn) -> ReviewOut:
    _get_published(db, tour_id)
    if not booking_service.has_finished_booking(db, user.id, tour_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Sharh yozish uchun avval shu turda ishtirok etishingiz kerak"
        )
    exists = db.scalar(
        select(Review).where(Review.tour_id == tour_id, Review.user_id == user.id)
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Siz bu tur uchun allaqachon sharh yozgansiz")

    review = Review(tour_id=tour_id, user_id=user.id, rating=data.rating, text=data.text.strip())
    db.add(review)
    db.commit()
    db.refresh(review)
    return ReviewOut(
        id=review.id,
        author=user.full_name,
        initials=_initials(user.full_name),
        rating=review.rating,
        date=review.created_at.date().isoformat(),
        text=review.text,
    )


def update_review(db: Session, user: User, tour_id: uuid.UUID, data: ReviewIn) -> ReviewOut:
    _get_published(db, tour_id)
    review = db.scalars(
        select(Review).where(Review.tour_id == tour_id, Review.user_id == user.id)
    ).first()
    if not review:
        return add_review(db, user, tour_id, data)
    review.rating = data.rating
    review.text = data.text.strip()
    db.commit()
    db.refresh(review)
    return ReviewOut(
        id=review.id,
        author=user.full_name,
        initials=_initials(user.full_name),
        rating=review.rating,
        date=review.created_at.date().isoformat(),
        text=review.text,
    )


def list_my_reviews(db: Session, user: User) -> list[MyReviewOut]:
    rows = db.scalars(
        select(Review)
        .options(joinedload(Review.tour).selectinload(Tour.images))
        .where(Review.user_id == user.id)
        .order_by(Review.created_at.desc())
    ).all()
    return [
        MyReviewOut(
            id=r.id,
            tour_id=r.tour_id,
            tour_title=r.tour.title,
            city=r.tour.city,
            image=media_url(r.tour.images[0].path) if r.tour.images else None,
            rating=r.rating,
            date=r.created_at.date().isoformat(),
            text=r.text,
        )
        for r in rows
    ]


def delete_my_review(db: Session, user: User, review_id: uuid.UUID) -> None:
    review = db.scalars(
        select(Review).where(Review.id == review_id, Review.user_id == user.id)
    ).first()
    if not review:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sharh topilmadi")
    db.delete(review)
    db.commit()