import uuid

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models.user_model import User, UserRole
from app.schemas.auth_schema import TokenOut
from app.schemas.tour_schema import MyReviewOut
from app.schemas.user_schema import (
    ChangePassword, NotificationSettingsUpdate, ProfileStatsOut, UserOut, UserUpdate,
)
from app.security import create_access_token
from app.services import profile_service, tour_service

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/me", response_model=UserOut)
def update_me(
    data: UserUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return profile_service.update_profile(db, user, data)


@router.patch("/me/notification-settings", response_model=UserOut)
def update_notification_settings(
    data: NotificationSettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return profile_service.update_notification_settings(db, user, data)


@router.put("/me/avatar", response_model=UserOut)
def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return profile_service.set_avatar(db, user, file)


@router.delete("/me/avatar", response_model=UserOut)
def delete_avatar(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return profile_service.remove_avatar(db, user)


@router.post("/me/change-password", response_model=TokenOut)
def change_password(
    data: ChangePassword, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    profile_service.change_password(db, user, data)
    return TokenOut(
        access_token=create_access_token(user.id, user.role.value, user.token_version),
        user=UserOut.model_validate(user),
    )


@router.get("/me/stats", response_model=ProfileStatsOut)
def my_stats(
    user: User = Depends(require_roles(UserRole.traveler)), db: Session = Depends(get_db)
):
    return profile_service.get_stats(db, user)


@router.get("/me/reviews", response_model=list[MyReviewOut])
def my_reviews(
    user: User = Depends(require_roles(UserRole.traveler)), db: Session = Depends(get_db)
):
    return tour_service.list_my_reviews(db, user)


@router.delete("/me/reviews/{review_id}", status_code=204)
def delete_my_review(
    review_id: uuid.UUID,
    user: User = Depends(require_roles(UserRole.traveler)),
    db: Session = Depends(get_db),
):
    tour_service.delete_my_review(db, user, review_id)
    return Response(status_code=204)


@router.delete("/me", status_code=204)
def delete_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile_service.delete_me(db, user)
    return Response(status_code=204)