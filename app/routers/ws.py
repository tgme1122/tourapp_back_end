import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.database import SessionLocal
from app.dependencies import _user_from_token
from app.realtime import manager

router = APIRouter(tags=["realtime"])

AUTH_FRAME_TIMEOUT_SECONDS = 5.0


def _header_token(ws: WebSocket) -> str | None:
    auth = ws.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    token = _header_token(ws)

    if not token:
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=AUTH_FRAME_TIMEOUT_SECONDS)
            msg = json.loads(raw)
            if isinstance(msg, dict) and msg.get("type") == "auth" and isinstance(msg.get("token"), str):
                token = msg["token"].strip()
        except Exception:
            token = None

    if not token:
        await ws.close(code=1008)
        return

    with SessionLocal() as db:
        user = _user_from_token(db, token)
        if not user:
            await ws.close(code=1008)
            return
        user_id = user.id
        role = user.role.value

    await manager.connect(user_id, role, ws, accept=False)
    try:
        await ws.send_json({"type": "connected"})
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, ws)
