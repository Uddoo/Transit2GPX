"""Add provider-specific railway station references to CSV review rows."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0005"
down_revision: str | Sequence[str] | None = "20260821_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("import_row") as batch_op:
        batch_op.add_column(
            sa.Column("matched_rail_start_station_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("matched_rail_end_station_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_import_row_rail_start_station",
            "rail_station",
            ["matched_rail_start_station_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_import_row_rail_end_station",
            "rail_station",
            ["matched_rail_end_station_id"],
            ["id"],
        )


def downgrade() -> None:
    connection = op.get_bind()
    rail_reference_count = connection.scalar(
        sa.text(
            "SELECT count(*) FROM import_row "
            "WHERE matched_rail_start_station_id IS NOT NULL "
            "OR matched_rail_end_station_id IS NOT NULL"
        )
    )
    if rail_reference_count:
        raise RuntimeError(
            "Cannot downgrade while CSV review rows reference rail stations; "
            "commit, cancel, or remove those import batches first."
        )
    with op.batch_alter_table("import_row") as batch_op:
        batch_op.drop_constraint("fk_import_row_rail_end_station", type_="foreignkey")
        batch_op.drop_constraint("fk_import_row_rail_start_station", type_="foreignkey")
        batch_op.drop_column("matched_rail_end_station_id")
        batch_op.drop_column("matched_rail_start_station_id")
