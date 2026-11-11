"""D-141: the AI's reading size goes to Automatic (up to 32,768 tokens).

The user asked on 2026-11-03 to make the AI read more. A reading size chosen below 16,384
cut off Metis's evidence, so it is reset to Automatic; bigger choices are kept.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-03 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE settings SET value = '0' "
            "WHERE key = 'ai.num_ctx' AND CAST(value AS INTEGER) < 16384"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE settings SET value = '8192' WHERE key = 'ai.num_ctx' AND value = '0'")
    )
