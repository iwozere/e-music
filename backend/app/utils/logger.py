import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from app.logging_redaction import SecretRedactFilter
from app.request_context import request_id_ctx


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object for log aggregation tools."""

    def format(self, record: logging.LogRecord) -> str:
        obj: dict = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            obj["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False)


def _make_formatter() -> logging.Formatter:
    """Return a JSON formatter when LOG_FORMAT=json, otherwise human-readable."""
    if os.environ.get("LOG_FORMAT", "").lower() == "json":
        return _JsonFormatter()
    return logging.Formatter(
        "%(asctime)s - %(request_id)s - %(name)s - %(levelname)s - %(message)s"
    )


def setup_logger(name: str) -> logging.Logger:
    """Set up a logger with console + optional rotating-file handler."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = _make_formatter()

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(_RequestIdFilter())
        console_handler.addFilter(SecretRedactFilter())
        logger.addHandler(console_handler)

        # Rotating file handler when running inside Docker (/app/db is a persistent volume).
        log_dir = "/app/db"
        if os.path.exists(log_dir):
            log_path = os.path.join(log_dir, "app.log")
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(_RequestIdFilter())
            file_handler.addFilter(SecretRedactFilter())
            logger.addHandler(file_handler)

    return logger
