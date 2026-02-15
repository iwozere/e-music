import logging
import sys
import os
from logging.handlers import RotatingFileHandler

def setup_logger(name: str) -> logging.Logger:
    """
    Set up a logger with a standard format, console handler, and rotating file handler.
    """
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # 1. Console Handler (for docker logs)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
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
            logger.addHandler(file_handler)
        
    return logger
