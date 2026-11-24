import uuid
from datetime import datetime, date

from pydantic import Field, field_validator

from app.models import TourCategory, TourStatus
from app.schemas.base import CamelModel
from app.schemas.tour_schema import TourDetailsOut
from app.schemas.user_schema import AgencyProfileOut
from  app.schemas.user_schema import UserRole , AgencyStatus



class AdminAgencyOut(AgencyProfileOut):
    owner_name: str
    owner_email: str
    owner_phone: str
    email_verified: bool
    created_at: datetime
    reviewed_at: datetime | None = None


class AgencyCountsOut(CamelModel):
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    suspended: int = 0


class ReasonRequest(CamelModel):
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 5:
            raise ValueError("Sabab kamida 5 belgi bo'lsin")
        return v


class DocumentCheck(CamelModel):
    is_checked: bool


class PromoCreate(CamelModel):
    title: str = Field(min_length=3, max_length=200)
    text: str = Field(min_length=3, max_length=500)
    tour_id: uuid.UUID | None = None


class PromoResultOut(CamelModel):
    sent: int

class AdminUserOut(CamelModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone: str
    avatar_url: str | None
    role: UserRole
    language: str
    is_active: bool
    is_email_verified: bool
    created_at: datetime
    # faqat agency uchun
    agency_id: uuid.UUID | None = None
    agency_name: str | None = None
    agency_status: AgencyStatus | None = None


class UserBookingItem(CamelModel):
    id: uuid.UUID
    tour_id: uuid.UUID
    tour_title: str
    guests: int
    status: str
    total: int
    created_at: datetime


class UserReviewItem(CamelModel):
    id: uuid.UUID
    tour_title: str
    rating: int
    text: str
    created_at: datetime


class UserTourItem(CamelModel):
    id: uuid.UUID
    title: str
    city: str
    price: int
    status: str


class AdminUserDetailOut(AdminUserOut):
    bookings: list[UserBookingItem] = []    # shu foydalanuvchi qilgan bronlar
    reviews: list[UserReviewItem] = []
    saved_tours: list[UserTourItem] = []
    tours: list[UserTourItem] = []          # agency bo'lsa: uning turlari


class UserCountsOut(CamelModel):
    total: int = 0
    travelers: int = 0
    agencies: int = 0
    admins: int = 0
    active: int = 0
    blocked: int = 0

class AdminTourOut(CamelModel):
    id: uuid.UUID
    title: str
    city: str
    country: str
    category: TourCategory
    status: TourStatus
    days: int
    price: int
    old_price: int | None = None
    hot: bool
    trending: bool
    image: str | None = None
    agency_id: uuid.UUID
    agency_name: str
    agency_status: AgencyStatus
    rating: float
    reviews_count: int
    bookings_count: int
    next_departure: str | None = None   # eng yaqin jo'nash (ISO sana)
    seats_left: int | None = None       # kelajakdagi jo'nashlar bo'yicha jami
    created_at: datetime


class TourBookingStatsOut(CamelModel):
    pending: int = 0
    confirmed: int = 0
    completed: int = 0
    cancelled: int = 0
    guests: int = 0
    revenue: int = 0


class AdminTourDetailOut(AdminTourOut):
    details: TourDetailsOut
    booking_stats: TourBookingStatsOut


class TourCountsOut(CamelModel):
    total: int = 0
    draft: int = 0
    published: int = 0
    archived: int = 0


class AdminTourBookingOut(CamelModel):
    id: uuid.UUID
    code: str
    status: str
    guests: int
    unit_price: int
    total: int
    start_date: date
    customer_name: str
    customer_phone: str
    customer_email: str
    created_at: datetime