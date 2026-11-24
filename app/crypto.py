from cryptography.fernet import Fernet

from app.config import settings

# Kalit noto'g'ri bo'lsa, server ishga tushishda darrov xato beradi
_fernet = Fernet(settings.PASSPORT_ENCRYPTION_KEY.encode())


def encrypt_text(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str:
    return _fernet.decrypt(value.encode()).decode()


def mask_passport(number: str) -> str:
    """AB1234567 -> AB*****67"""
    if len(number) <= 4:
        return "*" * len(number)
    return number[:2] + "*" * (len(number) - 4) + number[-2:]