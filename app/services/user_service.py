import hmac
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.agency_model import AgencyMember, AgencyMemberRole, AgencyProfile
from app.models.user_model import EmailCode, User, UserRole
from app.schemas.user_schema import AgencyRegister, TravelerRegister
from app.security import generate_code, hash_code, hash_password, verify_password

MAX_CODE_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


def get_user_by_phone(db: Session, phone: str) -> User | None:
    return db.scalar(select(User).where(User.phone == phone))


def _ensure_unique(db: Session, email: str, phone: str) -> None:
    exists = db.scalar(
        select(User).where(or_(func.lower(User.email) == email.lower(), User.phone == phone))
    )
    if exists:
        field = "Email" if exists.email.lower() == email.lower() else "Telefon raqam"
        raise HTTPException(status.HTTP_409_CONFLICT, f"{field} allaqachon ro'yxatdan o'tgan")


# ---------- Ro'yxatdan o'tish ----------
def register_traveler(db: Session, data: TravelerRegister) -> User:
    _ensure_unique(db, data.email, data.phone)
    user = User(
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email.lower(),
        phone=data.phone,
        password_hash=hash_password(data.password),
        role=UserRole.traveler,
        is_email_verified=True,  # oddiy userda kod shart emas
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def register_agency(db: Session, data: AgencyRegister) -> tuple[User, str]:
    _ensure_unique(db, data.email, data.phone)
    user = User(
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email.lower(),
        phone=data.phone,
        password_hash=hash_password(data.password),
        role=UserRole.agency,
        is_email_verified=False,
    )
    profile = AgencyProfile(
        name=data.agency_name.strip(),
        description=data.description,
        license_number=data.license_number,
        tax_id=data.tax_id,
        region=data.region,
        city=data.city,
        address=data.address,
        contact_phone=data.contact_phone,
        website=data.website,
    )
    user.owned_agency = profile
    # Ro'yxatdan o'tgan odam avtomatik egasi (owner) bo'ladi
    user.membership = AgencyMember(agency=profile, role=AgencyMemberRole.owner)

    db.add(user)
    db.flush()
    code = _issue_code(db, user)
    db.commit()
    db.refresh(user)
    return user, code


# ---------- Email kod ----------
def _issue_code(db: Session, user: User) -> str:
    db.execute(delete(EmailCode).where(EmailCode.user_id == user.id))
    code = generate_code()
    db.add(
        EmailCode(
            user_id=user.id,
            code_hash=hash_code(code),
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=settings.EMAIL_CODE_TTL_MINUTES),
        )
    )
    return code


def resend_code(db: Session, email: str) -> tuple[User, str] | None:
    """Foydalanuvchi mavjudligini oshkor qilmaslik uchun None qaytarishi mumkin."""
    user = get_user_by_email(db, email)
    if not user or user.role != UserRole.agency or user.is_email_verified:
        return None

    last = db.scalar(
        select(EmailCode)
        .where(EmailCode.user_id == user.id)
        .order_by(EmailCode.created_at.desc())
    )
    if last and (datetime.now(timezone.utc) - last.created_at).total_seconds() < RESEND_COOLDOWN_SECONDS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Yangi kodni {RESEND_COOLDOWN_SECONDS} soniyadan keyin so'rang",
        )

    code = _issue_code(db, user)
    db.commit()
    return user, code


def _codes_match(stored_hash: str, code: str) -> bool:
    return hmac.compare_digest(stored_hash, hash_code(code))


def verify_email(db: Session, email: str, code: str) -> User:
    bad = HTTPException(status.HTTP_400_BAD_REQUEST, "Kod noto'g'ri yoki muddati o'tgan")

    user = get_user_by_email(db, email)
    if not user:
        raise bad
    if user.is_email_verified:
        return user

    record = db.scalar(
        select(EmailCode)
        .where(EmailCode.user_id == user.id, EmailCode.used.is_(False))
        .order_by(EmailCode.created_at.desc())
    )
    if not record or record.expires_at < datetime.now(timezone.utc):
        raise bad
    if record.attempts >= MAX_CODE_ATTEMPTS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Urinishlar tugadi, yangi kod so'rang"
        )

    if not _codes_match(record.code_hash, code):
        record.attempts += 1
        db.commit()
        raise bad

    record.used = True
    user.is_email_verified = True
    db.commit()
    db.refresh(user)
    return user


# ---------- Login ----------
def authenticate(
    db: Session, email: str | None, password: str, phone: str | None = None
) -> User:
    user = (
        get_user_by_email(db, email)
        if email
        else (get_user_by_phone(db, phone) if phone else None)
    )
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email/telefon yoki parol noto'g'ri")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Akkaunt bloklangan")
    if user.role == UserRole.agency and not user.is_email_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Avval emailingizni tasdiqlang")
    return user