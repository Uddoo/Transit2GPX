"""Persist railway candidate scoring and timetable provider evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0006"
down_revision: str | Sequence[str] | None = "20260821_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("rail_journey_leg_detail") as batch_op:
        batch_op.add_column(
            sa.Column(
                "timetable_provider",
                sa.String(length=80),
                server_default="legacy",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "scoring_version",
                sa.String(length=120),
                server_default="legacy",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "score_details_json",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "warnings_json",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("rail_journey_leg_detail") as batch_op:
        batch_op.drop_column("warnings_json")
        batch_op.drop_column("score_details_json")
        batch_op.drop_column("scoring_version")
        batch_op.drop_column("timetable_provider")
