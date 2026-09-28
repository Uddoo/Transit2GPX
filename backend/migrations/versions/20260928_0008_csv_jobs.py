"""Persist CSV processing progress and worker ownership."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0008"
down_revision: str | Sequence[str] | None = "20260831_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_import_row_pending", "import_row", ["batch_id", "error_code", "row_no"]
    )
    op.add_column(
        "import_batch",
        sa.Column("processed_rows", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("import_batch", sa.Column("run_token", sa.String(32), nullable=True))
    op.add_column("import_batch", sa.Column("error_message", sa.Text(), nullable=True))
    op.execute(
        "UPDATE import_batch SET processed_rows = total_rows WHERE status != 'parsing'"
    )


def downgrade() -> None:
    op.drop_index("ix_import_row_pending", table_name="import_row")
    with op.batch_alter_table("import_batch") as batch:
        batch.drop_column("error_message")
        batch.drop_column("run_token")
        batch.drop_column("processed_rows")
