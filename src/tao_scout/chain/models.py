"""Pydantic models for chain data.

These are the in-memory shape; persistence uses :mod:`tao_scout.db.models`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SubnetInfo(BaseModel):
    """Decoded subnet info from ``AsyncSubtensor.get_subnet_info``-class calls."""

    model_config = ConfigDict(frozen=True)

    netuid: int = Field(ge=0)
    name: str | None = None
    owner_hotkey: str | None = None
    emission: float | None = None
    tempo: int | None = None
    burn_cost_tao: float | None = None
    recycle: float | None = None
    n_validators: int | None = None
    n_miners: int | None = None
    max_n: int | None = None
    alpha_in: float | None = None
    alpha_out: float | None = None
    tao_in: float | None = None
    fetched_at: datetime
    raw: dict | None = None


class ChainStatus(BaseModel):
    rpc_url: str
    network: str
    block: int | None = None
    reachable: bool
    error: str | None = None


__all__ = ["ChainStatus", "SubnetInfo"]
