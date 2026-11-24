import asyncio
import contextlib
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.realtime import manager
from app.routers import (
    admin, agency, auth, bookings, chats, notifications, payments, tour_options,
    tours, users, ws,
)
from app.services.booking_service import run_maintenance
from app.services.storage_service import MEDIA_ROOT

log = logging.getLogger("maintenance")
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)


async def _maintenance_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(run_maintenance)
        except Exception:
            log.exception("Fon vazifada xato")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.set_loop(asyncio.get_running_loop())
    task = asyncio.create_task(_maintenance_loop())
    yield
    await manager.close_all()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="SayohatApp API", lifespan=lifespan)

local_regex = (
    r"https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3})(:\d+)?$"
    if settings.ALLOW_LOCAL_CORS and settings.ENV.lower() != "production"
    else None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=local_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(tours.router)
app.include_router(tour_options.router)
app.include_router(bookings.router)
app.include_router(payments.router)
app.include_router(chats.router)
app.include_router(notifications.router)
app.include_router(agency.router)
app.include_router(admin.router)
app.include_router(ws.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, app_dir=str(ROOT_DIR))
