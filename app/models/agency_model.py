import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.database import Base, IdMixin, TimestampMixin
from app.models.user_model import User
from app.services.storage_service import media_url


class AgencyStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class DocumentType(str, enum.Enum):
    license = "license"
    tax_certificate = "tax_certificate"
    registration = "registration"
    director_passport = "director_passport"
    other = "other"


class AgencyMemberRole(str, enum.Enum):
    owner = "owner"        # egasi: hisobotlar, xodimlar, profil
    manager = "manager"    # agency admin: tur, bron, chat


class AgencyProfile(Base, IdMixin, TimestampMixin):
    __tablename__ = "agency_profiles"

    # Agentlikni yaratgan odam (egasi)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    name: Mapped[str] = mapped_column(String(160))
    logo_path: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)

    license_number: Mapped[str] = mapped_column(String(60))
    tax_id: Mapped[str] = mapped_column(String(20))

    region: Mapped[str] = mapped_column(String(80))
    city: Mapped[str] = mapped_column(String(80))
    address: Mapped[str] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    website: Mapped[str | None] = mapped_column(String(255))

    status: Mapped[AgencyStatus] = mapped_column(
        Enum(AgencyStatus), default=AgencyStatus.pending, index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(
        back_populates="owned_agency", foreign_keys=[user_id]
    )
    documents: Mapped[list["AgencyDocument"]] = relationship(
        back_populates="agency",
        cascade="all, delete-orphan",
        order_by="AgencyDocument.created_at",
    )
    members: Mapped[list["AgencyMember"]] = relationship(
        back_populates="agency", cascade="all, delete-orphan"
    )

    @property
    def verified(self) -> bool:
        return self.status == AgencyStatus.approved

    @property
    def logo_url(self) -> str | None:
        return media_url(self.logo_path)

    # Admin paneli uchun egasi haqida ma'lumot
    @property
    def owner_name(self) -> str:
        return self.user.full_name

    @property
    def owner_email(self) -> str:
        return self.user.email

    @property
    def owner_phone(self) -> str:
        return self.user.phone

    @property
    def email_verified(self) -> bool:
        return self.user.is_email_verified


class AgencyMember(Base, IdMixin, TimestampMixin):
    """Agentlik xodimi. Bitta odam faqat bitta agentlikda bo'ladi."""
    __tablename__ = "agency_members"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agency_profiles.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    role: Mapped[AgencyMemberRole] = mapped_column(Enum(AgencyMemberRole))

    agency: Mapped[AgencyProfile] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="membership")


class AgencyDocument(Base, IdMixin, TimestampMixin):
    __tablename__ = "agency_documents"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agency_profiles.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[DocumentType] = mapped_column(Enum(DocumentType))
    file_path: Mapped[str] = mapped_column(String(300))  # private/ ichidagi yo'l
    is_checked: Mapped[bool] = mapped_column(Boolean, default=False)

    agency: Mapped[AgencyProfile] = relationship(back_populates="documents")

    @property
    def file_url(self) -> str:
        # Ochiq fayl emas: bu API manzili, ochish uchun Authorization kerak
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        return f"{base}/agency/documents/{self.id}/file"