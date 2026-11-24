import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.agency_model import AgencyMemberRole, AgencyStatus
from app.models.user_model import User, UserRole
from app.security import decode_access_token

bearer = HTTPBearer()                            # majburiy token
bearer_optional = HTTPBearer(auto_error=False)   # ixtiyoriy token


def _user_from_token(db: Session, token: str) -> User | None:
    payload = decode_access_token(token)
    if not payload:
        return None
    try:
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (KeyError, ValueError):
        return None
    if not user or not user.is_active:
        return None
    if payload.get("ver") != user.token_version:
        return None
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    user = _user_from_token(db, credentials.credentials)
    if not user:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Token yaroqsiz yoki muddati o'tgan",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_optional),
    db: Session = Depends(get_db),
) -> User | None:
    if not credentials:
        return None
    return _user_from_token(db, credentials.credentials)


def require_roles(*roles: UserRole):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu amal uchun ruxsat yo'q")
        return user

    return checker


# ---------- Agentlik xodimlari ----------
def require_agency_member(user: User = Depends(require_roles(UserRole.agency))) -> User:
    """Agentlikka biriktirilgan har qanday xodim (agentlik tasdiqlanmagan bo'lsa ham)."""
    if not user.membership:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Siz hech qaysi agentlikka biriktirilmagansiz"
        )
    return user


def get_agency_owner(user: User = Depends(require_agency_member)) -> User:
    """Faqat egasi (agentlik tasdiqlanmagan bo'lsa ham)."""
    if user.agency_role != AgencyMemberRole.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu amal faqat agentlik egasi uchun")
    return user


def get_agency_viewer(user: User = Depends(require_agency_member)) -> User:
    """Egasi yoki manager; agentlik tasdiqlangan bo'lishi shart. O'qish uchun."""
    if user.agency_profile.status != AgencyStatus.approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agentligingiz hali tasdiqlanmagan")
    return user


def get_approved_agency(user: User = Depends(get_agency_viewer)) -> User:
    """Faqat manager (agency admin). Tur, bron va chatni boshqarish uchun."""
    if user.agency_role != AgencyMemberRole.manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu amal faqat agentlik admini uchun")
    return user