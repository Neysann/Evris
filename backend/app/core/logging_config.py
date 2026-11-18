import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from app.config import settings

_CONFIGURED = False


def setup_logging(log_file: str | None = None, level: int = logging.INFO) -> logging.Logger:
    """Configure rotating file logging for Evris without cluttering the terminal REPL."""
    global _CONFIGURED
    root_logger = logging.getLogger("evris")
    if _CONFIGURED:
        return root_logger

    target = Path(log_file or settings.log_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    root_logger.setLevel(level)
    root_logger.propagate = False

    handler = RotatingFileHandler(
        target,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    _CONFIGURED = True
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'evris' namespace."""
    setup_logging()
    short_name = name.removeprefix("app.")
    return logging.getLogger(f"evris.{short_name}")
