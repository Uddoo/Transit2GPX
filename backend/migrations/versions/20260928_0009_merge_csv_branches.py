"""Merge the pre-merge CSV revision with the task and CSV mainline revisions."""

from collections.abc import Sequence

revision: str = "20260928_0009"
down_revision: str | Sequence[str] | None = ("20260928_0008", "20260928_0007")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
