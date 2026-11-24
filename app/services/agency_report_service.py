from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import case, func, literal_column, select
from sqlalchemy.orm import Session

from app.models.booking_model import Booking, BookingStatus
from app.models.tour_model import Departure, Review, Tour, TourStatus
from app.models.user_model import User
from app.schemas.agency_report_schema import (
    AgencyOverviewOut, TimePointOut, ToursByStatusOut, TopTourOut,
)
from app.time_utils import UZ_TZ, today_uz

PAID = (BookingStatus.confirmed, BookingStatus.completed)


def _window(date_from: date | None, date_to: date | None):
    date_to = date_to or today_uz()
    date_from = date_from or date_to - timedelta(days=29)
    if date_from > date_to:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Boshlanish sanasi tugashdan keyin bo'lmasin"
        )
    if (date_to - date_from).days > 365:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Davr 1 yildan oshmasligi kerak")
    start = datetime.combine(date_from, time.min, tzinfo=UZ_TZ)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UZ_TZ)
    return date_from, date_to, start, end


def _booking_conds(agency_id, start, end):
    return (Tour.agency_id == agency_id, Booking.created_at >= start, Booking.created_at < end)


def _revenue_expr():
    return func.coalesce(
        func.sum(case((Booking.status.in_(PAID), Booking.total), else_=0)), 0
    )


def _guests_expr():
    return func.coalesce(
        func.sum(case((Booking.status.in_(PAID), Booking.guests), else_=0)), 0
    )


def overview(
    db: Session, user: User, date_from: date | None, date_to: date | None
) -> AgencyOverviewOut:
    agency_id = user.agency_profile.id
    date_from, date_to, start, end = _window(date_from, date_to)

    # turlar
    tours = ToursByStatusOut(**{
        s.value: c
        for s, c in db.execute(
            select(Tour.status, func.count(Tour.id))
            .where(Tour.agency_id == agency_id)
            .group_by(Tour.status)
        )
    })

    # davrdagi bronlar
    counts = {s.value: 0 for s in BookingStatus}
    guests = revenue = paid_count = 0
    rows = db.execute(
        select(
            Booking.status,
            func.count(case((Booking.status.in_(PAID), Booking.id))),
            func.coalesce(func.sum(Booking.guests), 0),
            func.coalesce(func.sum(Booking.total), 0),
        )
        .select_from(Booking)
        .join(Tour, Tour.id == Booking.tour_id)
        .where(*_booking_conds(agency_id, start, end))
        .group_by(Booking.status)
    )
    for st, cnt, g, total in rows:
        counts[st.value] = cnt
        if st in PAID:  # eski: st != BookingStatus.cancelled
            guests += int(g)
            revenue += int(total)
            paid_count += cnt
    cancelled_total = counts["cancelled"] + counts["refunded"]
    bookings_total = counts["confirmed"] + counts["completed"] + cancelled_total

    # hozirgi holat
    pending_now = db.scalar(
        select(func.count(Booking.id))
        .join(Tour, Tour.id == Booking.tour_id)
        .where(Tour.agency_id == agency_id, Booking.status == BookingStatus.pending_payment)
    ) or 0

    avg, reviews_count = db.execute(
        select(func.avg(Review.rating), func.count(Review.id))
        .join(Tour, Tour.id == Review.tour_id)
        .where(Tour.agency_id == agency_id)
    ).one()

    dep_count, seats_total, seats_left = db.execute(
        select(
            func.count(Departure.id),
            func.coalesce(func.sum(Departure.seats_total), 0),
            func.coalesce(func.sum(Departure.seats_left), 0),
        )
        .join(Tour, Tour.id == Departure.tour_id)
        .where(
            Tour.agency_id == agency_id,
            Tour.status == TourStatus.published,
            Departure.start_date >= today_uz(),
        )
    ).one()
    seats_total, seats_left = int(seats_total), int(seats_left)

    return AgencyOverviewOut(
        date_from=date_from, date_to=date_to, tours=tours,
        bookings_total=bookings_total,
        pending=counts["pending_payment"], confirmed=counts["confirmed"],
        completed=counts["completed"], cancelled=cancelled_total,
        guests=guests, revenue=revenue,
        avg_booking_value=revenue // paid_count if paid_count else 0,
        cancel_rate=round(cancelled_total / bookings_total, 3) if bookings_total else 0.0,
        pending_now=pending_now,
        rating=round(float(avg), 1) if avg else 0.0,
        reviews_count=reviews_count,
        upcoming_departures=dep_count, seats_total=seats_total, seats_left=seats_left,
        occupancy=round(1 - seats_left / seats_total, 3) if seats_total else 0.0,
    )


def timeseries(
    db: Session, user: User, date_from: date | None, date_to: date | None,
    group: Literal["day", "month"],
) -> list[TimePointOut]:
    agency_id = user.agency_profile.id
    date_from, date_to, start, end = _window(date_from, date_to)
    if group == "day" and (date_to - date_from).days > 92:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Kunlik ko'rinish uchun davr 93 kundan oshmasin"
        )

    # group faqat Literal["day","month"], shuning uchun SQL ichiga qo'yish xavfsiz
    bucket = func.date_trunc(
        literal_column(f"'{group}'"), func.timezone("Asia/Tashkent", Booking.created_at)
    )
    rows = db.execute(
        select(
            bucket.label("b"),
            func.count(case((Booking.status.in_(PAID), Booking.id))),
            _guests_expr(),
            _revenue_expr(),
        )
        .select_from(Booking)
        .join(Tour, Tour.id == Booking.tour_id)
        .where(*_booking_conds(agency_id, start, end))
        .group_by(bucket)
        .order_by(bucket)
    )
    data = {
        (b.date().isoformat() if group == "day" else b.strftime("%Y-%m")): (int(c), int(g), int(r))
        for b, c, g, r in rows
    }

    if group == "month":
        return [
            TimePointOut(period=k, bookings=v[0], guests=v[1], revenue=v[2])
            for k, v in sorted(data.items())
        ]

    points, d = [], date_from  # bo'sh kunlarni nol bilan to'ldiramiz
    while d <= date_to:
        c, g, r = data.get(d.isoformat(), (0, 0, 0))
        points.append(TimePointOut(period=d.isoformat(), bookings=c, guests=g, revenue=r))
        d += timedelta(days=1)
    return points

def top_tours(
    db: Session, user: User, date_from: date | None, date_to: date | None, limit: int
) -> list[TopTourOut]:
    agency_id = user.agency_profile.id
    _, _, start, end = _window(date_from, date_to)
    revenue = _revenue_expr()
    rows = db.execute(
        select(
            Tour.id,
            Tour.title,
            func.count(case((Booking.status.in_(PAID), Booking.id))),
            _guests_expr(),
            revenue,
        )
        .select_from(Booking)
        .join(Tour, Tour.id == Booking.tour_id)
        .where(*_booking_conds(agency_id, start, end))
        .group_by(Tour.id, Tour.title)
        .order_by(revenue.desc(), Tour.id)
        .limit(limit)
    )
    return [
        TopTourOut(tour_id=tid, title=title, bookings=int(c), guests=int(g), revenue=int(r))
        for tid, title, c, g, r in rows
    ]