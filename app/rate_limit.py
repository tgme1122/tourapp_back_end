import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class SlidingWindowLimiter:
    """Xotira ichidagi yengil rate limiter (har kalit uchun sliding window)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._calls = 0

    def check(self, key: str, limit: int, window_seconds: int) -> int | None:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            self._calls += 1
            if self._calls % 500 == 0:
                self._prune(now - 3600)

            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(bucket[0] + window_seconds - now) + 1)
                return retry_after
            bucket.append(now)
            return None

    def _prune(self, stale_before: float) -> None:
        dead = [k for k, q in self._hits.items() if not q or q[-1] < stale_before]
        for k in dead:
            self._hits.pop(k, None)


_limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str, limit: int, window_seconds: int):
    def dependency(request: Request) -> None:
        ip = client_ip(request)
        retry = _limiter.check(f"{scope}:{ip}", limit, window_seconds)
        if retry is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Juda ko'p urinish. {retry} soniyadan keyin qayta urinib ko'ring.",
                headers={"Retry-After": str(retry)},
            )

    return dependency


def enforce_rate_limit(scope: str, identifier: str, limit: int, window_seconds: int) -> None:
    retry = _limiter.check(f"{scope}:{identifier.lower().strip()}", limit, window_seconds)
    if retry is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Juda ko'p urinish. {retry} soniyadan keyin qayta urinib ko'ring.",
            headers={"Retry-After": str(retry)},
        )
