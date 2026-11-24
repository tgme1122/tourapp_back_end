import re
import uuid
from datetime import date, datetime

from pydantic import EmailStr, Field, field_validator, model_validator

from app.models.booking_model import BookingStatus
from app.schemas.base import CamelModel
from app.schemas.tour_option_schema import PolicyRule
from app.schemas.user_schema import PHONE_PATTERN
from app.time_utils import today_uz

PASSPORT_RE = re.compile(r"^[A-Z0-9]{6,12}$")


# ---------- Kirish ----------
class TravelerIn(CamelModel):
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    birth_date: date
    passport_number: str = Field(min_length=6, max_length=16)
    passport_expiry: date

    @field_validator("first_name", "last_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Bo'sh bo'lmasligi kerak")
        return v

    @field_validator("passport_number")
    @classmethod
    def clean_passport(cls, v: str) -> str:
        v = v.replace(" ", "").upper()
        if not PASSPORT_RE.match(v):
            raise ValueError("Pasport raqami noto'g'ri (masalan AB1234567)")
        return v

    @field_validator("birth_date")
    @classmethod
    def check_birth(cls, v: date) -> date:
        if v >= today_uz() or v.year < 1900:
            raise ValueError("Tug'ilgan sana noto'g'ri")
        return v

    @field_validator("passport_expiry")
    @classmethod
    def check_expiry(cls, v: date) -> date:
        if v <= today_uz():
            raise ValueError("Pasport muddati o'tgan")
        return v


class QuoteRequest(CamelModel):
    tour_id: uuid.UUID
    departure_id: uuid.UUID
    guests: int = Field(ge=1, le=10)
    addon_ids: list[uuid.UUID] = Field(default=[], max_length=20)


class BookingCreate(QuoteRequest):
    travelers: list[TravelerIn]
    accept_cancellation_policy: bool
    contact_phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    contact_email: EmailStr | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check(self):
        if not self.accept_cancellation_policy:
            raise ValueError("Bekor qilish shartlari bilan tanishib, rozilik bering")
        if len(self.travelers) != self.guests:
            raise ValueError("Sayohatchilar soni mehmonlar soniga teng bo'lishi kerak")
        numbers = [t.passport_number for t in self.travelers]
        if len(set(numbers)) != len(numbers):
            raise ValueError("Pasport raqamlari takrorlanmasligi kerak")
        return self


class BookingCancel(CamelModel):
    reason: str | None = Field(default=None, max_length=500)


# ---------- Javob ----------
class BookingAddonOut(CamelModel):
    addon_id: uuid.UUID | None = None
    name: str
    unit_price: int
    quantity: int
    total: int


class QuoteOut(CamelModel):
    tour_id: uuid.UUID
    departure_id: uuid.UUID
    start_date: date
    end_date: date
    guests: int
    unit_price: int
    base_total: int
    addons: list[BookingAddonOut]
    addons_total: int
    total: int
    seats_left: int
    available: bool
    hold_minutes: int
    cancellation_policy: list[PolicyRule]
    is_default_policy: bool


class TravelerMaskedOut(CamelModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    birth_date: date
    passport_mask: str
    passport_expiry: date


class TravelerFullOut(TravelerMaskedOut):
    passport_number: str


class CustomerOut(CamelModel):
    name: str
    phone: str
    email: str


class CancelPreviewOut(CamelModel):
    can_cancel: bool
    reason: str | None = None   # cancel qilib bo'lmasa, sababi
    paid: bool
    refund_percent: int
    refund_amount: int


class BookingOut(CamelModel):
    """Frontend `Booking` typeiga mos + qo'shimcha maydonlar."""
    id: uuid.UUID
    code: str
    tour_id: uuid.UUID
    title: str
    city: str
    country: str
    agency: str
    agency_id: uuid.UUID
    image: str | None = None
    dates: str  # "12–19 Okt 2026"
    start_date: date
    end_date: date
    departure_id: uuid.UUID
    guests: int
    unit_price: int
    addons_total: int
    total: int
    status: BookingStatus
    hold_expires_at: datetime | None = None   # faqat pending_payment da
    note: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    cancel_reason: str | None = None
    cancelled_by: str | None = None
    refund_percent: int | None = None
    refund_amount: int | None = None
    cancellation_policy: list[PolicyRule] = []
    addons: list[BookingAddonOut] = []
    travelers: list[TravelerMaskedOut] = []
    created_at: datetime
    customer: CustomerOut | None = None  # faqat agentlikka ko'rinadi