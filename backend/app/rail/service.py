from __future__ import annotations

import threading
from typing import Literal

from pydantic import BaseModel

from app.core.config import Settings
from app.rail.sidecar import RailSidecarError, fetch_sidecar_info
from app.rail.supervisor import RailSidecarSupervisor, _graph_runtime, _verify_identity


class RailServiceState(BaseModel):
    status: Literal["idle", "starting", "ready", "failed"] = "idle"
    error_code: str | None = None
    message: str | None = None


class RailServiceController:
    """Own the local sidecar across startup, wizard retries and shutdown."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._supervisor = RailSidecarSupervisor(settings)
        self._state = RailServiceState()
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._closed = False
        # Capture launch overrides before restored preferences mutate Settings.
        self.locked_fields = set(settings.model_fields_set)

    @property
    def configuration_lock(self) -> threading.RLock:
        return self._lock

    def snapshot(self) -> RailServiceState:
        with self._lock:
            if self._state.status == "ready" and self._supervisor.exited:
                self._state = RailServiceState(
                    status="failed",
                    error_code="rail_sidecar_exited",
                    message="铁路服务已退出，可以重新启动。",
                )
            return self._state.model_copy()

    def refresh(self) -> RailServiceState:
        state = self.snapshot()
        if state.status != "ready":
            return state
        try:
            _, metadata = _graph_runtime(self._settings)
            info = fetch_sidecar_info(self._settings.rail_sidecar_url, 0.5)
            _verify_identity(info, metadata)
        except RailSidecarError as error:
            with self._lock:
                if self._state.status == "ready":
                    self._state = RailServiceState(
                        status="failed", error_code=error.code, message=str(error)
                    )
        return self.snapshot()

    def start(self) -> RailServiceState:
        with self._lock:
            if self._closed:
                raise RailSidecarError(
                    "rail_service_stopping", "应用正在关闭，请重新打开后重试。"
                )
            if self.snapshot().status == "starting" or (
                self.snapshot().status == "ready" and self._supervisor.owns_process
            ):
                return self.snapshot()
            self._state = RailServiceState(
                status="starting", message="正在校验文件并启动铁路服务…"
            )
            self._cancel.clear()
            self._worker = threading.Thread(
                target=self._run, name="transit2fog-rail-start", daemon=True
            )
            self._worker.start()
            return self._state.model_copy()

    def _run(self) -> None:
        try:
            if self._supervisor.owns_process:
                self._supervisor.stop()
            self._supervisor.start(cancel_event=self._cancel)
        except Exception as error:
            self._supervisor.stop()
            with self._lock:
                self._state = RailServiceState(
                    status="failed",
                    error_code=getattr(error, "code", "rail_sidecar_start_failed"),
                    message=str(error)
                    if isinstance(error, RailSidecarError)
                    else "铁路服务启动失败，请检查服务文件与本地日志。",
                )
        else:
            with self._lock:
                self._state = RailServiceState(
                    status="ready", message="铁路路径服务已启动。"
                )

    def stop(self) -> None:
        with self._lock:
            self._closed = True
            self._cancel.set()
            worker = self._worker
        if worker is not None:
            worker.join(timeout=6)
        self._supervisor.stop()
