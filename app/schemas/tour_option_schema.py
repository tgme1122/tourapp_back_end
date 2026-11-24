import uuid

from pydantic import Field, field_validator

from app.schemas.base import CamelModel


class AddonIn(CamelModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    price: int = Field(gt=0, le=1_000_000_000)
    per_person: bool = True
    is_active: bool = True


class AddonUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    price: int | None = Field(default=None, gt=0, le=1_000_000_000)
    per_person: bool | None = None
    is_active: bool | None = None


class AddonOut(CamelModel):
    id: uuid.UUID
    name: str
    description: str | None
    price: int
    per_person: bool
    is_active: bool


class PolicyRule(CamelModel):
    """Jo'nashgacha kamida `daysBefore` kun qolgan bo'lsa, `refundPercent` qaytariladi."""
    days_before: int = Field(ge=0, le=365)
    refund_percent: int = Field(ge=0, le=100)


class PolicyIn(CamelModel):
    rules: list[PolicyRule] = Field(max_length=6)  # bo'sh bo'lsa default shart ishlaydi

    @field_validator("rules")
    @classmethod
    def check(cls, v: list[PolicyRule]) -> list[PolicyRule]:
        days = [r.days_before for r in v]
        if len(set(days)) != len(days):
            raise ValueError("Kunlar takrorlanmasligi kerak")
        ordered = sorted(v, key=lambda r: -r.days_before)
        for a, b in zip(ordered, ordered[1:]):
            if b.refund_percent > a.refund_percent:
                raise ValueError("Jo'nash yaqinlashgan sari qaytariladigan ulush oshmasligi kerak")
        return ordered


class PolicyOut(CamelModel):
    rules: list[PolicyRule]
    is_default: bool


class BookingOptionsOut(CamelModel):
    addons: list[AddonOut]
    cancellation_policy: list[PolicyRule]
    is_default_policy: bool
    hold_minutes: int