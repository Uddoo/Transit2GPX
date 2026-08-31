from __future__ import annotations

from typing import Any

from app.db.session import SessionLocal
from app.tasks.executor import PersistentTaskExecutor


def _dispatch(kind: str, resource_id: int, payload: dict[str, Any]) -> None:
    from app.services.import_jobs import TASK_HANDLERS

    handler = TASK_HANDLERS.get(kind)
    if handler is None:
        raise ValueError(f"Unsupported persistent task kind: {kind}")
    handler(resource_id, payload)


task_executor = PersistentTaskExecutor(SessionLocal, _dispatch)

__all__ = ["PersistentTaskExecutor", "task_executor"]
