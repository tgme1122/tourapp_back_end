import uuid
from datetime import datetime
from typing import Literal

from app.models.notification_model import NotificationType
from app.schemas.base import CamelModel


class NotificationTargetOut(CamelModel):
    kind: Literal["tour", "bookings", "chat"]
    id: uuid.UUID | None = None  # "bookings" uchun null


class NotificationOut(CamelModel):
    """Frontend `AppNotification` typeiga mos."""
    id: uuid.UUID
    type: NotificationType
    title: str
    text: str
    time: datetime
    day: Literal["Bugun", "Kecha", "Avvalroq"]
    read: bool
    target: NotificationTargetOut | None = None


class UnreadCountOut(CamelModel):
    count: int