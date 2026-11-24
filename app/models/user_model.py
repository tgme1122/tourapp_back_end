import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, IdMixin, TimestampMixin
from app.services.storage_service import media_url


class UserRole(str, enum.Enum):
    traveler = "traveler"
    agency = "agency"
    admin = "admin"


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"

    first_name: Mapped[str] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(60))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    avatar_path: Mapped[str | None] = mapped_column(String(300))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.traveler)
    language: Mapped[str] = mapped_column(String(5), default="uz")  # uz | ru | en

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    # Profil sahifasidagi togglelar
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    price_drop_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    agency_messages_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Agentlikni yaratgan odam (egasi) bo'lsa
    owned_agency: Mapped["AgencyProfile | None"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="AgencyProfile.user_id",
    )
    # Agentlik a'zoligi (egasi ham, manager ham)
    membership: Mapped["AgencyMember | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def agency_profile(self) -> "AgencyProfile | None":
        return self.membership.agency if self.membership else None

    @property
    def agency_role(self):
        return self.membership.role if self.membership else None

    @property
    def full_name(self) -> str:  # bazada saqlanmaydi
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def avatar_url(self) -> str | None:
        return media_url(self.avatar_path)


class EmailCode(Base, IdMixin, TimestampMixin):
    __tablename__ = "email_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64))  # kodning o'zi saqlanmaydi
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)