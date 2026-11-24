import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, IdMixin, TimestampMixin
from app.models.agency_model import AgencyProfile
from app.models.tour_model import Tour
from app.models.user_model import User


class MessageType(str, enum.Enum):
    text = "text"
    image = "image"
    voice = "voice"
    file = "file"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base, IdMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("user_id", "agency_id", "tour_id", name="uq_conversation_participants"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agency_profiles.id", ondelete="CASCADE"), index=True
    )
    tour_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tours.id", ondelete="RESTRICT"), index=True
    )

    # Ro'yxatni tez chiqarish uchun oxirgi xabar nusxasi
    last_message_text: Mapped[str | None] = mapped_column(String(200))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    user: Mapped[User] = relationship()
    agency: Mapped[AgencyProfile] = relationship()
    tour: Mapped[Tour] = relationship()
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base, IdMixin):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conv_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE")
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[MessageType] = mapped_column(
        Enum(MessageType), default=MessageType.text, server_default="text"
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_path: Mapped[str | None] = mapped_column(String(300))
    attachment_name: Mapped[str | None] = mapped_column(String(200))
    attachment_mime: Mapped[str | None] = mapped_column(String(100))
    attachment_size: Mapped[int | None] = mapped_column(Integer)
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped[Conversation] = relationship(back_populates="messages")