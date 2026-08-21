from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.core.config import Settings
from app.core.logging import configure_logging


def test_production_logging_is_rotating_and_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(environment="production", data_dir=tmp_path)
    logger = logging.getLogger("app")

    configure_logging(settings)
    configure_logging(settings)
    handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, RotatingFileHandler)
        and handler.baseFilename == str((tmp_path / "logs" / "metro2fog.log").resolve())
    ]
    assert len(handlers) == 1
    handler = handlers[0]
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 3

    logger.info("import task 42 failed with synthetic_error")
    handler.flush()
    content = (tmp_path / "logs" / "metro2fog.log").read_text(encoding="utf-8")
    assert "import task 42 failed with synthetic_error" in content

    logger.removeHandler(handler)
    handler.close()
