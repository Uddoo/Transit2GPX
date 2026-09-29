from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Install one privacy-safe rotating application log in production."""

    app_logger = logging.getLogger("app")
    app_logger.disabled = False
    app_logger.setLevel(logging.INFO)
    if settings.environment != "production":
        return
    log_directory = settings.data_dir / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = (log_directory / "transit2gpx.log").resolve()
    for handler in app_logger.handlers:
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == str(
            log_path
        ):
            return
    handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    app_logger.addHandler(handler)
