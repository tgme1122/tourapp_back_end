import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.models.chat_model import MessageType
from app.schemas.base import CamelModel


class ConversationCreate(CamelModel):
    tour_id: uuid.UUID
    message: str | None = Field(default=None, max_length=2000)


class MessageCreate(CamelModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Xabar bo'sh bo'lmasligi kerak")
        return v


class ConversationOut(CamelModel):
    """Frontend `Conversation` typeiga mos."""
    id: uuid.UUID
    agency: str          # qarshi tomon nomi (foydalanuvchiga: agentlik, agentlikka: mijoz)
    initials: str
    verified: bool
    online: bool
    tour_id: uuid.UUID
    tour_title: str
    last_message: str
    time: datetime
    unread: int


class AttachmentOut(CamelModel):
    url: str
    name: str | None = None
    mime: str | None = None
    size: int | None = None
    duration_sec: int | None = None


class MessageOut(CamelModel):
    """Frontend `Message` typeiga mos."""
    id: uuid.UUID
    type: MessageType = MessageType.text
    text: str
    attachment: AttachmentOut | None = None
    mine: bool
    time: datetime
    read: bool


class UnreadCountOut(CamelModel):
    count: int