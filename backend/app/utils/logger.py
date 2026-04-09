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


def setup_logger(name: str) -> logging.Logger:
    """
    Set up a logger with a standard format, console handler, and rotating file handler.
    """
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s - %(request_id)s - %(name)s - %(levelname)s - %(message)s"
        )

        # 1. Console Handler (for docker logs)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(_RequestIdFilter())
        console_handler.addFilter(SecretRedactFilter())
        logger.addHandler(console_handler)

        # 2. Rotating File Handler (for persistence on SSD)
        # We store it in /app/db which is a persistent volume
        log_dir = "/app/db"
        if os.path.exists(log_dir):
            log_path = os.path.join(log_dir, "app.log")
            file_handler = RotatingFileHandler(
                log_path, 
                maxBytes=5*1024*1024, # 5MB
                backupCount=5
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(_RequestIdFilter())
            file_handler.addFilter(SecretRedactFilter())
            logger.addHandler(file_handler)
        
    return logger
