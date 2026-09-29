from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.data_status import DataStatusResponse, data_status
from app.api.rail_data import RailDataStatusResponse, rail_data_status
from app.core.config import get_settings
from app.core.errors import APIError
from app.db.base import AppMeta
from app.db.models import Journey, RailDatasetVersion
from app.db.session import get_db
from app.importers.capabilities import raw_import_available
from app.rail.components import ComponentError, ComponentInstaller, ComponentState
from app.rail.service import RailServiceController, RailServiceState
from app.rail.sidecar import RailSidecarError
from app.services.onboarding import (
    RAIL_FIELDS,
    RailSetupConfig,
    SetupChecks,
    SetupProgress,
    SetupStep,
    config_updates,
    current_rail_config,
    environment_checks,
    get_progress,
    put_meta,
    rail_checks,
    save_progress,
    save_rail_preferences,
)

router = APIRouter(prefix="/setup", tags=["first-use setup"])


class SetupState(BaseModel):
    progress: SetupProgress
    should_show: bool
    metro: DataStatusResponse
    rail: RailDataStatusResponse
    service: RailServiceState
    rail_config: RailSetupConfig
    metro_directory: str
    log_path: str
    locked_fields: list[str]
    rail_start_allowed: bool
    components: ComponentState
    raw_import_available: bool


class SetupProgressPatch(BaseModel):
    step: SetupStep | None = None
    dismissed: bool | None = None
    rail_skipped: bool | None = None
    metro_directory: str | None = None
    complete: bool = False


class ComponentPrepareRequest(BaseModel):
    install: Literal[True]


def service_controller(request: Request) -> RailServiceController:
    return cast(RailServiceController, request.app.state.rail_service)


@router.get("", response_model=SetupState)
def setup_state(request: Request, db: Session = Depends(get_db)) -> SetupState:
    settings = get_settings()
    progress, saved = get_progress(db)
    metro = data_status(db)
    rail = rail_data_status(db)
    existing = (
        metro.ready_available
        or bool(db.scalar(select(Journey.id).limit(1)))
        or bool(
            db.scalar(
                select(RailDatasetVersion.id)
                .where(RailDatasetVersion.status == "ready")
                .limit(1)
            )
        )
    )
    controller = service_controller(request)
    directory = db.get(AppMeta, "setup.metro_directory")
    return SetupState(
        progress=progress,
        should_show=not progress.completed
        and not progress.dismissed
        and (saved or not existing),
        metro=metro,
        rail=rail,
        service=controller.refresh(),
        rail_config=current_rail_config(settings),
        metro_directory=directory.value if directory else "",
        log_path=str(settings.data_dir / "logs" / "rail-sidecar.log"),
        locked_fields=[
            key for key, name in RAIL_FIELDS.items() if name in controller.locked_fields
        ],
        rail_start_allowed=not any(
            name in controller.locked_fields and not getattr(settings, name)
            for name in ("rail_enabled", "rail_sidecar_managed")
        ),
        components=cast(
            ComponentInstaller, request.app.state.rail_components
        ).snapshot(),
        raw_import_available=raw_import_available(),
    )


@router.patch("/progress", response_model=SetupProgress)
def update_setup_progress(
    payload: SetupProgressPatch, db: Session = Depends(get_db)
) -> SetupProgress:
    progress, _ = get_progress(db)
    if payload.complete:
        if not environment_checks(db, get_settings()).can_continue:
            raise APIError(
                status_code=409,
                code="setup_environment_not_ready",
                message="运行环境检查尚未通过，请先处理阻断项。",
            )
        if (
            not data_status(db).ready_available
            and rail_data_status(db).status != "ready"
        ):
            raise APIError(
                status_code=409,
                code="setup_data_not_ready",
                message="至少准备好地铁或铁路数据后才能完成设置；也可选择稍后设置。",
            )
        progress.completed = True
        progress.step = "finish"
    elif payload.step is not None:
        progress.step = payload.step
    if payload.dismissed is not None:
        progress.dismissed = payload.dismissed
    if payload.rail_skipped is not None:
        progress.rail_skipped = payload.rail_skipped
    if payload.metro_directory is not None:
        if len(payload.metro_directory) > 480:
            raise APIError(
                status_code=422, code="setup_path_too_long", message="目录路径过长。"
            )
        put_meta(db, "setup.metro_directory", payload.metro_directory)
    save_progress(db, progress)
    return progress


@router.get("/checks", response_model=SetupChecks)
def check_environment(db: Session = Depends(get_db)) -> SetupChecks:
    return environment_checks(db, get_settings())


@router.post("/rail/check", response_model=SetupChecks)
def check_rail_setup(payload: RailSetupConfig) -> SetupChecks:
    return rail_checks(get_settings().model_copy(update=config_updates(payload)))


@router.post("/rail/start", response_model=RailServiceState, status_code=202)
def start_rail_service(
    payload: RailSetupConfig, request: Request, db: Session = Depends(get_db)
) -> RailServiceState:
    controller = service_controller(request)
    # Configuration and launch reservation are serialized for this local service.
    with controller.configuration_lock:
        components = cast(ComponentInstaller, request.app.state.rail_components)
        if components.snapshot().status in {"downloading", "installing"}:
            raise APIError(
                status_code=409,
                code="rail_components_installing",
                message="铁路组件正在准备，请完成后再启动。",
            )
        state = controller.snapshot()
        if state.status == "starting":
            raise APIError(
                status_code=409,
                code="rail_service_starting",
                message="铁路服务正在启动，请等待当前任务结束。",
            )
        if state.status == "ready" and payload != current_rail_config(get_settings()):
            raise APIError(
                status_code=409,
                code="rail_service_running",
                message="铁路服务已启动；修改图配置前请先关闭并重新启动应用。",
            )
        try:
            save_rail_preferences(db, get_settings(), payload, controller.locked_fields)
            return controller.start()
        except RailSidecarError as error:
            raise APIError(
                status_code=409, code=error.code, message=str(error)
            ) from error


@router.post("/rail/components", response_model=ComponentState, status_code=202)
def prepare_rail_components(
    payload: ComponentPrepareRequest, request: Request
) -> ComponentState:
    controller = service_controller(request)
    with controller.configuration_lock:
        if controller.snapshot().status in {"starting", "ready"}:
            raise APIError(
                status_code=409,
                code="rail_service_running",
                message="铁路服务正在运行，请关闭并重新打开应用后准备组件。",
            )
        installer = cast(ComponentInstaller, request.app.state.rail_components)
        try:
            return installer.start()
        except ComponentError as error:
            raise APIError(
                status_code=409, code="rail_components_unavailable", message=str(error)
            ) from error
