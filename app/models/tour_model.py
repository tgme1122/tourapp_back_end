import enum
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import (
    ARRAY, BigInteger, Boolean, CheckConstraint, Date, DateTime, Enum,
    ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, IdMixin, TimestampMixin
from app.models.agency_model import AgencyProfile
from app.models.user_model import User


class TourCategory(str, enum.Enum):
    sea = "sea"
    mountain = "mountain"
    city = "city"
    culture = "culture"


class TourStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class Tour(Base, IdMixin, TimestampMixin):
    __tablename__ = "tours"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_tour_price"),
        CheckConstraint("days > 0", name="ck_tour_days"),
    )

    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agency_profiles.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(80), index=True)
    country: Mapped[str] = mapped_column(String(80), index=True)
    category: Mapped[TourCategory] = mapped_column(Enum(TourCategory), index=True)
    days: Mapped[int] = mapped_column(Integer)
    price: Mapped[int] = mapped_column(BigInteger)  # so'mda
    old_price: Mapped[int | None] = mapped_column(BigInteger)

    hotel: Mapped[str | None] = mapped_column(String(200))
    meals: Mapped[str | None] = mapped_column(String(120))
    transport: Mapped[str | None] = mapped_column(String(120))
    group_size: Mapped[str | None] = mapped_column(String(60))
    language: Mapped[str | None] = mapped_column(String(60))
    included: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    excluded: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    hot: Mapped[bool] = mapped_column(Boolean, default=False)
    trending: Mapped[bool] = mapped_column(Boolean, default=False)  # keyinchalik admin/hisob
    status: Mapped[TourStatus] = mapped_column(
        Enum(TourStatus), default=TourStatus.draft, index=True
    )
    bookings_count: Mapped[int] = mapped_column(Integer, default=0)  # "popular" saralash uchun

    agency: Mapped[AgencyProfile] = relationship()
    images: Mapped[list["TourImage"]] = relationship(
        back_populates="tour", cascade="all, delete-orphan", order_by="TourImage.position"
    )
    itinerary: Mapped[list["TourItineraryDay"]] = relationship(
        back_populates="tour", cascade="all, delete-orphan", order_by="TourItineraryDay.day"
    )
    departures: Mapped[list["Departure"]] = relationship(
        back_populates="tour", cascade="all, delete-orphan", order_by="Departure.start_date"
    )
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="tour", cascade="all, delete-orphan"
    )


class TourImage(Base, IdMixin):
    __tablename__ = "tour_images"

    tour_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tours.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(300))
    position: Mapped[int] = mapped_column(Integer, default=0)  # 0 = muqova rasmi

    tour: Mapped[Tour] = relationship(back_populates="images")


class TourItineraryDay(Base, IdMixin):
    __tablename__ = "tour_itinerary_days"

    tour_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tours.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)

    tour: Mapped[Tour] = relationship(back_populates="itinerary")


class Departure(Base, IdMixin):
    __tablename__ = "tour_departures"
    __table_args__ = (
        CheckConstraint(
            "seats_left >= 0 AND seats_left <= seats_total", name="ck_departure_seats"
        ),
    )

    tour_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tours.id", ondelete="CASCADE"), index=True
    )
    start_date: Mapped[date] = mapped_column(Date, index=True)
    seats_total: Mapped[int] = mapped_column(Integer)
    seats_left: Mapped[int] = mapped_column(Integer)

    tour: Mapped[Tour] = relationship(back_populates="departures")

    @property
    def start_iso(self) -> str:  # frontend: startISO
        return self.start_date.isoformat()

    @property
    def end_date(self) -> date:  # tugash sanasi = boshlanish + (kunlar - 1)
        return self.start_date + timedelta(days=max(self.tour.days, 1) - 1)

    @property
    def end_iso(self) -> str:  # frontend: endISO
        return self.end_date.isoformat()


class Review(Base, IdMixin, TimestampMixin):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("tour_id", "user_id", name="uq_review_tour_user"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating"),
    )

    tour_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tours.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    tour: Mapped[Tour] = relationship(back_populates="reviews")
    user: Mapped[User] = relationship()


class SavedTour(Base):
    __tablename__ = "saved_tours"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tour_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tours.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )