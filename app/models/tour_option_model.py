import uuid

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, IdMixin, TimestampMixin


class TourAddon(Base, IdMixin, TimestampMixin):
    """Agentlik kiritadigan ixtiyoriy xizmat (transfer, sug'urta, ekskursiya)."""
    __tablename__ = "tour_addons"
    __table_args__ = (CheckConstraint("price > 0", name="ck_addon_price"),)

    tour_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tours.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(300))
    price: Mapped[int] = mapped_column(BigInteger)
    per_person: Mapped[bool] = mapped_column(Boolean, default=True)  # False = bron uchun bir marta
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class TourCancellationRule(Base, IdMixin):
    """Jo'nashgacha kamida `days_before` kun qolgan bo'lsa, `refund_percent` qaytariladi."""
    __tablename__ = "tour_cancellation_rules"
    __table_args__ = (
        UniqueConstraint("tour_id", "days_before", name="uq_rule_tour_days"),
        CheckConstraint("refund_percent BETWEEN 0 AND 100", name="ck_rule_percent"),
        CheckConstraint("days_before >= 0", name="ck_rule_days"),
    )

    tour_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tours.id", ondelete="CASCADE"), index=True
    )
    days_before: Mapped[int] = mapped_column(Integer)
    refund_percent: Mapped[int] = mapped_column(Integer)