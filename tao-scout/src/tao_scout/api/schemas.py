"""Pydantic schemas for the HTTP API."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from tao_scout.scoring.weights import DEFAULT_WEIGHTS


class SubnetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    netuid: int
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
    last_refreshed_at: datetime
    is_stale: bool = False


class NoteIn(BaseModel):
    task_type: str | None = None
    repo_url: str | None = None
    repo_quality_notes: str | None = None
    hardware_required: str | None = None
    entry_difficulty: str | None = None
    risk_notes: str | None = None
    opportunity_notes: str | None = None
    tags: list[str] = Field(default_factory=list)


class NoteOut(NoteIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    netuid: int
    last_reviewed_at: datetime


class ScoreIn(BaseModel):
    developer_fit: int = Field(ge=0, le=10)
    hardware_fit: int = Field(ge=0, le=10)
    competition_level: int = Field(ge=0, le=10)
    repo_quality: int = Field(ge=0, le=10)
    reward_potential: int = Field(ge=0, le=10)
    ecosystem_momentum: int = Field(ge=0, le=10)
    rationale: str | None = None
    weights: Mapping[str, float] | None = None


class ScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    netuid: int
    created_at: datetime
    developer_fit: int
    hardware_fit: int
    competition_level: int
    repo_quality: int
    reward_potential: int
    ecosystem_momentum: int
    weighted_total: float
    weights_snapshot: Mapping[str, float]
    rationale: str | None = None


class SettingsIn(BaseModel):
    skill_profile: str | None = None
    skill_tags: list[str] | None = None
    hardware_profile: str | None = None
    weights: Mapping[str, float] | None = None
    rpc_url: str | None = None
    cache_ttl_seconds: int | None = None


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    skill_profile: str | None = None
    skill_tags: list[str] = Field(default_factory=list)
    hardware_profile: str | None = None
    weights: Mapping[str, float] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    rpc_url: str | None = None
    cache_ttl_seconds: int | None = None
    updated_at: datetime


class RefreshRequest(BaseModel):
    netuid: int | None = None


class RefreshOut(BaseModel):
    refreshed: list[int]
    failed: list[int]
    error: str | None = None
    used_cache: bool = False


class HealthOut(BaseModel):
    sdk_version: str | None
    rpc_reachable: bool
    rpc_url: str
    network: str
    db_ok: bool
    error: str | None = None
