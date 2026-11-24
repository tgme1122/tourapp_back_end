import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.models.agency_model import AgencyMemberRole, AgencyStatus, DocumentType
from app.models.user_model import UserRole
from app.schemas.base import CamelModel

PHONE_PATTERN = r"^\+998\d{9}$"


def _clean_name(v: str | None) -> str | None:
    if v is None:
        return v
    v = " ".join(v.split())  # ortiqcha bo'sh joylarni olib tashlaydi
    if not v:
        raise ValueError("Bo'sh bo'lmasligi kerak")
    return v


# ---------- Ro'yxatdan o'tish ----------
class TravelerRegister(CamelModel):
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    email: EmailStr
    phone: str = Field(pattern=PHONE_PATTERN)
    password: str = Field(min_length=8, max_length=64)

    _strip_names = field_validator("first_name", "last_name")(_clean_name)


class AgencyRegister(TravelerRegister):
    agency_name: str = Field(min_length=2, max_length=160)
    license_number: str
    tax_id: str
    region: str
    city: str
    address: str
    contact_phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    website: str | None = None
    description: str | None = None


# ---------- Profilni yangilash ----------
class UserUpdate(CamelModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=60)
    last_name: str | None = Field(default=None, min_length=1, max_length=60)
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    language: str | None = Field(default=None, pattern="^(uz|ru|en)$")

    _strip_names = field_validator("first_name", "last_name")(_clean_name)


class NotificationSettingsUpdate(CamelModel):
    push_enabled: bool | None = None
    price_drop_enabled: bool | None = None
    agency_messages_enabled: bool | None = None


class ChangePassword(CamelModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=64)


class ProfileStatsOut(CamelModel):
    saved_tours: int
    bookings: int
    reviews: int


# ---------- Javoblar ----------
class AgencyDocumentOut(CamelModel):
    id: uuid.UUID
    type: DocumentType
    file_url: str
    is_checked: bool


class AgencyProfileOut(CamelModel):
    id: uuid.UUID
    name: str
    logo_url: str | None
    description: str | None
    license_number: str
    tax_id: str
    region: str
    city: str
    address: str
    contact_phone: str | None
    website: str | None
    status: AgencyStatus
    verified: bool
    rejection_reason: str | None
    documents: list[AgencyDocumentOut] = []


class UserOut(CamelModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    avatar_url: str | None
    role: UserRole
    language: str
    is_email_verified: bool
    push_enabled: bool
    price_drop_enabled: bool
    agency_messages_enabled: bool
    created_at: datetime
    agency_role: AgencyMemberRole | None = None   # owner | manager
    agency_profile: AgencyProfileOut | None = None