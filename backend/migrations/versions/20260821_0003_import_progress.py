"""Persist CPTOND import progress and failure diagnostics."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0003"
down_revision: str | Sequence[str] | None = "20260820_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("dataset_version") as batch_op:
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column("route_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("stop_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("total_cities", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "processed_cities", sa.Integer(), server_default="0", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column("ready_lines", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("blocked_lines", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("error_code", sa.String(length=100)))
        batch_op.add_column(sa.Column("error_message", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("dataset_version") as batch_op:
        batch_op.drop_column("error_message")
        batch_op.drop_column("error_code")
        batch_op.drop_column("blocked_lines")
        batch_op.drop_column("ready_lines")
        batch_op.drop_column("processed_cities")
        batch_op.drop_column("total_cities")
        batch_op.drop_column("stop_count")
        batch_op.drop_column("route_count")
        batch_op.drop_column("completed_at")
