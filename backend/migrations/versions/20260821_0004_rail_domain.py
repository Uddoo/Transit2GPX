"""Add shared journey mode and immutable railway snapshot schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0004"
down_revision: str | Sequence[str] | None = "20260821_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rail_dataset_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("source_timestamp", sa.String(length=40), nullable=False),
        sa.Column("pbf_checksum", sa.String(length=128), nullable=False),
        sa.Column("extract_region", sa.String(length=240), nullable=False),
        sa.Column("graph_version", sa.String(length=160), nullable=False),
        sa.Column("profile_version", sa.String(length=120), nullable=False),
        sa.Column("openrailrouting_version", sa.String(length=120), nullable=False),
        sa.Column("graphhopper_version", sa.String(length=120), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("license", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("quality_flags_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "status IN ('staging', 'building', 'ready', 'failed', 'retired')",
            name="ck_rail_dataset_version_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph_version"),
        sa.UniqueConstraint("pbf_checksum", "graph_version", "profile_version"),
    )
    op.create_table(
        "rail_station",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rail_dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("osm_type", sa.String(length=20), nullable=False),
        sa.Column("osm_id", sa.Integer(), nullable=False),
        sa.Column("name_cn", sa.String(length=240), nullable=False),
        sa.Column("name_en", sa.String(length=320), nullable=True),
        sa.Column("normalized_name", sa.String(length=280), nullable=False),
        sa.Column("pinyin_full", sa.String(length=480), nullable=True),
        sa.Column("pinyin_initials", sa.String(length=160), nullable=True),
        sa.Column("station_code", sa.String(length=80), nullable=True),
        sa.Column("city_name", sa.String(length=160), nullable=True),
        sa.Column("province_name", sa.String(length=160), nullable=True),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("match_status", sa.String(length=20), nullable=False),
        sa.Column("quality_flags_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("lat BETWEEN -90 AND 90", name="ck_rail_station_lat"),
        sa.CheckConstraint("lon BETWEEN -180 AND 180", name="ck_rail_station_lon"),
        sa.CheckConstraint(
            "match_status IN ('unreviewed', 'ready', 'blocked')",
            name="ck_rail_station_match_status",
        ),
        sa.CheckConstraint(
            "osm_type IN ('node', 'way', 'relation')",
            name="ck_rail_station_osm_type",
        ),
        sa.ForeignKeyConstraint(
            ["rail_dataset_version_id"],
            ["rail_dataset_version.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rail_dataset_version_id", "osm_type", "osm_id"),
    )
    op.create_index(
        "ix_rail_station_dataset_name",
        "rail_station",
        ["rail_dataset_version_id", "normalized_name"],
    )
    for column in (
        "rail_dataset_version_id",
        "pinyin_full",
        "pinyin_initials",
        "station_code",
        "city_name",
        "province_name",
    ):
        op.create_index(f"ix_rail_station_{column}", "rail_station", [column])
    op.create_table(
        "rail_station_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=320), nullable=False),
        sa.Column("normalized_alias", sa.String(length=360), nullable=False),
        sa.Column("alias_type", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=160), nullable=False),
        sa.ForeignKeyConstraint(
            ["station_id"], ["rail_station.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("station_id", "normalized_alias", "alias_type"),
    )
    op.create_index(
        "ix_rail_station_alias_station_id", "rail_station_alias", ["station_id"]
    )
    op.create_index(
        "ix_rail_station_alias_normalized_alias",
        "rail_station_alias",
        ["normalized_alias"],
    )

    with op.batch_alter_table("journey_leg") as batch_op:
        batch_op.add_column(
            sa.Column(
                "transport_mode",
                sa.String(length=20),
                server_default=sa.text("'metro'"),
                nullable=False,
            )
        )
        for column, foreign_key in (
            ("dataset_version_id", "dataset_version.id"),
            ("city_id", "city.id"),
            ("line_id", "line.id"),
            ("route_variant_id", "route_variant.id"),
            ("start_station_id", "station.id"),
            ("end_station_id", "station.id"),
        ):
            del foreign_key
            batch_op.alter_column(column, existing_type=sa.Integer(), nullable=True)
        batch_op.create_check_constraint(
            "ck_journey_leg_transport_mode",
            "transport_mode IN ('metro', 'rail')",
        )
        batch_op.create_check_constraint(
            "ck_journey_leg_provider_refs",
            "(transport_mode = 'metro' AND dataset_version_id IS NOT NULL "
            "AND city_id IS NOT NULL AND line_id IS NOT NULL "
            "AND route_variant_id IS NOT NULL AND start_station_id IS NOT NULL "
            "AND end_station_id IS NOT NULL) OR "
            "(transport_mode = 'rail' AND dataset_version_id IS NULL "
            "AND city_id IS NULL AND line_id IS NULL AND route_variant_id IS NULL "
            "AND start_station_id IS NULL AND end_station_id IS NULL)",
        )

    op.create_table(
        "rail_journey_leg_detail",
        sa.Column("journey_leg_id", sa.Integer(), nullable=False),
        sa.Column("travel_date", sa.Date(), nullable=False),
        sa.Column("train_no", sa.String(length=80), nullable=True),
        sa.Column("train_type", sa.String(length=20), nullable=False),
        sa.Column("routing_profile", sa.String(length=80), nullable=False),
        sa.Column("route_hint", sa.String(length=500), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("selected_candidate_digest", sa.String(length=100), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_rail_journey_confidence",
        ),
        sa.CheckConstraint(
            "train_type IN ('G', 'C', 'D', 'Z', 'T', 'K', 'Y', 'S', 'OTHER')",
            name="ck_rail_journey_train_type",
        ),
        sa.ForeignKeyConstraint(
            ["journey_leg_id"], ["journey_leg.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("journey_leg_id"),
    )
    op.create_index(
        "ix_rail_journey_leg_detail_train_no",
        "rail_journey_leg_detail",
        ["train_no"],
    )
    op.create_table(
        "rail_journey_stop",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("journey_leg_id", sa.Integer(), nullable=False),
        sa.Column("stop_sequence", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=True),
        sa.Column("raw_station_name", sa.String(length=320), nullable=False),
        sa.Column("arrival_time", sa.String(length=20), nullable=True),
        sa.Column("departure_time", sa.String(length=20), nullable=True),
        sa.Column("is_boarding", sa.Boolean(), nullable=False),
        sa.Column("is_alighting", sa.Boolean(), nullable=False),
        sa.Column("match_method", sa.String(length=80), nullable=True),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column("locked_by_user", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "match_confidence IS NULL OR "
            "(match_confidence >= 0 AND match_confidence <= 1)",
            name="ck_rail_journey_stop_confidence",
        ),
        sa.CheckConstraint("stop_sequence > 0", name="ck_rail_journey_stop_sequence"),
        sa.ForeignKeyConstraint(
            ["journey_leg_id"], ["journey_leg.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["station_id"], ["rail_station.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("journey_leg_id", "stop_sequence"),
    )
    op.create_index(
        "ix_rail_journey_stop_journey_leg_id",
        "rail_journey_stop",
        ["journey_leg_id"],
    )
    op.create_index(
        "ix_rail_journey_stop_station_id", "rail_journey_stop", ["station_id"]
    )
    op.create_table(
        "rail_journey_edge_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("journey_leg_id", sa.Integer(), nullable=False),
        sa.Column("order_no", sa.Integer(), nullable=False),
        sa.Column("rail_dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("provider_edge_ref", sa.String(length=240), nullable=True),
        sa.Column("osm_way_id", sa.Integer(), nullable=True),
        sa.Column("from_osm_node_id", sa.Integer(), nullable=True),
        sa.Column("to_osm_node_id", sa.Integer(), nullable=True),
        sa.Column("reversed", sa.Boolean(), nullable=False),
        sa.Column("continuity_group", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("geometry_wkb", sa.LargeBinary(), nullable=False),
        sa.Column("geometry_sha256", sa.String(length=64), nullable=False),
        sa.Column("min_lon", sa.Float(), nullable=False),
        sa.Column("min_lat", sa.Float(), nullable=False),
        sa.Column("max_lon", sa.Float(), nullable=False),
        sa.Column("max_lat", sa.Float(), nullable=False),
        sa.Column("quality_flags_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("continuity_group > 0", name="ck_rail_snapshot_group"),
        sa.CheckConstraint("distance_m > 0", name="ck_rail_snapshot_distance"),
        sa.CheckConstraint("order_no > 0", name="ck_rail_snapshot_order"),
        sa.ForeignKeyConstraint(
            ["journey_leg_id"], ["journey_leg.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["rail_dataset_version_id"],
            ["rail_dataset_version.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("journey_leg_id", "order_no"),
    )
    op.create_index(
        "ix_rail_journey_edge_snapshot_journey_leg_id",
        "rail_journey_edge_snapshot",
        ["journey_leg_id"],
    )
    op.create_index(
        "ix_rail_journey_edge_snapshot_rail_dataset_version_id",
        "rail_journey_edge_snapshot",
        ["rail_dataset_version_id"],
    )
    op.create_index(
        "ix_rail_journey_edge_snapshot_osm_way_id",
        "rail_journey_edge_snapshot",
        ["osm_way_id"],
    )
    op.create_index(
        "ix_rail_snapshot_bbox",
        "rail_journey_edge_snapshot",
        ["min_lon", "min_lat", "max_lon", "max_lat"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    rail_leg_count = connection.scalar(
        sa.text("SELECT count(*) FROM journey_leg WHERE transport_mode = 'rail'")
    )
    if rail_leg_count:
        raise RuntimeError(
            "Cannot downgrade while rail journey legs exist; "
            "export or remove them first."
        )
    op.drop_table("rail_journey_edge_snapshot")
    op.drop_table("rail_journey_stop")
    op.drop_table("rail_journey_leg_detail")
    with op.batch_alter_table("journey_leg") as batch_op:
        batch_op.drop_constraint("ck_journey_leg_provider_refs", type_="check")
        batch_op.drop_constraint("ck_journey_leg_transport_mode", type_="check")
        for column in (
            "dataset_version_id",
            "city_id",
            "line_id",
            "route_variant_id",
            "start_station_id",
            "end_station_id",
        ):
            batch_op.alter_column(column, existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column("transport_mode")
    op.drop_table("rail_station_alias")
    op.drop_table("rail_station")
    op.drop_table("rail_dataset_version")
