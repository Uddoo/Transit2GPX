from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DatasetVersion(Base):
    __tablename__ = "dataset_version"
    __table_args__ = (
        UniqueConstraint("source_name", "source_version", "checksum"),
        CheckConstraint(
            "status IN ('staging', 'checking', 'ready', 'failed', "
            "'cancelled', 'retired')",
            name="ck_dataset_version_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_version: Mapped[str] = mapped_column(String(120), nullable=False)
    captured_at: Mapped[str | None] = mapped_column(String(40))
    license: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    importer_schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    route_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stop_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cities: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_cities: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ready_lines: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_lines: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False)


class City(Base):
    __tablename__ = "city"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "source_city_code"),
        CheckConstraint(
            "status IN ('checking', 'ready', 'blocked')", name="ck_city_status"
        ),
        CheckConstraint("center_lon BETWEEN -180 AND 180", name="ck_city_lon"),
        CheckConstraint("center_lat BETWEEN -90 AND 90", name="ck_city_lat"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_city_code: Mapped[str] = mapped_column(String(100), nullable=False)
    name_cn: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    name_en: Mapped[str | None] = mapped_column(String(200))
    center_lon: Mapped[float] = mapped_column(Float, nullable=False)
    center_lat: Mapped[float] = mapped_column(Float, nullable=False)
    min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    max_lon: Mapped[float] = mapped_column(Float, nullable=False)
    max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)


class Line(Base):
    __tablename__ = "line"
    __table_args__ = (
        UniqueConstraint("city_id", "normalized_name"),
        CheckConstraint(
            "status IN ('checking', 'ready', 'blocked')", name="ck_line_status"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int] = mapped_column(
        ForeignKey("city.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name_cn: Mapped[str] = mapped_column(String(160), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(240))
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_color: Mapped[str | None] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)


class RouteVariant(Base):
    __tablename__ = "route_variant"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "source_route_id"),
        CheckConstraint(
            "quality_status IN ('checking', 'ready', 'blocked')",
            name="ck_route_variant_quality",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(
        ForeignKey("line.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_route_id: Mapped[str] = mapped_column(String(240), nullable=False)
    source_route_name: Mapped[str | None] = mapped_column(String(300))
    direction_name: Mapped[str | None] = mapped_column(String(160))
    is_loop: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_branch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    geometry_wkb: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    match_method: Mapped[str] = mapped_column(String(80), nullable=False)
    quality_status: Mapped[str] = mapped_column(String(20), nullable=False)
    quality_flags_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )


class Station(Base):
    __tablename__ = "station"
    __table_args__ = (
        UniqueConstraint("city_id", "normalized_name", "cluster_no"),
        CheckConstraint("lon BETWEEN -180 AND 180", name="ck_station_lon"),
        CheckConstraint("lat BETWEEN -90 AND 90", name="ck_station_lat"),
        Index("ix_station_city_name", "city_id", "normalized_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int] = mapped_column(
        ForeignKey("city.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name_cn: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False)
    pinyin_full: Mapped[str | None] = mapped_column(String(400), index=True)
    pinyin_initials: Mapped[str | None] = mapped_column(String(120), index=True)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    cluster_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class StationAlias(Base):
    __tablename__ = "station_alias"
    __table_args__ = (UniqueConstraint("station_id", "normalized_alias", "language"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(
        ForeignKey("station.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(
        String(340), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False)


class RouteStop(Base):
    __tablename__ = "route_stop"
    __table_args__ = (
        UniqueConstraint("route_variant_id", "source_sequence"),
        UniqueConstraint("route_variant_id", "source_stop_id"),
        CheckConstraint("source_lon BETWEEN -180 AND 180", name="ck_route_stop_lon"),
        CheckConstraint("source_lat BETWEEN -90 AND 90", name="ck_route_stop_lat"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_variant_id: Mapped[int] = mapped_column(
        ForeignKey("route_variant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    station_id: Mapped[int] = mapped_column(
        ForeignKey("station.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_stop_id: Mapped[str] = mapped_column(String(240), nullable=False)
    source_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_lon: Mapped[float] = mapped_column(Float, nullable=False)
    source_lat: Mapped[float] = mapped_column(Float, nullable=False)
    projected_measure_m: Mapped[float] = mapped_column(Float, nullable=False)
    projection_error_m: Mapped[float] = mapped_column(Float, nullable=False)
    match_quality: Mapped[str] = mapped_column(String(40), nullable=False)


class RouteEdge(Base):
    __tablename__ = "route_edge"
    __table_args__ = (
        UniqueConstraint("route_variant_id", "sequence_from", "sequence_to"),
        CheckConstraint("distance_m > 0", name="ck_route_edge_distance"),
        CheckConstraint(
            "quality_status IN ('checking', 'ready', 'blocked')",
            name="ck_route_edge_quality",
        ),
        Index("ix_route_edge_bbox", "min_lon", "min_lat", "max_lon", "max_lat"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_variant_id: Mapped[int] = mapped_column(
        ForeignKey("route_variant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_route_stop_id: Mapped[int] = mapped_column(
        ForeignKey("route_stop.id", ondelete="CASCADE"), nullable=False
    )
    to_route_stop_id: Mapped[int] = mapped_column(
        ForeignKey("route_stop.id", ondelete="CASCADE"), nullable=False
    )
    from_station_id: Mapped[int] = mapped_column(
        ForeignKey("station.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    to_station_id: Mapped[int] = mapped_column(
        ForeignKey("station.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sequence_from: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_to: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    geometry_wkb: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    max_lon: Mapped[float] = mapped_column(Float, nullable=False)
    max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    quality_status: Mapped[str] = mapped_column(String(20), nullable=False)
    quality_flags_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )


class Journey(Base):
    __tablename__ = "journey"
    __table_args__ = (
        UniqueConstraint("journey_code"),
        CheckConstraint(
            "source_type IN ('manual', 'map', 'csv')", name="ck_journey_source"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journey_code: Mapped[str] = mapped_column(String(120), nullable=False)
    traveled_at: Mapped[date | None] = mapped_column(Date)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class JourneyLeg(Base):
    __tablename__ = "journey_leg"
    __table_args__ = (
        UniqueConstraint("journey_id", "leg_no"),
        CheckConstraint(
            "resolution_status IN ('resolved', 'needs_review', 'invalidated')",
            name="ck_journey_leg_resolution",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journey_id: Mapped[int] = mapped_column(
        ForeignKey("journey.id", ondelete="CASCADE"), nullable=False, index=True
    )
    leg_no: Mapped[int] = mapped_column(Integer, nullable=False)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    city_id: Mapped[int] = mapped_column(
        ForeignKey("city.id", ondelete="RESTRICT"), nullable=False
    )
    line_id: Mapped[int] = mapped_column(
        ForeignKey("line.id", ondelete="RESTRICT"), nullable=False
    )
    route_variant_id: Mapped[int] = mapped_column(
        ForeignKey("route_variant.id", ondelete="RESTRICT"), nullable=False
    )
    start_station_id: Mapped[int] = mapped_column(
        ForeignKey("station.id", ondelete="RESTRICT"), nullable=False
    )
    end_station_id: Mapped[int] = mapped_column(
        ForeignKey("station.id", ondelete="RESTRICT"), nullable=False
    )
    direction: Mapped[str | None] = mapped_column(String(120))
    resolution_status: Mapped[str] = mapped_column(String(30), nullable=False)
    resolution_message: Mapped[str | None] = mapped_column(Text)
    candidate_digest: Mapped[str] = mapped_column(String(100), nullable=False)


class JourneyLegEdge(Base):
    __tablename__ = "journey_leg_edge"
    __table_args__ = (
        UniqueConstraint("journey_leg_id", "order_no"),
        UniqueConstraint("journey_leg_id", "route_edge_id", "order_no"),
    )

    journey_leg_id: Mapped[int] = mapped_column(
        ForeignKey("journey_leg.id", ondelete="CASCADE"), primary_key=True
    )
    route_edge_id: Mapped[int] = mapped_column(
        ForeignKey("route_edge.id", ondelete="RESTRICT"), primary_key=True
    )
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    reversed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ImportBatch(Base):
    __tablename__ = "import_batch"
    __table_args__ = (
        CheckConstraint(
            "status IN ('parsing', 'ready_for_review', 'committing', 'committed', "
            "'failed', 'cancelled')",
            name="ck_import_batch_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    encoding: Mapped[str] = mapped_column(String(20), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resolved_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportRow(Base):
    __tablename__ = "import_row"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_no"),
        CheckConstraint(
            "resolution_status IN ('resolved', 'needs_review', 'unresolved', "
            "'ignored', 'committed')",
            name="ck_import_row_resolution",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    normalized_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(30), nullable=False)
    matched_city_id: Mapped[int | None] = mapped_column(ForeignKey("city.id"))
    matched_line_id: Mapped[int | None] = mapped_column(ForeignKey("line.id"))
    matched_start_station_id: Mapped[int | None] = mapped_column(
        ForeignKey("station.id")
    )
    matched_end_station_id: Mapped[int | None] = mapped_column(ForeignKey("station.id"))
    selected_candidate_id: Mapped[str | None] = mapped_column(String(160))
    candidate_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
