import asyncio
import json
import uuid
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from fastapi import WebSocket


class RealtimeManager:
    """Foydalanuvchilarga real-time WebSocket hodisalarini yuborish menejeri."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)
        self._admins: set[uuid.UUID] = set()

    def set_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    async def close_all(self) -> None:
        self._loop = None
        sockets = [ws for group in self._clients.values() for ws in list(group)]
        self._clients.clear()
        self._admins.clear()
        for ws in sockets:
            try:
                await ws.close(code=1001)
            except Exception:
                pass

    async def connect(
        self, user_id: uuid.UUID, role: str, ws: WebSocket, *, accept: bool = True
    ) -> None:
        if accept:
            await ws.accept()
        self._clients[user_id].add(ws)
        if role == "admin":
            self._admins.add(user_id)

    def disconnect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        sockets = self._clients.get(user_id)
        if not sockets:
            return
        sockets.discard(ws)
        if not sockets:
            self._clients.pop(user_id, None)
            self._admins.discard(user_id)

    async def _send_targets(self, targets: list[uuid.UUID], raw: str) -> None:
        dead: list[tuple[uuid.UUID, WebSocket]] = []
        for uid in targets:
            for ws in list(self._clients.get(uid, ())):
                try:
                    await ws.send_text(raw)
                except Exception:
                    dead.append((uid, ws))
        for uid, ws in dead:
            self.disconnect(uid, ws)

    def _schedule(self, coro) -> None:
        loop = self._loop
        if not loop or loop.is_closed():
            coro.close()
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            loop.create_task(coro)
        else:
            loop.call_soon_threadsafe(loop.create_task, coro)

    def emit(self, user_ids: Iterable[uuid.UUID], payload: dict[str, Any]) -> None:
        targets = list(dict.fromkeys(user_ids))
        if not targets or not self._loop or self._loop.is_closed():
            return
        raw = json.dumps(payload, default=str)
        self._schedule(self._send_targets(targets, raw))

    def emit_one(self, user_id: uuid.UUID, payload: dict[str, Any]) -> None:
        self.emit((user_id,), payload)

    def is_online(self, user_id: uuid.UUID) -> bool:
        return bool(self._clients.get(user_id))

    def any_online(self, user_ids: Iterable[uuid.UUID]) -> bool:
        return any(bool(self._clients.get(uid)) for uid in user_ids)

    def close_user(self, user_id: uuid.UUID, code: int = 1000) -> None:
        if not self._loop or self._loop.is_closed():
            return

        async def _close() -> None:
            sockets = list(self._clients.pop(user_id, ()))
            self._admins.discard(user_id)
            for ws in sockets:
                try:
                    await ws.close(code=code)
                except Exception:
                    pass

        self._schedule(_close())

    def emit_admins(self, payload: dict[str, Any]) -> None:
        if not self._loop or self._loop.is_closed():
            return
        raw = json.dumps(payload, default=str)

        async def _dispatch() -> None:
            if self._admins:
                await self._send_targets(list(self._admins), raw)

        self._schedule(_dispatch())


manager = RealtimeManager()
