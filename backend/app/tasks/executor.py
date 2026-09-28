from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from concurrent.futures import CancelledError
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AppTask

logger = logging.getLogger(__name__)
TaskDispatcher = Callable[[str, int, dict[str, Any]], None]


class PersistentTaskExecutor:
    """Run durable SQLite-backed jobs on a single daemon worker."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        dispatcher: TaskDispatcher,
    ) -> None:
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._queue: queue.Queue[int | None] = queue.Queue()
        self._scheduled: set[int] = set()
        self._lock = threading.Lock()
        self._persistence_lock = threading.Lock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                if self._stop.is_set():
                    raise RuntimeError("持久化任务执行器仍在停止中。")
                return
            self._queue = queue.Queue()
            self._scheduled.clear()
            self._stop.clear()
            with self._session_factory() as db:
                db.execute(
                    update(AppTask)
                    .where(AppTask.status == "running")
                    .values(
                        status="queued",
                        started_at=None,
                        error_type="ServiceRestarted",
                        error_message="服务重启后自动恢复任务",
                    )
                )
                db.commit()
                task_ids = list(
                    db.scalars(
                        select(AppTask.id)
                        .where(AppTask.status == "queued")
                        .order_by(AppTask.id)
                    )
                )
            self._worker = threading.Thread(
                target=self._work,
                name="transit2fog-task-executor",
                daemon=True,
            )
            self._worker.start()
        for task_id in task_ids:
            self._schedule(task_id)

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)
        worker = self._worker
        if worker is not None:
            worker.join(timeout=0.25)
        with self._lock:
            if worker is None or not worker.is_alive():
                self._worker = None
                self._scheduled.clear()

    def enqueue(
        self,
        *,
        kind: str,
        resource_id: int,
        payload: dict[str, Any],
    ) -> AppTask:
        with self._persistence_lock, self._session_factory() as db:
            existing = db.scalar(
                select(AppTask)
                .where(
                    AppTask.kind == kind,
                    AppTask.resource_id == resource_id,
                    AppTask.status.in_(["queued", "running"]),
                )
                .order_by(AppTask.id.desc())
            )
            if existing is not None:
                task = existing
            else:
                task = AppTask(
                    kind=kind,
                    resource_id=resource_id,
                    payload_json=payload,
                    status="queued",
                    attempts=0,
                )
                db.add(task)
                db.commit()
                db.refresh(task)
            task_id = task.id
            db.expunge(task)
        self._schedule(task_id)
        return task

    def cancel_pending(self, *, kind: str, resource_id: int) -> None:
        with self._persistence_lock, self._session_factory() as db:
            tasks = db.scalars(
                select(AppTask).where(
                    AppTask.kind == kind,
                    AppTask.resource_id == resource_id,
                    AppTask.status == "queued",
                )
            ).all()
            for task in tasks:
                task.status = "cancelled"
                task.completed_at = datetime.now(UTC)
                task.error_type = "CancelledError"
                task.error_message = "用户取消了任务"
            db.commit()

    def _schedule(self, task_id: int) -> None:
        with self._lock:
            if task_id in self._scheduled:
                return
            self._scheduled.add(task_id)
            self._queue.put(task_id)

    def _work(self) -> None:
        while True:
            task_id = self._queue.get()
            if task_id is None:
                self._queue.task_done()
                return
            try:
                if not self._stop.is_set():
                    self._run_task(task_id)
            finally:
                with self._lock:
                    self._scheduled.discard(task_id)
                self._queue.task_done()

    def _run_task(self, task_id: int) -> None:
        with self._session_factory() as db:
            task = db.get(AppTask, task_id)
            if task is None or task.status != "queued":
                return
            task.status = "running"
            task.attempts += 1
            task.started_at = datetime.now(UTC)
            task.completed_at = None
            task.error_type = None
            task.error_message = None
            db.commit()
            kind = task.kind
            resource_id = task.resource_id
            payload = dict(task.payload_json)
        try:
            self._dispatcher(kind, resource_id, payload)
        except CancelledError as error:
            self._finish(task_id, "cancelled", error)
        except Exception as error:
            logger.exception("Persistent task %s (%s) failed", task_id, kind)
            self._finish(task_id, "failed", error)
        else:
            self._finish(task_id, "succeeded", None)

    def _finish(self, task_id: int, status: str, error: BaseException | None) -> None:
        with self._session_factory() as db:
            task = db.get(AppTask, task_id)
            if task is None:
                return
            task.status = status
            task.completed_at = datetime.now(UTC)
            task.error_type = type(error).__name__ if error is not None else None
            task.error_message = str(error)[:2000] if error is not None else None
            db.commit()
