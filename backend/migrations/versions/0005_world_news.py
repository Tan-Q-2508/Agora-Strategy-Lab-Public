"""World news (D-68): what each headline is about (topics), how much it matters to markets
(severity 0–5, impact −1…+1) and where (scope IN / US / WORLD).

The columns are nullable: rows saved before this migration are classified by the news
service the first time it reads them.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("news_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("topics", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("severity", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("impact", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("scope", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("news_items", schema=None) as batch_op:
        batch_op.drop_column("scope")
        batch_op.drop_column("impact")
        batch_op.drop_column("severity")
        batch_op.drop_column("topics")
