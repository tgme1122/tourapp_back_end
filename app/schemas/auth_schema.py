from pydantic import EmailStr, Field, model_validator

from app.schemas.base import CamelModel
from app.schemas.user_schema import PHONE_PATTERN, UserOut


class LoginRequest(CamelModel):
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    password: str

    @model_validator(mode="after")
    def check_identifier(self):
        if not self.email and not self.phone:
            raise ValueError("Email yoki telefon raqamini kiriting")
        return self


class VerifyEmailRequest(CamelModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class ResendCodeRequest(CamelModel):
    email: EmailStr


class TokenOut(CamelModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class MessageOut(CamelModel):
    message: str