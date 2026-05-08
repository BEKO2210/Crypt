"""Cache layer between the chain client and the rest of the app.

Chain reads are cached in the SQLite ``subnets`` table. Behaviour:

* If the cached row is fresher than ``cache_ttl_seconds``, return it.
* Otherwise, attempt a live fetch.
* On RPC failure, fall back to cached data and surface a stale flag — never
  silently substitute zeros.

The cache is intentionally simple: persistence in the same DB the user reads
elsewhere, so backups and audits are trivial.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tao_scout.chain.client import ChainUnavailableError, ReadOnlyChainClient, open_client
from tao_scout.chain.models import SubnetInfo
from tao_scout.config import get_settings
from tao_scout.db.models import Subnet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CachedSubnet:
    info: SubnetInfo
    cached_at: datetime
    is_stale: bool


def _row_to_info(row: Subnet) -> SubnetInfo:  # noqa: C901
    fetched = _aware(row.last_refreshed_at) or datetime.now(UTC)
    raw: dict | None = None
    if row.raw_json:
        try:
            raw = json.loads(row.raw_json)
        except json.JSONDecodeError:
            raw = None
    return SubnetInfo(
        netuid=row.netuid,
        name=row.name,
        owner_hotkey=row.owner_hotkey,
        emission=row.emission,
        tempo=row.tempo,
        burn_cost_tao=row.burn_cost_tao,
        recycle=row.recycle,
        n_validators=row.n_validators,
        n_miners=row.n_miners,
        max_n=row.max_n,
        alpha_in=row.alpha_in,
        alpha_out=row.alpha_out,
        tao_in=row.tao_in,
        fetched_at=fetched,
        raw=raw,
    )


def _info_to_row_kwargs(info: SubnetInfo) -> dict:
    raw_json = json.dumps(info.raw, default=str) if info.raw is not None else None
    return {
        "name": info.name,
        "owner_hotkey": info.owner_hotkey,
        "emission": info.emission,
        "tempo": info.tempo,
        "burn_cost_tao": info.burn_cost_tao,
        "recycle": info.recycle,
        "n_validators": info.n_validators,
        "n_miners": info.n_miners,
        "max_n": info.max_n,
        "alpha_in": info.alpha_in,
        "alpha_out": info.alpha_out,
        "tao_in": info.tao_in,
        "last_refreshed_at": info.fetched_at,
        "raw_json": raw_json,
    }


async def _upsert_subnet(session: AsyncSession, info: SubnetInfo) -> Subnet:
    existing = await session.get(Subnet, info.netuid)
    if existing is None:
        existing = Subnet(netuid=info.netuid)
        session.add(existing)
    for k, v in _info_to_row_kwargs(info).items():
        setattr(existing, k, v)
    return existing


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    if d.tzinfo is None:
        return d.replace(tzinfo=UTC)
    return d


def _is_stale(row: Subnet, ttl_seconds: int) -> bool:
    refreshed = _aware(row.last_refreshed_at)
    if refreshed is None:
        return True
    age = datetime.now(UTC) - refreshed
    return age > timedelta(seconds=ttl_seconds)


async def get_cached_subnets(session: AsyncSession) -> list[CachedSubnet]:
    s = get_settings()
    rows: Sequence[Subnet] = (
        (await session.execute(select(Subnet).order_by(Subnet.netuid))).scalars().all()
    )
    return [
        CachedSubnet(
            info=_row_to_info(r),
            cached_at=_aware(r.last_refreshed_at) or datetime.now(UTC),
            is_stale=_is_stale(r, s.cache_ttl_seconds),
        )
        for r in rows
    ]


async def get_cached_subnet(
    session: AsyncSession, netuid: int
) -> CachedSubnet | None:
    s = get_settings()
    row = await session.get(Subnet, netuid)
    if row is None:
        return None
    return CachedSubnet(
        info=_row_to_info(row),
        cached_at=_aware(row.last_refreshed_at) or datetime.now(UTC),
        is_stale=_is_stale(row, s.cache_ttl_seconds),
    )


@dataclass
class RefreshReport:
    refreshed: list[int]
    failed: list[int]
    error: str | None = None
    used_cache: bool = False


async def refresh_all(
    session: AsyncSession,
    *,
    client: ReadOnlyChainClient | None = None,
) -> RefreshReport:
    """Pull every subnet from chain and overwrite the cache."""
    refreshed: list[int] = []
    failed: list[int] = []
    try:
        if client is not None:
            infos = await client.list_subnets()
        else:
            async with open_client() as c:
                infos = await c.list_subnets()
    except ChainUnavailableError as e:
        logger.warning("refresh_all: chain unreachable: %s", e)
        return RefreshReport(refreshed=[], failed=[], error=str(e), used_cache=True)

    for info in infos:
        try:
            await _upsert_subnet(session, info)
            refreshed.append(info.netuid)
        except Exception as e:  # pragma: no cover - DB-level failure
            logger.exception("upsert subnet %s failed", info.netuid)
            failed.append(info.netuid)
            _ = e
    await session.commit()
    return RefreshReport(refreshed=refreshed, failed=failed)


async def refresh_one(
    session: AsyncSession,
    netuid: int,
    *,
    client: ReadOnlyChainClient | None = None,
) -> RefreshReport:
    try:
        if client is not None:
            info = await client.get_subnet(netuid)
        else:
            async with open_client() as c:
                info = await c.get_subnet(netuid)
    except ChainUnavailableError as e:
        return RefreshReport(refreshed=[], failed=[netuid], error=str(e), used_cache=True)
    if info is None:
        return RefreshReport(refreshed=[], failed=[netuid], error="subnet not found")
    await _upsert_subnet(session, info)
    await session.commit()
    return RefreshReport(refreshed=[netuid], failed=[])


async def upsert_many(session: AsyncSession, infos: Iterable[SubnetInfo]) -> int:
    """Insert/overwrite many subnets in one transaction (used by import)."""
    n = 0
    for info in infos:
        await _upsert_subnet(session, info)
        n += 1
    await session.commit()
    return n


__all__ = [
    "CachedSubnet",
    "RefreshReport",
    "get_cached_subnet",
    "get_cached_subnets",
    "refresh_all",
    "refresh_one",
    "upsert_many",
]
