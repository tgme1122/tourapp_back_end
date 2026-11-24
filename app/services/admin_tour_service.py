import uuid
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.agency_model import AgencyProfile
from app.models.booking_model import Booking, BookingStatus
from app.models.tour_model import Departure, Review, Tour, TourCategory, TourStatus
from app.schemas.admin_schema import (
    AdminTourBookingOut, AdminTourDetailOut, AdminTourOut, TourBookingStatsOut,
    TourCountsOut,
)
from app.schemas.tour_schema import (
    DepartureOut, ItineraryDayOut, ReviewOut, TourDetailsOut, TourImageOut,
)
from app.services.storage_service import media_url
from app.services.tour_service import _initials
from app.time_utils import today_uz


def _stmt():
    reviews = (
        select(
            Review.tour_id.label("tour_id"),
            func.avg(Review.rating).label("avg_rating"),
            func.count(Review.id).label("cnt"),
        )
        .group_by(Review.tour_id)
        .subquery()
    )
    stmt = (
        select(Tour, reviews.c.avg_rating, reviews.c.cnt)
        .outerjoin(reviews, reviews.c.tour_id == Tour.id)
        .options(selectinload(Tour.images), joinedload(Tour.agency))
    )
    return stmt, reviews


def _departure_info(db: Session, tour_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[date, int]]:
    """Har tur uchun: eng yaqin jo'nash sanasi va kelajakdagi jami bo'sh joylar."""
    rows = db.execute(
        select(
            Departure.tour_id,
            func.min(Departure.start_date),
            func.sum(Departure.seats_left),
        )
        .where(Departure.tour_id.in_(tour_ids), Departure.start_date >= today_uz())
        .group_by(Departure.tour_id)
    )
    return {tid: (d, int(s or 0)) for tid, d, s in rows}


def _to_out(row, info) -> AdminTourOut:
    tour, avg, cnt = row
    nxt, seats = info.get(tour.id, (None, None))
    return AdminTourOut(
        id=tour.id, title=tour.title, city=tour.city, country=tour.country,
        category=tour.category, status=tour.status, days=tour.days,
        price=tour.price, old_price=tour.old_price, hot=tour.hot,
        trending=tour.trending,
        image=media_url(tour.images[0].path) if tour.images else None,
        agency_id=tour.agency_id, agency_name=tour.agency.name,
        agency_status=tour.agency.status,
        rating=round(float(avg), 1) if avg else 0.0,
        reviews_count=cnt or 0,
        bookings_count=tour.bookings_count,
        next_departure=nxt.isoformat() if nxt else None,
        seats_left=seats,
        created_at=tour.created_at,
    )


def list_tours(
    db: Session,
    status_filter: TourStatus | None,
    agency_id: uuid.UUID | None,
    category: TourCategory | None,
    country: str | None,
    q: str | None,
    sort: str,
    limit: int,
    offset: int,
) -> list[AdminTourOut]:
    stmt, reviews = _stmt()
    if status_filter:
        stmt = stmt.where(Tour.status == status_filter)
    if agency_id:
        stmt = stmt.where(Tour.agency_id == agency_id)
    if category:
        stmt = stmt.where(Tour.category == category)
    if country:
        stmt = stmt.where(func.lower(Tour.country) == country.lower())
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.join(AgencyProfile, AgencyProfile.id == Tour.agency_id).where(
            or_(
                Tour.title.ilike(like), Tour.city.ilike(like),
                Tour.country.ilike(like), AgencyProfile.name.ilike(like),
            )
        )

    if sort == "bookings":
        stmt = stmt.order_by(Tour.bookings_count.desc(), Tour.id)
    elif sort == "price":
        stmt = stmt.order_by(Tour.price.asc(), Tour.id)
    elif sort == "rating":
        stmt = stmt.order_by(func.coalesce(reviews.c.avg_rating, 0).desc(), Tour.id)
    else:  # newest
        stmt = stmt.order_by(Tour.created_at.desc(), Tour.id)

    rows = db.execute(stmt.limit(limit).offset(offset)).all()
    info = _departure_info(db, [r[0].id for r in rows]) if rows else {}
    return [_to_out(r, info) for r in rows]


def counts(db: Session) -> TourCountsOut:
    rows = db.execute(select(Tour.status, func.count(Tour.id)).group_by(Tour.status))
    data = {s.value: c for s, c in rows}
    return TourCountsOut(total=sum(data.values()), **data)


def get_detail(db: Session, tour_id: uuid.UUID) -> AdminTourDetailOut:
    stmt, _ = _stmt()
    stmt = stmt.options(
        selectinload(Tour.itinerary), selectinload(Tour.departures)
    ).where(Tour.id == tour_id)
    row = db.execute(stmt).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tour topilmadi")
    tour = row[0]
    base = _to_out(row, _departure_info(db, [tour.id]))

    reviews = db.scalars(
        select(Review)
        .options(joinedload(Review.user))
        .where(Review.tour_id == tour.id)
        .order_by(Review.created_at.desc())
    ).all()

    details = TourDetailsOut(
        gallery=[media_url(i.path) for i in tour.images],
        images=[TourImageOut(id=i.id, url=media_url(i.path), position=i.position) for i in tour.images],
        description=tour.description,
        hotel=tour.hotel, meals=tour.meals, transport=tour.transport,
        group_size=tour.group_size, language=tour.language,
        included=tour.included or [], excluded=tour.excluded or [],
        itinerary=[ItineraryDayOut.model_validate(i) for i in tour.itinerary],
        # admin o'tgan jo'nashlarni ham ko'radi
        departures=[DepartureOut.model_validate(d) for d in tour.departures],
        reviews=[
            ReviewOut(
                id=r.id, author=r.user.full_name, initials=_initials(r.user.full_name),
                rating=r.rating, date=r.created_at.date().isoformat(), text=r.text,
            )
            for r in reviews
        ],
    )
    return AdminTourDetailOut(
        **base.model_dump(), details=details, booking_stats=_booking_stats(db, tour.id)
    )


def _booking_stats(db: Session, tour_id: uuid.UUID) -> TourBookingStatsOut:
    paid = (BookingStatus.confirmed, BookingStatus.completed)
    rows = db.execute(
        select(Booking.status, func.count(Booking.id), func.sum(Booking.guests),
               func.sum(Booking.total))
        .where(Booking.tour_id == tour_id)
        .group_by(Booking.status)
    )
    out = TourBookingStatsOut()
    for st, cnt, guests, total in rows:
        key = {"pending_payment": "pending", "refunded": "cancelled"}.get(st.value, st.value)
        if key in ("pending", "confirmed", "completed", "cancelled"):
            setattr(out, key, getattr(out, key) + cnt)
        if st in paid:
            out.guests += int(guests or 0)
            out.revenue += int(total or 0)
    return out


def tour_bookings(
    db: Session, tour_id: uuid.UUID, status_filter: BookingStatus | None,
    limit: int, offset: int,
) -> list[AdminTourBookingOut]:
    if not db.scalar(select(Tour.id).where(Tour.id == tour_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tour topilmadi")
    stmt = (
        select(Booking)
        .options(joinedload(Booking.user), joinedload(Booking.departure))
        .where(Booking.tour_id == tour_id)
    )
    if status_filter:
        stmt = stmt.where(Booking.status == status_filter)
    stmt = stmt.order_by(Booking.created_at.desc(), Booking.id).limit(limit).offset(offset)
    return [
        AdminTourBookingOut(
            id=b.id, code=b.code, status=b.status.value, guests=b.guests,
            unit_price=b.unit_price, total=b.total,
            start_date=b.departure.start_date,
            customer_name=b.user.full_name, customer_phone=b.user.phone,
            customer_email=b.user.email, created_at=b.created_at,
        )
        for b in db.scalars(stmt)
    ]