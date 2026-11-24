import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_optional_user, require_roles
from app.models.chat_model import MessageType
from app.models.user_model import User, UserRole
from app.schemas.chat_schema import (
    ConversationCreate, ConversationOut, MessageCreate, MessageOut, UnreadCountOut,
)
from app.services import chat_service

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=list[ConversationOut])
def my_conversations(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return chat_service.list_conversations(db, user, limit, offset)


@router.post("", response_model=ConversationOut)
def start_conversation(
    data: ConversationCreate,
    user: User = Depends(require_roles(UserRole.traveler)),
    db: Session = Depends(get_db),
):
    return chat_service.start_conversation(db, user, data.tour_id, data.message)


# "/{conversation_id}" dan OLDIN turishi kerak
@router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return UnreadCountOut(count=chat_service.unread_total(db, user))


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def messages(
    conversation_id: uuid.UUID,
    before: datetime | None = None,
    after: datetime | None = None,
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return chat_service.list_messages(db, user, conversation_id, before, after, limit)


@router.post("/{conversation_id}/messages", response_model=MessageOut, status_code=201)
def send_message(
    conversation_id: uuid.UUID,
    data: MessageCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return chat_service.send_message(db, user, conversation_id, data.text)


@router.post("/{conversation_id}/attachments", response_model=MessageOut, status_code=201)
def send_attachment(
    conversation_id: uuid.UUID,
    type: MessageType = Form(...),
    file: UploadFile = File(...),
    text: str | None = Form(default=None),
    duration_sec: int | None = Form(default=None, alias="durationSec"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return chat_service.send_attachment(
        db, user, conversation_id, type, file, text=text, duration_sec=duration_sec
    )


@router.get("/{conversation_id}/attachments/{message_id}")
def download_attachment(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    ticket: str | None = None,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    path, mime, filename, inline = chat_service.get_attachment(
        db, conversation_id, message_id, ticket, user
    )
    return FileResponse(
        path,
        media_type=mime,
        filename=None if inline else filename,
        content_disposition_type="inline" if inline else "attachment",
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{conversation_id}/read", status_code=204)
def mark_read(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat_service.mark_conversation_read(db, user, conversation_id)
    return Response(status_code=204)