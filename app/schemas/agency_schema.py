import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.models.agency_model import AgencyMemberRole
from app.schemas.base import CamelModel
from app.schemas.user_schema import PHONE_PATTERN, _clean_name


class AgencyUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    license_number: str | None = Field(default=None, min_length=2, max_length=60)
    tax_id: str | None = Field(default=None, min_length=2, max_length=20)
    region: str | None = Field(default=None, min_length=2, max_length=80)
    city: str | None = Field(default=None, min_length=2, max_length=80)
    address: str | None = Field(default=None, min_length=2, max_length=255)
    contact_phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    website: str | None = Field(default=None, max_length=255)


class MemberCreate(CamelModel):
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    email: EmailStr
    phone: str = Field(pattern=PHONE_PATTERN)
    password: str = Field(min_length=8, max_length=64)

    _strip_names = field_validator("first_name", "last_name")(_clean_name)


class MemberUpdate(CamelModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=60)
    last_name: str | None = Field(default=None, min_length=1, max_length=60)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    password: str | None = Field(default=None, min_length=8, max_length=64)

    _strip_names = field_validator("first_name", "last_name")(_clean_name)


class MemberOut(CamelModel):
    user_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone: str
    role: AgencyMemberRole
    is_active: bool
    created_at: datetime