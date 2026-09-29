from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.db.session import get_db
from app.exports.gpx import (
    ExportOptions,
    ExportValidationError,
    create_export_plan,
    render_gpx,
    track_segments,
)

router = APIRouter(prefix="/exports", tags=["exports"])


class ExportRequest(BaseModel):
    mode: Literal["journeys", "coverage"] = "coverage"
    max_segment_length_m: Literal[15, 25, 50] | None = 25
    rail_max_segment_length_m: Literal[100, 200, 500] | None = 200
    journey_ids: list[int] = Field(default_factory=list, max_length=5000)
    city_id: int | None = Field(default=None, gt=0)
    line_id: int | None = Field(default=None, gt=0)
    traveled_from: date | None = None
    traveled_to: date | None = None


class GPXRequest(ExportRequest):
    preview_token: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ExportPreviewResponse(BaseModel):
    preview_token: str
    journey_count: int
    edge_count: int
    unique_edge_count: int
    distance_m: float
    track_count: int
    segment_count: int
    dataset_version_ids: list[int]
    rail_dataset_version_ids: list[int]
    rail_graph_versions: list[str]
    blocking_errors: list[str]
    warnings: list[str]


def _options(request: ExportRequest) -> ExportOptions:
    if (
        request.traveled_from is not None
        and request.traveled_to is not None
        and request.traveled_from > request.traveled_to
    ):
        raise APIError(
            status_code=422,
            code="invalid_date_range",
            message="结束日期不能早于起始日期。",
        )
    return ExportOptions(
        mode=request.mode,
        max_segment_length_m=request.max_segment_length_m,
        rail_max_segment_length_m=request.rail_max_segment_length_m,
        journey_ids=tuple(sorted(set(request.journey_ids))),
        city_id=request.city_id,
        line_id=request.line_id,
        traveled_from=request.traveled_from,
        traveled_to=request.traveled_to,
    )


@router.post("/preview", response_model=ExportPreviewResponse)
def preview_export(
    request: ExportRequest,
    db: Session = Depends(get_db),
) -> ExportPreviewResponse:
    try:
        plan = create_export_plan(db, _options(request))
    except ExportValidationError as exc:
        raise APIError(
            status_code=409,
            code="export_blocked",
            message="导出前校验未通过。",
            details={"errors": [str(exc)]},
        ) from exc
    tracks = track_segments(plan)
    segment_count = sum(len(segments) for _, segments in tracks)
    rail_legs = [leg for leg in plan.legs if leg.transport_mode == "rail"]
    rail_dataset_ids = sorted({leg.dataset_version_id for leg in rail_legs})
    rail_graph_versions = sorted(
        {leg.graph_version for leg in rail_legs if leg.graph_version is not None}
    )
    warnings = (
        ["铁路轨迹来源：© OpenStreetMap contributors（ODbL）"] if rail_legs else []
    )
    if len(rail_dataset_ids) > 1:
        warnings.append("包含多个铁路数据版本；coverage 仅在各版本内部去重。")
    return ExportPreviewResponse(
        preview_token=plan.token,
        journey_count=len(plan.journeys),
        edge_count=plan.edge_count,
        unique_edge_count=plan.unique_edge_count,
        distance_m=plan.distance_m,
        track_count=len(tracks),
        segment_count=segment_count,
        dataset_version_ids=sorted(
            {
                leg.dataset_version_id
                for leg in plan.legs
                if leg.transport_mode == "metro"
            }
        ),
        rail_dataset_version_ids=rail_dataset_ids,
        rail_graph_versions=rail_graph_versions,
        blocking_errors=[] if plan.journeys else ["没有符合条件的已保存行程"],
        warnings=warnings,
    )


@router.post("/gpx")
def download_gpx(
    request: GPXRequest,
    db: Session = Depends(get_db),
) -> Response:
    try:
        plan = create_export_plan(db, _options(request))
        if plan.token != request.preview_token:
            raise APIError(
                status_code=409,
                code="export_preview_expired",
                message="行程已经变化，请重新预览导出。",
            )
        if not plan.journeys:
            raise APIError(
                status_code=409,
                code="export_empty",
                message="没有可导出的行程。",
            )
        content = render_gpx(plan)
    except ExportValidationError as exc:
        raise APIError(
            status_code=409,
            code="export_blocked",
            message="GPX 生成前校验未通过。",
            details={"errors": [str(exc)]},
        ) from exc
    filename = f"transit2gpx_{date.today().isoformat()}.gpx"
    return Response(
        content=content,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
