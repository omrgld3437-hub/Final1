"""add max_buy_levels guard

Revision ID: 0001_add_max_buy_levels
Revises:
Create Date: 2026-06-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_add_max_buy_levels"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "bots" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("bots")}
    if "max_buy_levels" not in cols:
        op.add_column("bots", sa.Column("max_buy_levels", sa.Integer(), nullable=False, server_default="1"))
    op.execute("UPDATE bots SET max_buy_levels = 1 WHERE max_buy_levels IS NULL OR max_buy_levels < 1")
    try:
        op.create_check_constraint("ck_bots_max_buy_levels_positive", "bots", "max_buy_levels > 0")
    except Exception:
        pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "bots" not in inspector.get_table_names():
        return
    try:
        op.drop_constraint("ck_bots_max_buy_levels_positive", "bots", type_="check")
    except Exception:
        pass
    cols = {c["name"] for c in inspector.get_columns("bots")}
    if "max_buy_levels" in cols:
        op.drop_column("bots", "max_buy_levels")
