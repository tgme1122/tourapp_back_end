import uuid
from datetime import date

from app.schemas.base import CamelModel


class ToursByStatusOut(CamelModel):
    draft: int = 0
    published: int = 0
    archived: int = 0


class AgencyOverviewOut(CamelModel):
    date_from: date
    date_to: date
    tours: ToursByStatusOut
    # tanlangan davrda yaratilgan bronlar
    bookings_total: int
    pending: int
    confirmed: int
    completed: int
    cancelled: int
    guests: int                # bekor qilinmagan bronlardagi mehmonlar
    revenue: int               # confirmed + completed summasi (so'm)
    avg_booking_value: int
    cancel_rate: float         # 0..1
    # hozirgi holat (davrga bog'liq emas)
    pending_now: int           # tasdiqlashni kutayotgan bronlar
    rating: float
    reviews_count: int
    upcoming_departures: int
    seats_total: int
    seats_left: int
    occupancy: float           # 0..1, kelgusi jo'nashlar to'lish darajasi


class TimePointOut(CamelModel):
    period: str                # "2026-10-12" yoki "2026-10"
    bookings: int              # bekor qilinmaganlar
    guests: int
    revenue: int


class TopTourOut(CamelModel):
    tour_id: uuid.UUID
    title: str
    bookings: int
    guests: int
    revenue: int