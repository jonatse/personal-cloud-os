"""Logging setup for Personal Cloud OS."""
import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    format_string: Optional[str] = None
):
    """Configure logging for the application."""
    if format_string is None:
        format_string = "%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s"
    
    # Create formatters
    formatter = logging.Formatter(format_string)
    
    # Console handler - only warnings and above
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.WARNING)  # Only show warnings+ to console
    
    # Root logger - set to DEBUG to allow file handler to capture everything
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture all for file
    root_logger.addHandler(console_handler)
    
    # File handler if specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)
