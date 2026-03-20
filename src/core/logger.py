"""Logging configuration for Personal Cloud OS."""
import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(level: str = "DEBUG", log_file: str = None):
    """
    Set up application logging.

    Every log line includes the app version so you immediately know
    which build produced a given log entry, even when reading old files.
    """
    from core.version import __version__

    if log_file is None:
        log_dir = os.path.expanduser("~/.local/share/pcos/logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "app.log")

    numeric_level = getattr(logging, level.upper(), logging.DEBUG)

    # Format: timestamp | version | module | level | message
    fmt = f"%(asctime)s | v{__version__} | %(name)-20s | %(levelname)-8s | %(message)s"
    formatter = logging.Formatter(fmt)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Remove any existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    # Console — WARNING and above only (keeps terminal clean)
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    # Rotating file — full DEBUG output, max 2 MB, keep 3 backups
    file_handler = RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Silence noisy third-party loggers
    for noisy in ("urllib3", "asyncio", "RNS"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return log_file


def get_logger(name: str) -> logging.Logger:
    """Get a named logger."""
    return logging.getLogger(name)
