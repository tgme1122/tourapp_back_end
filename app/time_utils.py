from datetime import date, datetime, timedelta, timezone

UZ_TZ = timezone(timedelta(hours=5))  # O'zbekistonda yozgi/qishki vaqt yo'q


def now_uz() -> datetime:
    return datetime.now(UZ_TZ)


def today_uz() -> date:
    return now_uz().date()
