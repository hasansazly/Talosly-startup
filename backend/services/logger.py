import json
import logging
from datetime import datetime, timezone
from typing import Any

from backend.config import settings


class TaloslyLogger:
    def __init__(self) -> None:
        logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
        self._logger = logging.getLogger("talosly")

    def _emit(self, level: str, event: str, **kwargs: Any) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": level,
            "service": "talosly",
            "event": event,
            **kwargs,
        }
        if settings.log_format == "json":
            self._logger.log(getattr(logging, level), json.dumps(payload, default=str))
        else:
            self._logger.log(getattr(logging, level), "%s %s", event, kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._emit("INFO", event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._emit("WARNING", event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._emit("ERROR", event, **kwargs)


logger = TaloslyLogger()
