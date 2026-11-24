import uuid
from datetime import date
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.models.tour_model import TourCategory, TourStatus
from app.schemas.base import CamelModel
from app.time_utils import today_uz

SortKey = Literal["cheap", "popular", "rating"]
PriceRangeKey = Literal["lt1", "1to5", "5to10", "gt10"]
DurationKey = Literal["short", "mid", "long"]


# ---------- Kirish ----------
class ItineraryDayIn(CamelModel):
    day: int = Field(ge=1, le=60)
    title: str = Field(min_length=2, max_length=200)
    text: str = Field(min_length=2)


class DepartureIn(CamelModel):
    start_date: date
    seats_total: int = Field(ge=1, le=500)

    @field_validator("start_date")
    @classmethod
    def not_in_past(cls, v: date) -> date:
        if v < today_uz():
            raise ValueError("Jo'nash sanasi o'tmishda bo'lishi mumkin emas")
        return v


class TourCreate(CamelModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10)
    city: str = Field(min_length=2, max_length=80)
    country: str = Field(min_length=2, max_length=80)
    category: TourCategory
    days: int = Field(ge=1, le=60)
    price: int = Field(gt=0)
    old_price: int | None = Field(default=None, gt=0)
    hotel: str | None = None
    meals: str | None = None
    transport: str | None = None
    group_size: str | None = None
    language: str | None = None
    included: list[str] = []
    excluded: list[str] = []
    hot: bool = False
    itinerary: list[ItineraryDayIn] = []
    departures: list[DepartureIn] = []

    @model_validator(mode="after")
    def check_old_price(self):
        if self.old_price is not None and self.old_price <= self.price:
            raise ValueError("Eski narx yangi narxdan katta bo'lishi kerak")
        return self


class TourUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=10)
    city: str | None = Field(default=None, min_length=2, max_length=80)
    country: str | None = Field(default=None, min_length=2, max_length=80)
    category: TourCategory | None = None
    days: int | None = Field(default=None, ge=1, le=60)
    price: int | None = Field(default=None, gt=0)
    old_price: int | None = Field(default=None, gt=0)
    hotel: str | None = None
    meals: str | None = None
    transport: str | None = None
    group_size: str | None = None
    language: str | None = None
    included: list[str] | None = None
    excluded: list[str] | None = None
    hot: bool | None = None
    itinerary: list[ItineraryDayIn] | None = None  # yuborilsa to'liq almashtiriladi
    status: TourStatus | None = None


class ReviewIn(CamelModel):
    rating: int = Field(ge=1, le=5)
    text: str = Field(default="", max_length=1000)


# ---------- Javob ----------
class TourCardOut(CamelModel):
    """Frontend `Tour` typeiga mos."""
    id: uuid.UUID
    city: str
    country: str
    title: str
    agency: str
    agency_id: uuid.UUID
    agency_verified: bool
    agency_rating: float
    rating: float
    reviews: int
    days: int
    price: int
    old_price: int | None = None
    seats_left: int | None = None
    category: TourCategory
    image: str | None = None
    hot: bool = False
    trending: bool = False
    is_saved: bool = False


class MyTourOut(TourCardOut):
    status: TourStatus


class ItineraryDayOut(CamelModel):
    day: int
    title: str
    text: str


class DepartureOut(CamelModel):
    id: uuid.UUID
    start_iso: str = Field(serialization_alias="startISO")
    end_iso: str = Field(serialization_alias="endISO")
    seats_left: int
    seats_total: int


class ReviewOut(CamelModel):
    id: uuid.UUID
    author: str
    initials: str
    rating: int
    date: str  # ISO: "2026-10-12", frontend formatlaydi
    text: str


class MyReviewOut(CamelModel):
    id: uuid.UUID
    tour_id: uuid.UUID
    tour_title: str
    city: str
    image: str | None = None
    rating: int
    date: str
    text: str


class TourImageOut(CamelModel):
    id: uuid.UUID
    url: str
    position: int


class TourDetailsOut(CamelModel):
    """Frontend `TourDetails` typeiga mos."""
    gallery: list[str]
    images: list[TourImageOut] = []
    description: str
    hotel: str | None
    meals: str | None
    transport: str | None
    group_size: str | None
    language: str | None
    included: list[str]
    excluded: list[str]
    itinerary: list[ItineraryDayOut]
    departures: list[DepartureOut]
    reviews: list[ReviewOut]


class TourDetailResponse(CamelModel):
    tour: TourCardOut
    details: TourDetailsOut
    status: TourStatus