from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agency_model import AgencyMemberRole
from app.models.booking_model import Booking, BookingStatus
from app.models.notification_model import Notification
from app.models.payment_model import Payment
from app.models.tour_model import Review, SavedTour
from app.models.user_model import EmailCode, User, UserRole
from app.realtime import manager
from app.schemas.user_schema import (
    ChangePassword, NotificationSettingsUpdate, ProfileStatsOut, UserUpdate,
)
from app.security import hash_password, verify_password
from app.services.storage_service import delete_file, save_image


def update_profile(db: Session, user: User, data: UserUpdate) -> User:
    values = data.model_dump(exclude_unset=True)

    phone = values.get("phone")
    if phone and phone != user.phone:
        taken = db.scalar(select(User.id).where(User.phone == phone, User.id != user.id))
        if taken:
            raise HTTPException(status.HTTP_409_CONFLICT, "Bu telefon raqam band")

    for key, value in values.items():
        if value is None:  # bu maydonlarning hech biri bo'sh bo'la olmaydi
            continue
        setattr(user, key, value.strip() if isinstance(value, str) else value)

    try:
        db.commit()
    except IntegrityError:  # ikki so'rov bir vaqtda kelgan holat
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu telefon raqam band")
    db.refresh(user)
    return user


def update_notification_settings(
    db: Session, user: User, data: NotificationSettingsUpdate
) -> User:
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user


def set_avatar(db: Session, user: User, file: UploadFile) -> User:
    new_path = save_image(file, f"avatars/{user.id}")
    old_path = user.avatar_path
    user.avatar_path = new_path
    try:
        db.commit()
    except Exception:
        db.rollback()
        delete_file(new_path)
        raise
    delete_file(old_path)  # eskisi faqat commit'dan keyin o'chiriladi
    db.refresh(user)
    return user


def remove_avatar(db: Session, user: User) -> User:
    old_path = user.avatar_path
    user.avatar_path = None
    db.commit()
    delete_file(old_path)
    db.refresh(user)
    return user


def change_password(db: Session, user: User, data: ChangePassword) -> None:
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Joriy parol noto'g'ri")
    if data.current_password == data.new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Yangi parol joriysidan farq qilsin")
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1
    db.commit()
    db.refresh(user)
    manager.close_user(user.id)


def get_stats(db: Session, user: User) -> ProfileStatsOut:
    def count(col, where):
        return db.scalar(select(func.count(col)).where(where)) or 0

    return ProfileStatsOut(
        saved_tours=count(SavedTour.tour_id, SavedTour.user_id == user.id),
        bookings=count(Booking.id, Booking.user_id == user.id),
        reviews=count(Review.id, Review.user_id == user.id),
    )


def delete_me(db: Session, user: User) -> None:
    if user.role == UserRole.admin or user.agency_role == AgencyMemberRole.owner:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Bu roldagi hisobni o'chirib bo'lmaydi. Admin bilan bog'laning.",
        )

    active_booking = db.scalar(
        select(Booking.id).where(
            Booking.user_id == user.id,
            Booking.status.in_((BookingStatus.pending_payment, BookingStatus.confirmed)),
        )
    )
    if active_booking:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Faol broningiz borligi sababli hisobni o'chirib bo'lmaydi. Avval bronni bekor qiling.",
        )

    old_avatar = user.avatar_path
    has_records = bool(
        db.scalar(select(Booking.id).where(Booking.user_id == user.id))
        or db.scalar(select(Payment.id).where(Payment.user_id == user.id))
    )

    if has_records:
        # Moliyaviy yozuvlar (RESTRICT) saqlanishi uchun anonimizatsiya + deaktivatsiya qilamiz
        db.execute(delete(SavedTour).where(SavedTour.user_id == user.id))
        db.execute(delete(Notification).where(Notification.user_id == user.id))
        db.execute(delete(EmailCode).where(EmailCode.user_id == user.id))
        user.is_active = False
        user.first_name = "O'chirilgan"
        user.last_name = "Foydalanuvchi"
        user.email = f"deleted-{user.id}@deleted.local"
        user.phone = f"+000{str(user.id.int)[:12]}"
        user.avatar_path = None
        user.push_enabled = False
        user.price_drop_enabled = False
        user.agency_messages_enabled = False
    else:
        db.delete(user)

    db.commit()
    delete_file(old_avatar)
    manager.close_user(user.id)