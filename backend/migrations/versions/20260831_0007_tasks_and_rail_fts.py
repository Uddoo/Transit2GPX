"""Add persistent application tasks and railway station FTS5 index."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0007"
down_revision: str | Sequence[str] | None = "20260821_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RAIL_FTS_STATEMENTS = (
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS rail_station_fts USING fts5(
      station_id UNINDEXED, rail_dataset_version_id UNINDEXED,
      province_name UNINDEXED, city_name UNINDEXED, name_cn, name_en,
      pinyin_full, pinyin_initials, station_code, aliases,
      tokenize='unicode61'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS rail_station_fts_insert
    AFTER INSERT ON rail_station BEGIN
      INSERT INTO rail_station_fts(
        rowid, station_id, rail_dataset_version_id, province_name, city_name,
        name_cn, name_en, pinyin_full, pinyin_initials, station_code, aliases
      ) VALUES (
        new.id, new.id, new.rail_dataset_version_id,
        coalesce(new.province_name, ''), coalesce(new.city_name, ''),
        new.name_cn, coalesce(new.name_en, ''), coalesce(new.pinyin_full, ''),
        coalesce(new.pinyin_initials, ''), coalesce(new.station_code, ''), ''
      );
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS rail_station_fts_update
    AFTER UPDATE ON rail_station BEGIN
      UPDATE rail_station_fts SET
        rail_dataset_version_id=new.rail_dataset_version_id,
        province_name=coalesce(new.province_name, ''),
        city_name=coalesce(new.city_name, ''), name_cn=new.name_cn,
        name_en=coalesce(new.name_en, ''),
        pinyin_full=coalesce(new.pinyin_full, ''),
        pinyin_initials=coalesce(new.pinyin_initials, ''),
        station_code=coalesce(new.station_code, '')
      WHERE rowid=new.id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS rail_station_fts_delete
    AFTER DELETE ON rail_station BEGIN
      DELETE FROM rail_station_fts WHERE rowid=old.id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS rail_station_alias_fts_insert
    AFTER INSERT ON rail_station_alias BEGIN
      UPDATE rail_station_fts SET aliases=(
        SELECT coalesce(group_concat(alias, ' '), '')
        FROM rail_station_alias WHERE station_id=new.station_id
      ) WHERE rowid=new.station_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS rail_station_alias_fts_update
    AFTER UPDATE ON rail_station_alias BEGIN
      UPDATE rail_station_fts SET aliases=(
        SELECT coalesce(group_concat(alias, ' '), '')
        FROM rail_station_alias WHERE station_id=old.station_id
      ) WHERE rowid=old.station_id;
      UPDATE rail_station_fts SET aliases=(
        SELECT coalesce(group_concat(alias, ' '), '')
        FROM rail_station_alias WHERE station_id=new.station_id
      ) WHERE rowid=new.station_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS rail_station_alias_fts_delete
    AFTER DELETE ON rail_station_alias BEGIN
      UPDATE rail_station_fts SET aliases=(
        SELECT coalesce(group_concat(alias, ' '), '')
        FROM rail_station_alias WHERE station_id=old.station_id
      ) WHERE rowid=old.station_id;
    END
    """,
    """
    INSERT OR REPLACE INTO rail_station_fts(
      rowid, station_id, rail_dataset_version_id, province_name, city_name,
      name_cn, name_en, pinyin_full, pinyin_initials, station_code, aliases
    )
    SELECT s.id, s.id, s.rail_dataset_version_id,
           coalesce(s.province_name, ''), coalesce(s.city_name, ''),
           s.name_cn, coalesce(s.name_en, ''), coalesce(s.pinyin_full, ''),
           coalesce(s.pinyin_initials, ''), coalesce(s.station_code, ''),
           coalesce((SELECT group_concat(a.alias, ' ')
                     FROM rail_station_alias a WHERE a.station_id=s.id), '')
    FROM rail_station s
    """,
)


def upgrade() -> None:
    op.create_table(
        "app_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_type", sa.String(length=160)),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_app_task_status",
        ),
    )
    op.create_index("ix_app_task_status_id", "app_task", ["status", "id"])
    op.create_index(
        "ix_app_task_resource", "app_task", ["kind", "resource_id", "status"]
    )
    for statement in _RAIL_FTS_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    active_tasks = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM app_task WHERE status IN ('queued', 'running')"
            )
        )
        .scalar_one()
    )
    if active_tasks:
        raise RuntimeError("存在未完成的持久化任务，拒绝删除任务表。")
    for trigger in (
        "rail_station_alias_fts_delete",
        "rail_station_alias_fts_update",
        "rail_station_alias_fts_insert",
        "rail_station_fts_delete",
        "rail_station_fts_update",
        "rail_station_fts_insert",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.execute("DROP TABLE IF EXISTS rail_station_fts")
    op.drop_index("ix_app_task_resource", table_name="app_task")
    op.drop_index("ix_app_task_status_id", table_name="app_task")
    op.drop_table("app_task")
