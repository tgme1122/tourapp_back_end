from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user_model import User
from app.rate_limit import enforce_rate_limit, rate_limit
from app.schemas.auth_schema import (
    LoginRequest, MessageOut, ResendCodeRequest, TokenOut, VerifyEmailRequest,
)
from app.schemas.user_schema import AgencyRegister, TravelerRegister, UserOut
from app.security import create_access_token
from app.services import user_service
from app.services.email_service import send_verification_code

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, user.role.value, user.token_version),
        user=UserOut.model_validate(user),
    )


@router.post(
    "/register/traveler",
    response_model=TokenOut,
    status_code=201,
    dependencies=[Depends(rate_limit("auth_register", 5, 60))],
)
def register_traveler(data: TravelerRegister, db: Session = Depends(get_db)):
    user = user_service.register_traveler(db, data)
    return _token_response(user)


@router.post(
    "/register/agency",
    response_model=MessageOut,
    status_code=201,
    dependencies=[Depends(rate_limit("auth_register", 5, 60))],
)
def register_agency(
    data: AgencyRegister, background: BackgroundTasks, db: Session = Depends(get_db)
):
    user, code = user_service.register_agency(db, data)
    background.add_task(send_verification_code, user.email, code)
    return MessageOut(message="Emailingizga tasdiqlash kodi yuborildi")


@router.post(
    "/verify-email",
    response_model=MessageOut,
    dependencies=[Depends(rate_limit("auth_verify", 10, 60))],
)
def verify_email(data: VerifyEmailRequest, db: Session = Depends(get_db)):
    user_service.verify_email(db, data.email, data.code)
    return MessageOut(
        message="Email tasdiqlandi. Agentligingiz admin tomonidan ko'rib chiqiladi"
    )


@router.post(
    "/resend-code",
    response_model=MessageOut,
    dependencies=[Depends(rate_limit("auth_verify", 10, 60))],
)
def resend_code(
    data: ResendCodeRequest, background: BackgroundTasks, db: Session = Depends(get_db)
):
    result = user_service.resend_code(db, data.email)
    if result:
        user, code = result
        background.add_task(send_verification_code, user.email, code)
    # Email mavjudligini oshkor qilmaslik uchun javob doim bir xil
    return MessageOut(message="Agar email mavjud bo'lsa, yangi kod yuborildi")


@router.post(
    "/login",
    response_model=TokenOut,
    dependencies=[Depends(rate_limit("auth_login", 10, 60))],
)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    ident = data.email or data.phone or ""
    enforce_rate_limit("auth_login_ident", ident, 8, 60)
    user = user_service.authenticate(db, data.email, data.password, data.phone)
    return _token_response(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user