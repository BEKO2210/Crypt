"""SQLAlchemy ORM models.

Notes
-----
* ``Score`` is append-only: re-scoring a subnet always inserts a new row.
* ``raw_json`` on :class:`Subnet` is the verbatim SDK payload, kept for
  forward-compatibility when the SDK adds new fields.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Subnet(Base):
    __tablename__ = "subnets"

    netuid: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_hotkey: Mapped[str | None] = mapped_column(String(64), nullable=True)
    emission: Mapped[float | None] = mapped_column(Float, nullable=True)
    tempo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    burn_cost_tao: Mapped[float | None] = mapped_column(Float, nullable=True)
    recycle: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_validators: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_miners: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alpha_in: Mapped[float | None] = mapped_column(Float, nullable=True)
    alpha_out: Mapped[float | None] = mapped_column(Float, nullable=True)
    tao_in: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    notes: Mapped[list[Note]] = relationship(
        "Note", back_populates="subnet", cascade="all, delete-orphan"
    )
    scores: Mapped[list[Score]] = relationship(
        "Score", back_populates="subnet", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list[Snapshot]] = relationship(
        "Snapshot", back_populates="subnet", cascade="all, delete-orphan"
    )


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (UniqueConstraint("netuid", name="uq_notes_netuid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    netuid: Mapped[int] = mapped_column(
        Integer, ForeignKey("subnets.netuid", ondelete="CASCADE"), nullable=False
    )
    task_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    repo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    repo_quality_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    hardware_required: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entry_difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    risk_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    opportunity_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    subnet: Mapped[Subnet] = relationship("Subnet", back_populates="notes")


class Score(Base):
    """Append-only score history. Never UPDATE: always INSERT."""

    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    netuid: Mapped[int] = mapped_column(
        Integer, ForeignKey("subnets.netuid", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    developer_fit: Mapped[int] = mapped_column(Integer, nullable=False)
    hardware_fit: Mapped[int] = mapped_column(Integer, nullable=False)
    competition_level: Mapped[int] = mapped_column(Integer, nullable=False)
    repo_quality: Mapped[int] = mapped_column(Integer, nullable=False)
    reward_potential: Mapped[int] = mapped_column(Integer, nullable=False)
    ecosystem_momentum: Mapped[int] = mapped_column(Integer, nullable=False)
    weighted_total: Mapped[float] = mapped_column(Float, nullable=False)
    weights_snapshot: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    subnet: Mapped[Subnet] = relationship("Subnet", back_populates="scores")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    netuid: Mapped[int] = mapped_column(
        Integer, ForeignKey("subnets.netuid", ondelete="CASCADE"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    subnet: Mapped[Subnet] = relationship("Subnet", back_populates="snapshots")


class UserSettings(Base):
    """Singleton row holding the user's profile + custom weights.

    The application enforces a single row (id=1) in code; the table itself
    just behaves like a normal table for migration simplicity.
    """

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    skill_profile: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    hardware_profile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weights: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    rpc_url: Mapped[str | None] = mapped_column(String(256), nullable=True)
    cache_ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


__all__ = ["Base", "Subnet", "Note", "Score", "Snapshot", "UserSettings"]
