from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # loyiha ildizi


class Settings(BaseSettings):
    ENV: str = "development"
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    CORS_ORIGINS: list[str] = []
    ALLOW_LOCAL_CORS: bool = True

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@sayohatapp.uz"
    EMAIL_CODE_TTL_MINUTES: int = 10

    MEDIA_DIR: str = "media"
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    MAX_IMAGE_MB: int = 5
    PRIVATE_DIR: str = "private"
    MAX_DOCUMENT_MB: int = 10

    PASSPORT_ENCRYPTION_KEY: str
    BOOKING_HOLD_MINUTES: int = 10
    PAYMENT_SIMULATION: bool = False

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        if self.ENV.lower() == "production":
            if self.PAYMENT_SIMULATION:
                raise ValueError("Production muhitida PAYMENT_SIMULATION yoqilishi mumkin emas")
            if self.ALLOW_LOCAL_CORS and not self.CORS_ORIGINS:
                raise ValueError("Production muhitida CORS_ORIGINS ro'yxatini aniq ko'rsating")
        return self

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8"
    )


settings = Settings()