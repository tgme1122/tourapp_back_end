import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_agency_owner, get_current_user, get_optional_user, require_agency_member,
)
from app.models.agency_model import DocumentType
from app.models.user_model import User
from app.schemas.agency_report_schema import AgencyOverviewOut, TimePointOut, TopTourOut
from app.schemas.agency_schema import AgencyUpdate, MemberCreate, MemberOut, MemberUpdate
from app.schemas.user_schema import AgencyDocumentOut, AgencyProfileOut
from app.security import create_doc_ticket, verify_doc_ticket
from app.services import agency_member_service, agency_report_service, agency_service

router = APIRouter(prefix="/agency", tags=["agency"])


# ---------- Profil ----------
# Ko'rish: egasi ham, manager ham
@router.get("/me", response_model=AgencyProfileOut)
def my_agency(user: User = Depends(require_agency_member)):
    return user.agency_profile


# O'zgartirish: faqat egasi (agentlik tasdiqlanmagan bo'lsa ham)
@router.patch("/me", response_model=AgencyProfileOut)
def update_agency(
    data: AgencyUpdate, user: User = Depends(get_agency_owner), db: Session = Depends(get_db)
):
    return agency_service.update_profile(db, user, data)


@router.put("/me/logo", response_model=AgencyProfileOut)
def upload_logo(
    file: UploadFile = File(...),
    user: User = Depends(get_agency_owner),
    db: Session = Depends(get_db),
):
    return agency_service.set_logo(db, user, file)


# ---------- Hujjatlar (egasi) ----------
@router.post("/me/documents", response_model=AgencyDocumentOut, status_code=201)
def upload_document(
    doc_type: DocumentType = Form(..., alias="type"),
    file: UploadFile = File(...),
    user: User = Depends(get_agency_owner),
    db: Session = Depends(get_db),
):
    return agency_service.add_document(db, user, doc_type, file)


@router.delete("/me/documents/{document_id}", status_code=204)
def delete_document(
    document_id: uuid.UUID,
    user: User = Depends(get_agency_owner),
    db: Session = Depends(get_db),
):
    agency_service.delete_document(db, user, document_id)
    return Response(status_code=204)


@router.post("/me/resubmit", response_model=AgencyProfileOut)
def resubmit(user: User = Depends(get_agency_owner), db: Session = Depends(get_db)):
    return agency_service.resubmit(db, user)


# Egasi va admin uchun (Authorization sarlavhasi yoki qisqa muddatli ticket kerak)
@router.post("/documents/{document_id}/ticket")
def document_ticket(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    path = agency_service.document_file(db, user, document_id)
    return {
        "ticket": create_doc_ticket(document_id),
        "is_pdf": path.suffix.lower() == ".pdf",
    }


@router.get("/documents/{document_id}/file")
def document_file(
    document_id: uuid.UUID,
    ticket: str | None = None,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if ticket and verify_doc_ticket(ticket, document_id):
        path = agency_service.document_file_by_id(db, document_id)
    elif user:
        path = agency_service.document_file(db, user, document_id)
    else:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Token yaroqsiz yoki muddati o'tgan",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return FileResponse(
        path,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


# ---------- Xodimlar (egasi) ----------
@router.get("/me/members", response_model=list[MemberOut])
def members(user: User = Depends(get_agency_owner), db: Session = Depends(get_db)):
    return agency_member_service.list_members(db, user)


@router.post("/me/members", response_model=MemberOut, status_code=201)
def add_manager(
    data: MemberCreate,
    user: User = Depends(get_agency_owner),
    db: Session = Depends(get_db),
):
    return agency_member_service.create_manager(db, user, data)


@router.post("/me/members/{user_id}/deactivate", response_model=MemberOut)
def deactivate_member(
    user_id: uuid.UUID,
    user: User = Depends(get_agency_owner),
    db: Session = Depends(get_db),
):
    return agency_member_service.set_active(db, user, user_id, False)


@router.post("/me/members/{user_id}/activate", response_model=MemberOut)
def activate_member(
    user_id: uuid.UUID,
    user: User = Depends(get_agency_owner),
    db: Session = Depends(get_db),
):
    return agency_member_service.set_active(db, user, user_id, True)


@router.patch("/me/members/{user_id}", response_model=MemberOut)
def update_member(
    user_id: uuid.UUID,
    data: MemberUpdate,
    user: User = Depends(get_agency_owner),
    db: Session = Depends(get_db),
):
    return agency_member_service.update_manager(db, user, user_id, data)


@router.delete("/me/members/{user_id}", status_code=204)
def delete_member(
    user_id: uuid.UUID,
    user: User = Depends(get_agency_owner),
    db: Session = Depends(get_db),
):
    agency_member_service.delete_manager(db, user, user_id)
    return Response(status_code=204)


# ---------- Hisobotlar (egasi) ----------
@router.get("/reports/overview", response_model=AgencyOverviewOut)
def report_overview(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    user: User = Depends(get_agency_owner),
    db: Session = Depends(get_db),
):
    return agency_report_service.overview(db, user, date_from, date_to)


@router.get("/reports/timeseries", response_model=list[TimePointOut])
def report_timeseries(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    group: Literal["day", "month"] = "day",
    user: User = Depends(get_agency_owner),
    db: Session = Depends(get_db),
):
    return agency_report_service.timeseries(db, user, date_from, date_to, group)


@router.get("/reports/top-tours", response_model=list[TopTourOut])
def report_top_tours(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    limit: int = Query(5, ge=1, le=20),
    user: User = Depends(get_agency_owner),
    db: Session = Depends(get_db),
):
    return agency_report_service.top_tours(db, user, date_from, date_to, limit)