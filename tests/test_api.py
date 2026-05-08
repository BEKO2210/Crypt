"""HTTP API smoke tests using FastAPI's TestClient.

We patch the ``db_session`` dependency so the routes use the in-memory
fixture session rather than connecting to a real SQLite file.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from tao_scout.api.deps import db_session as deps_db_session
from tao_scout.db.models import Subnet
from tao_scout.main import create_app


@pytest.fixture
def app(db_session):
    a = create_app()

    async def override():
        yield db_session

    a.dependency_overrides[deps_db_session] = override
    return a


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def test_api_index_announces_read_only(client: TestClient) -> None:
    resp = client.get("/api")
    assert resp.status_code == 200
    body = resp.json()
    assert body["read_only"] is True


def test_subnets_empty_initially(client: TestClient) -> None:
    resp = client.get("/api/subnets")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_full_score_flow(app, db_session) -> None:
    # Pre-populate one subnet.
    db_session.add(Subnet(netuid=1, name="alpha", last_refreshed_at=datetime.now(UTC)))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # PUT note
        r = await ac.put(
            "/api/subnets/1/notes",
            json={
                "task_type": "text-gen",
                "repo_url": "https://example.com/x",
                "tags": ["llm"],
            },
        )
        assert r.status_code == 200, r.text

        # POST score
        r = await ac.post(
            "/api/subnets/1/scores",
            json={
                "developer_fit": 8,
                "hardware_fit": 7,
                "competition_level": 5,
                "repo_quality": 6,
                "reward_potential": 8,
                "ecosystem_momentum": 7,
            },
        )
        assert r.status_code == 201, r.text
        score = r.json()
        assert score["weighted_total"] > 0

        # GET history
        r = await ac.get("/api/subnets/1/scores")
        assert r.status_code == 200
        assert len(r.json()) == 1

        # GET rank
        r = await ac.get("/api/rank")
        assert r.status_code == 200
        rows = r.json()
        assert rows and rows[0]["netuid"] == 1


@pytest.mark.asyncio
async def test_rejects_score_for_unknown_subnet(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/subnets/999/scores",
            json={
                "developer_fit": 0,
                "hardware_fit": 0,
                "competition_level": 0,
                "repo_quality": 0,
                "reward_potential": 0,
                "ecosystem_momentum": 0,
            },
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_rejects_invalid_weights(app, db_session) -> None:
    db_session.add(Subnet(netuid=2, last_refreshed_at=datetime.now(UTC)))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/subnets/2/scores",
            json={
                "developer_fit": 5,
                "hardware_fit": 5,
                "competition_level": 5,
                "repo_quality": 5,
                "reward_potential": 5,
                "ecosystem_momentum": 5,
                "weights": {"developer_fit": 0.5},  # missing axes
            },
        )
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_export_import_round_trip(app, db_session) -> None:
    db_session.add(Subnet(netuid=3, name="r", last_refreshed_at=datetime.now(UTC)))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.put(
            "/api/subnets/3/notes",
            json={"task_type": "infra", "tags": []},
        )
        await ac.post(
            "/api/subnets/3/scores",
            json={
                "developer_fit": 4,
                "hardware_fit": 4,
                "competition_level": 4,
                "repo_quality": 4,
                "reward_potential": 4,
                "ecosystem_momentum": 4,
            },
        )

        r = await ac.post("/api/export?format=json")
        assert r.status_code == 200
        body = r.json()
        assert body["version"] == 1
        assert any(n["netuid"] == 3 for n in body["notes"])
        assert any(s["netuid"] == 3 for s in body["scores"])

        # Round-trip import.
        files = {"file": ("export.json", json.dumps(body), "application/json")}
        r = await ac.post("/api/import", files=files)
        assert r.status_code == 200
