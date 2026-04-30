import time
from collections import defaultdict, deque

from fastapi import HTTPException

from backend.config import settings

_windows: dict[int, dict[str, deque[float]]] = defaultdict(lambda: {"minute": deque(), "day": deque()})


def check_rate_limit(api_key_id: int) -> dict[str, str]:
    now = time.time()
    minute_window = _windows[api_key_id]["minute"]
    day_window = _windows[api_key_id]["day"]

    while minute_window and minute_window[0] <= now - 60:
        minute_window.popleft()
    while day_window and day_window[0] <= now - 86400:
        day_window.popleft()

    minute_remaining = settings.rate_limit_per_minute - len(minute_window)
    day_remaining = settings.rate_limit_per_day - len(day_window)
    if minute_remaining <= 0 or day_remaining <= 0:
        reset = int((minute_window[0] + 60) if minute_remaining <= 0 and minute_window else now + 60)
        retry_after = max(reset - int(now), 1)
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(settings.rate_limit_per_minute),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset),
                "Retry-After": str(retry_after),
            },
        )

    minute_window.append(now)
    day_window.append(now)
    return {
        "X-RateLimit-Limit": str(settings.rate_limit_per_minute),
        "X-RateLimit-Remaining": str(max(minute_remaining - 1, 0)),
        "X-RateLimit-Reset": str(int(now + 60)),
    }
