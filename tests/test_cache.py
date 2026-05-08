"""Cache TTL and stale-while-error behaviour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tao_scout.chain.cache import (
    RefreshReport,
    get_cached_subnet,
    get_cached_subnets,
    refresh_all,
)
from tao_scout.chain.client import ChainUnavailableError
from tao_scout.chain.models import SubnetInfo
from tao_scout.db.models import Subnet


class _FakeChainClient:
    def __init__(self, subnets: list[SubnetInfo] | Exception) -> None:
        self._subnets = subnets

    async def list_subnets(self) -> list[SubnetInfo]:
        if isinstance(self._subnets, Exception):
            raise self._subnets
        return list(self._subnets)


@pytest.mark.asyncio
async def test_refresh_all_writes_through(db_session) -> None:
    fetched = datetime.now(UTC)
    payload = [
        SubnetInfo(netuid=1, name="alpha", emission=0.05, n_miners=10, max_n=64,
                    fetched_at=fetched, raw={"k": 1}),
        SubnetInfo(netuid=2, name="beta", emission=0.02, n_miners=5, max_n=64,
                    fetched_at=fetched),
    ]
    client = _FakeChainClient(payload)
    report = await refresh_all(db_session, client=client)  # type: ignore[arg-type]
    assert sorted(report.refreshed) == [1, 2]
    rows = await get_cached_subnets(db_session)
    assert {r.info.netuid for r in rows} == {1, 2}
    one = await get_cached_subnet(db_session, 1)
    assert one is not None and one.info.name == "alpha"


@pytest.mark.asyncio
async def test_refresh_all_falls_back_to_cache_on_error(db_session) -> None:
    # Pre-populate cache.
    db_session.add(
        Subnet(
            netuid=7,
            name="precached",
            emission=0.10,
            last_refreshed_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    await db_session.commit()

    client = _FakeChainClient(ChainUnavailableError("network down"))
    report: RefreshReport = await refresh_all(db_session, client=client)  # type: ignore[arg-type]
    assert report.used_cache is True
    assert report.error is not None

    rows = await get_cached_subnets(db_session)
    assert len(rows) == 1
    assert rows[0].info.netuid == 7


@pytest.mark.asyncio
async def test_stale_flag_set_when_older_than_ttl(db_session, monkeypatch) -> None:
    # Force a small TTL by overriding settings.
    from tao_scout.config import get_settings, reset_settings_cache

    monkeypatch.setenv("TAO_SCOUT_CACHE_TTL_SECONDS", "1")
    reset_settings_cache()
    assert get_settings().cache_ttl_seconds == 1

    db_session.add(
        Subnet(
            netuid=11,
            name="old",
            last_refreshed_at=datetime.now(UTC) - timedelta(seconds=30),
        )
    )
    await db_session.commit()
    cached = await get_cached_subnet(db_session, 11)
    assert cached is not None
    assert cached.is_stale is True

    reset_settings_cache()
