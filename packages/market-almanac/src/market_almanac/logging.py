"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"(app_identifier=)[^&\s\"']+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-_.=]+", re.IGNORECASE),
    re.compile(r"(password=)[^&\s\"']+", re.IGNORECASE),
    re.compile(r"(://[^:/\s]+:)[^@\s]+(@)"),
]


def redact(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        if pat.groups == 2:
            text = pat.sub(r"\1***\2", text)
        else:
            text = pat.sub(r"\1***", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update({k: redact(str(v)) if isinstance(v, str) else v for k, v in extra.items()})
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("market_almanac")
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    root.propagate = False
    # httpx logs full URLs (which may contain the HDX app identifier) at INFO; silence it.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"market_almanac.{name}")


def log_event(logger: logging.Logger, msg: str, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, msg, extra={"fields": fields})
