import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: uuid.UUID, role: str, token_version: int = 1) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": str(user_id), "role": str(role), "ver": token_version, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


def generate_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def hash_code(code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()


def create_doc_ticket(doc_id: uuid.UUID, ttl_seconds: int = 120) -> str:
    expire = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    payload = {"doc": str(doc_id), "purpose": "doc_view", "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_doc_ticket(ticket: str, doc_id: uuid.UUID) -> bool:
    payload = decode_access_token(ticket)
    if not payload:
        return False
    return payload.get("purpose") == "doc_view" and payload.get("doc") == str(doc_id)


def create_chat_ticket(message_id: uuid.UUID, ttl_seconds: int = 3600) -> str:
    expire = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    payload = {"msg": str(message_id), "purpose": "chat_file", "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_chat_ticket(ticket: str, message_id: uuid.UUID) -> bool:
    payload = decode_access_token(ticket)
    if not payload:
        return False
    return payload.get("purpose") == "chat_file" and payload.get("msg") == str(message_id)