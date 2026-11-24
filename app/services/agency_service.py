import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.models.agency_model import (
    AgencyDocument, AgencyMemberRole, AgencyProfile, AgencyStatus, DocumentType,
)
from app.models.user_model import User, UserRole
from app.realtime import manager
from app.schemas.agency_schema import AgencyUpdate
from app.services.storage_service import delete_file, private_file, save_document, save_image

REQUIRED_DOCS = {
    DocumentType.license, DocumentType.tax_certificate, DocumentType.registration,
}
MAX_DOCUMENTS = 10
NULLABLE = {"description", "contact_phone", "website"}
SENSITIVE = ("license_number", "tax_id")


def _profile(user: User) -> AgencyProfile:
    if not user.agency_profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agentlik profili topilmadi")
    return user.agency_profile


def missing_documents(profile: AgencyProfile) -> list[str]:
    have = {d.type for d in profile.documents}
    return sorted(t.value for t in REQUIRED_DOCS - have)


def update_profile(db: Session, user: User, data: AgencyUpdate) -> AgencyProfile:
    p = _profile(user)
    values = data.model_dump(exclude_unset=True)

    sensitive_changed = any(
        values.get(k) is not None and values[k] != getattr(p, k) for k in SENSITIVE
    )
    for key, value in values.items():
        if value is None and key not in NULLABLE:
            continue
        setattr(p, key, value.strip() if isinstance(value, str) else value)

    if sensitive_changed and p.status == AgencyStatus.approved:
        p.status = AgencyStatus.pending  # rekvizit o'zgardi, qayta tekshiriladi
        p.reviewed_at = None

    db.commit()
    db.refresh(p)
    if sensitive_changed:
        manager.emit_one(user.id, {"type": "agency_status"})
        manager.emit_admins({"type": "admin_update"})
    return p


def set_logo(db: Session, user: User, file: UploadFile) -> AgencyProfile:
    p = _profile(user)
    new_path = save_image(file, f"logos/{p.id}")
    old_path = p.logo_path
    p.logo_path = new_path
    try:
        db.commit()
    except Exception:
        db.rollback()
        delete_file(new_path)
        raise
    delete_file(old_path)
    db.refresh(p)
    return p


def add_document(
    db: Session, user: User, doc_type: DocumentType, file: UploadFile
) -> AgencyDocument:
    p = _profile(user)
    if p.status == AgencyStatus.suspended:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agentligingiz bloklangan")
    if len(p.documents) >= MAX_DOCUMENTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Ko'pi bilan {MAX_DOCUMENTS} ta hujjat yuklash mumkin"
        )

    path = save_document(file, f"agency-docs/{p.id}")
    doc = AgencyDocument(agency_id=p.id, type=doc_type, file_path=path)
    try:
        db.add(doc)
        db.commit()
    except Exception:
        db.rollback()
        delete_file(path, private=True)
        raise
    db.refresh(doc)
    return doc


def delete_document(db: Session, user: User, doc_id: uuid.UUID) -> None:
    p = _profile(user)
    doc = next((d for d in p.documents if d.id == doc_id), None)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hujjat topilmadi")
    if p.status == AgencyStatus.approved and doc.is_checked:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tasdiqlangan hujjatni o'chirib bo'lmaydi")
    path = doc.file_path
    db.delete(doc)
    db.commit()
    delete_file(path, private=True)


def resubmit(db: Session, user: User) -> AgencyProfile:
    p = _profile(user)
    if p.status != AgencyStatus.rejected:
        raise HTTPException(status.HTTP_409_CONFLICT, "Faqat rad etilgan arizani qayta yuborish mumkin")
    missing = missing_documents(p)
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Yetishmayotgan hujjatlar: {', '.join(missing)}"
        )
    p.status = AgencyStatus.pending
    p.rejection_reason = None
    db.commit()
    db.refresh(p)
    manager.emit_one(user.id, {"type": "agency_status"})
    manager.emit_admins({"type": "admin_update"})
    return p


def document_file(db: Session, user: User, doc_id: uuid.UUID) -> Path:
    """Hujjatni faqat admin yoki agentlik egasi ochadi (manager ochmaydi)."""
    doc = db.get(AgencyDocument, doc_id)
    allowed = bool(
        doc
        and (
            user.role == UserRole.admin
            or (
                user.agency_profile
                and user.agency_role == AgencyMemberRole.owner
                and doc.agency_id == user.agency_profile.id
            )
        )
    )
    path = private_file(doc.file_path) if allowed else None
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hujjat topilmadi")
    return path


def document_file_by_id(db: Session, doc_id: uuid.UUID) -> Path:
    doc = db.get(AgencyDocument, doc_id)
    path = private_file(doc.file_path) if doc else None
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hujjat topilmadi")
    return path