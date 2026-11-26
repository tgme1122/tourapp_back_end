import json
from pathlib import Path
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # loyiha ildizi


class Settings(BaseSettings):
    ENV: str = "development"
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    CORS_ORIGINS: Annotated[list[str], NoDecode] = []
    ALLOW_LOCAL_CORS: bool = True

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        url = v.strip()
        if url.startswith("postgres://"):
            return "postgresql+psycopg2://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            return "postgresql+psycopg2://" + url[len("postgresql://"):]
        if url.startswith("postgresql+psycopg://"):
            return "postgresql+psycopg2://" + url[len("postgresql+psycopg://"):]
        return url

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> object:
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            if s.startswith("["):
                return json.loads(s)
            return [item.strip() for item in s.split(",") if item.strip()]
        return v

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