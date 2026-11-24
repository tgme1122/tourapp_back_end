import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user_model import User
from app.schemas.notification_schema import NotificationOut, UnreadCountOut
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def my_notifications(
    unread_only: bool = Query(False, alias="unreadOnly"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return notification_service.list_notifications(db, user, unread_only, limit, offset)


# "/{notification_id}" dan OLDIN turishi kerak
@router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return UnreadCountOut(count=notification_service.unread_count(db, user))


@router.post("/read-all", status_code=204)
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notification_service.mark_all_read(db, user)
    return Response(status_code=204)


@router.post("/{notification_id}/read", status_code=204)
def read_one(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification_service.mark_read(db, user, notification_id)
    return Response(status_code=204)


@router.delete("/{notification_id}", status_code=204)
def delete_one(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification_service.delete_notification(db, user, notification_id)
    return Response(status_code=204)