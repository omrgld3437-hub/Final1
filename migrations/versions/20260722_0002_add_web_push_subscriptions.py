"""add account-scoped web push subscriptions

Revision ID: 0002_web_push_subscriptions
Revises: 0001_add_max_buy_levels
Create Date: 2026-07-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_web_push_subscriptions"
down_revision = "0001_add_max_buy_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "web_push_subscriptions" in inspector.get_table_names():
        return
    op.create_table(
        "web_push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("endpoint", name="uq_web_push_subscriptions_endpoint"),
    )
    op.create_index("ix_web_push_subscriptions_user_id", "web_push_subscriptions", ["user_id"])
    op.create_index("ix_web_push_subscriptions_account_id", "web_push_subscriptions", ["account_id"])
    op.create_index("ix_web_push_subscriptions_revoked_at", "web_push_subscriptions", ["revoked_at"])
    op.create_index("ix_web_push_account_active", "web_push_subscriptions", ["account_id", "revoked_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "web_push_subscriptions" in inspector.get_table_names():
        op.drop_table("web_push_subscriptions")
