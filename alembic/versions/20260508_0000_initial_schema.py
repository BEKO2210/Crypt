"""initial schema

Revision ID: 20260508_0000
Revises:
Create Date: 2026-05-08
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260508_0000"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subnets",
        sa.Column("netuid", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("owner_hotkey", sa.String(length=64), nullable=True),
        sa.Column("emission", sa.Float(), nullable=True),
        sa.Column("tempo", sa.Integer(), nullable=True),
        sa.Column("burn_cost_tao", sa.Float(), nullable=True),
        sa.Column("recycle", sa.Float(), nullable=True),
        sa.Column("n_validators", sa.Integer(), nullable=True),
        sa.Column("n_miners", sa.Integer(), nullable=True),
        sa.Column("max_n", sa.Integer(), nullable=True),
        sa.Column("alpha_in", sa.Float(), nullable=True),
        sa.Column("alpha_out", sa.Float(), nullable=True),
        sa.Column("tao_in", sa.Float(), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("netuid"),
    )

    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("netuid", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=True),
        sa.Column("repo_url", sa.String(length=512), nullable=True),
        sa.Column("repo_quality_notes", sa.Text(), nullable=True),
        sa.Column("hardware_required", sa.String(length=32), nullable=True),
        sa.Column("entry_difficulty", sa.String(length=16), nullable=True),
        sa.Column("risk_notes", sa.Text(), nullable=True),
        sa.Column("opportunity_notes", sa.Text(), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["netuid"], ["subnets.netuid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("netuid", name="uq_notes_netuid"),
    )

    op.create_table(
        "scores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("netuid", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("developer_fit", sa.Integer(), nullable=False),
        sa.Column("hardware_fit", sa.Integer(), nullable=False),
        sa.Column("competition_level", sa.Integer(), nullable=False),
        sa.Column("repo_quality", sa.Integer(), nullable=False),
        sa.Column("reward_potential", sa.Integer(), nullable=False),
        sa.Column("ecosystem_momentum", sa.Integer(), nullable=False),
        sa.Column("weighted_total", sa.Float(), nullable=False),
        sa.Column("weights_snapshot", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["netuid"], ["subnets.netuid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scores_netuid_created_at", "scores", ["netuid", "created_at"])

    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("netuid", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["netuid"], ["subnets.netuid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_snapshots_netuid_captured_at", "snapshots", ["netuid", "captured_at"])

    op.create_table(
        "user_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("skill_profile", sa.Text(), nullable=True),
        sa.Column("skill_tags", sa.JSON(), nullable=False),
        sa.Column("hardware_profile", sa.String(length=32), nullable=True),
        sa.Column("weights", sa.JSON(), nullable=False),
        sa.Column("rpc_url", sa.String(length=256), nullable=True),
        sa.Column("cache_ttl_seconds", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
    op.drop_index("ix_snapshots_netuid_captured_at", table_name="snapshots")
    op.drop_table("snapshots")
    op.drop_index("ix_scores_netuid_created_at", table_name="scores")
    op.drop_table("scores")
    op.drop_table("notes")
    op.drop_table("subnets")
