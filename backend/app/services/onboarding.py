from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.resources import resource_path
from app.db.base import AppMeta
from app.rail.sidecar import RailSidecarError, fetch_sidecar_info
from app.rail.supervisor import (
    _graph_runtime,
    _java_executable,
    _resolve_pbf_path,
    _verify_identity,
)

SetupStep = Literal["check", "metro", "rail", "finish"]
RAIL_FIELDS = {
    "graph_root": "rail_graph_root",
    "graph_version": "rail_graph_version",
    "pbf_path": "rail_pbf_path",
    "jar_path": "rail_sidecar_jar",
    "java_home": "rail_java_home",
}


class SetupProgress(BaseModel):
    step: SetupStep = "check"
    dismissed: bool = False
    completed: bool = False
    rail_skipped: bool = False


class SetupCheck(BaseModel):
    id: str
    title: str
    status: Literal["passed", "warning", "failed"]
    detail: str
    remedy: str | None = None


class SetupChecks(BaseModel):
    checks: list[SetupCheck]
    can_continue: bool


class RailSetupConfig(BaseModel):
    graph_root: str = Field(min_length=1, max_length=480)
    graph_version: str = Field(
        default="active", pattern=r"^[A-Za-z0-9._-]+$", max_length=160
    )
    pbf_path: str | None = Field(default=None, max_length=480)
    jar_path: str | None = Field(default=None, max_length=480)
    java_home: str | None = Field(default=None, max_length=480)

    @field_validator("graph_root", "pbf_path", "jar_path", "java_home", mode="before")
    @classmethod
    def local_path(cls, value: Any) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("请填写本机绝对路径")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if not Path(value).expanduser().is_absolute():
            raise ValueError("请填写本机绝对路径")
        return str(Path(value).expanduser().resolve())


def get_progress(db: Session) -> tuple[SetupProgress, bool]:
    row = db.get(AppMeta, "setup.progress")
    if row is None:
        return SetupProgress(), False
    try:
        return SetupProgress.model_validate_json(row.value), True
    except ValueError:
        return SetupProgress(), True


def put_meta(db: Session, key: str, value: str) -> None:
    row = db.get(AppMeta, key)
    if row is None:
        db.add(AppMeta(key=key, value=value))
    else:
        row.value = value


def save_progress(db: Session, progress: SetupProgress) -> None:
    put_meta(db, "setup.progress", progress.model_dump_json())
    db.commit()


def current_rail_config(settings: Settings) -> RailSetupConfig:
    pbf_path = settings.rail_pbf_path
    if pbf_path is None and settings.rail_graph_version:
        try:
            _, metadata = _graph_runtime(settings)
            pbf_path = _resolve_pbf_path(settings, metadata)
        except RailSidecarError:
            pass
    return RailSetupConfig(
        graph_root=str(settings.resolved_rail_graph_root),
        graph_version=settings.rail_graph_version or "active",
        pbf_path=str(pbf_path) if pbf_path else None,
        jar_path=str(settings.resolved_rail_sidecar_jar),
        java_home=str(settings.rail_java_home) if settings.rail_java_home else None,
    )


def config_updates(config: RailSetupConfig) -> dict[str, Any]:
    return {
        **{
            field: (Path(value) if value and key != "graph_version" else value)
            for key, field in RAIL_FIELDS.items()
            for value in [getattr(config, key)]
        },
        "rail_enabled": True,
        "rail_sidecar_managed": True,
    }


def restore_rail_preferences(db: Session, settings: Settings) -> None:
    # Explicit launch arguments/environment always take precedence.
    locked = set(settings.model_fields_set)
    allowed = {*RAIL_FIELDS.values(), "rail_enabled", "rail_sidecar_managed"}
    for row in db.scalars(select(AppMeta).where(AppMeta.key.like("setup.rail.%"))):
        name = row.key.removeprefix("setup.rail.")
        if name not in allowed or name in locked:
            continue
        try:
            value = json.loads(row.value)
            if name in {"rail_enabled", "rail_sidecar_managed"}:
                if not isinstance(value, bool):
                    continue
            elif value is not None:
                if not isinstance(value, str):
                    continue
                if name == "rail_graph_version":
                    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
                        continue
                else:
                    if not Path(value).is_absolute():
                        continue
                    value = Path(value)
            setattr(settings, name, value)
        except (ValueError, TypeError):
            continue


def save_rail_preferences(
    db: Session, settings: Settings, config: RailSetupConfig, locked: set[str]
) -> None:
    updates = config_updates(config)
    for name, value in updates.items():
        if name in locked and getattr(settings, name) != value:
            raise RailSidecarError(
                "rail_launch_override",
                "铁路选项由启动参数或环境变量固定，请调整启动配置后重启，或保留当前值。",
            )
    for name, value in updates.items():
        put_meta(
            db,
            f"setup.rail.{name}",
            json.dumps(
                str(value) if isinstance(value, Path) else value, ensure_ascii=False
            ),
        )
    db.commit()
    for name, value in updates.items():
        setattr(settings, name, value)


@lru_cache
def schema_head() -> str | None:
    config = Config()
    config.set_main_option(
        "script_location", str(resource_path("backend", "migrations"))
    )
    return ScriptDirectory.from_config(config).get_current_head()


def environment_checks(db: Session, settings: Settings) -> SetupChecks:
    checks = [
        SetupCheck(
            id="service", title="本地服务", status="passed", detail="服务连接正常"
        )
    ]
    try:
        current = db.scalar(text("SELECT version_num FROM alembic_version"))
        ready = current == schema_head()
    except Exception:
        db.rollback()
        ready = False
    checks.append(
        SetupCheck(
            id="database",
            title="本地数据库",
            status="passed" if ready else "failed",
            detail="结构与当前版本一致" if ready else "数据库需要升级",
            remedy=None
            if ready
            else "重新启动安装包以完成升级；源码版请运行数据库升级命令。",
        )
    )
    writable = settings.data_dir.is_dir() and os.access(settings.data_dir, os.W_OK)
    checks.append(
        SetupCheck(
            id="storage",
            title="数据目录",
            status="passed" if writable else "failed",
            detail="可保存行程和导入任务" if writable else "数据目录不可写",
            remedy=None if writable else "检查数据目录的写入权限，再重新检查。",
        )
    )
    try:
        free_gb = shutil.disk_usage(settings.data_dir).free / 1024**3
        checks.append(
            SetupCheck(
                id="disk",
                title="可用空间",
                status="passed" if free_gb >= 1 else "warning",
                detail=f"剩余 {free_gb:.1f} GB，用于存放线路数据和轨迹文件",
                remedy=None
                if free_gb >= 1
                else "空间不足 1 GB，导入大型数据前建议清理空间。",
            )
        )
    except OSError:
        checks.append(
            SetupCheck(
                id="disk",
                title="可用空间",
                status="warning",
                detail="暂时无法读取磁盘空间",
                remedy="确认数据目录所在磁盘已挂载。",
            )
        )
    return SetupChecks(
        checks=checks, can_continue=all(item.status != "failed" for item in checks)
    )


def rail_checks(settings: Settings) -> SetupChecks:
    # A matching external service can be reused without installing another JVM/JAR.
    try:
        _, metadata = _graph_runtime(settings)
        info = fetch_sidecar_info(settings.rail_sidecar_url, 0.5)
        _verify_identity(info, metadata)
        _resolve_pbf_path(settings, metadata)
    except RailSidecarError as error:
        if error.code == "rail_sidecar_identity_mismatch":
            return SetupChecks(
                can_continue=False,
                checks=[
                    SetupCheck(
                        id="service_identity",
                        title="运行中的铁路服务",
                        status="failed",
                        detail=str(error),
                        remedy="请让正在运行的铁路服务与所选图版本一致，再重新检查。",
                    )
                ],
            )
    else:
        return SetupChecks(
            can_continue=True,
            checks=[
                SetupCheck(
                    id="service",
                    title="运行中的铁路服务",
                    status="passed",
                    detail="版本身份一致，将复用现有服务",
                ),
                SetupCheck(
                    id="pbf",
                    title="铁路 PBF",
                    status="passed",
                    detail="已找到对应文件，可继续建立车站索引",
                ),
            ],
        )
    checks: list[SetupCheck] = []
    try:
        java = _java_executable(settings)
        result = subprocess.run(
            [str(java), "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        match = re.search(
            r'version\s+"(\d+)(?:\.(\d+))?', result.stdout + result.stderr
        )
        major = (
            int(match.group(2) or 0)
            if match and match.group(1) == "1"
            else int(match.group(1))
            if match
            else 0
        )
        ready = result.returncode == 0 and major >= 17
        checks.append(
            SetupCheck(
                id="java",
                title="Java 运行环境",
                status="passed" if ready else "failed",
                detail=f"Java {major} 已就绪"
                if ready
                else "没有找到 Java 17 或更高版本",
                remedy=None
                if ready
                else "安装 Java 17+，或在高级设置中填写 Java 目录。",
            )
        )
    except (RailSidecarError, OSError, subprocess.TimeoutExpired):
        checks.append(
            SetupCheck(
                id="java",
                title="Java 运行环境",
                status="failed",
                detail="没有找到可用的 Java",
                remedy="安装 Java 17 或更高版本，或在高级设置中填写 Java 目录。",
            )
        )
    for key, title, path, remedy in (
        (
            "jar",
            "铁路服务文件",
            settings.resolved_rail_sidecar_jar,
            "按铁路准备说明安装服务文件，或在高级设置中填写 JAR 路径。",
        ),
        (
            "config",
            "铁路服务配置",
            settings.resolved_rail_sidecar_config,
            "安装包请重新安装；源码版请检查 rail-routing/config.yml。",
        ),
    ):
        exists = path.is_file()
        checks.append(
            SetupCheck(
                id=key,
                title=title,
                status="passed" if exists else "failed",
                detail="文件已找到" if exists else "文件尚未准备",
                remedy=None if exists else remedy,
            )
        )
    try:
        _, metadata = _graph_runtime(settings)
        checks.append(
            SetupCheck(
                id="graph",
                title="铁路图",
                status="passed",
                detail=f"图版本：{metadata['graph_version']}",
            )
        )
        _resolve_pbf_path(settings, metadata)
        checks.append(
            SetupCheck(
                id="pbf",
                title="铁路 PBF",
                status="passed",
                detail="文件已找到，启动时校验与图版本是否一致",
            )
        )
    except RailSidecarError as error:
        checks.append(
            SetupCheck(
                id="graph_files",
                title="铁路图与 PBF",
                status="failed",
                detail=str(error),
                remedy="核对图目录、版本和 PBF；也可查看准备说明，或先使用地铁。",
            )
        )
    return SetupChecks(
        checks=checks, can_continue=all(item.status != "failed" for item in checks)
    )
