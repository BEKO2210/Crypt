"""Generate README screenshots for TAO-Scout (M4).

Spins up an in-memory app pre-seeded with realistic-looking subnet, note,
and score data, then drives a headless Chromium via Playwright to capture
both desktop and mobile views of every public page.

Usage::

    uv pip install playwright
    .venv/bin/playwright install chromium
    .venv/bin/python scripts/take_screenshots.py

Output goes to ``docs/screenshots/`` and is referenced from ``README.adoc``.

The script is intentionally self-contained: it does not require a populated
SQLite database or a live RPC connection.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force a deterministic config before any tao_scout imports.
os.environ.setdefault("TAO_SCOUT_DB_PATH", "./data/screenshots-tmp.db")
os.environ.setdefault("TAO_SCOUT_NETWORK", "test")
os.environ.setdefault("TAO_SCOUT_LOG_LEVEL", "WARNING")

from tao_scout import services  # noqa: E402
from tao_scout.api.deps import db_session as deps_db_session  # noqa: E402
from tao_scout.db.models import Base, Subnet  # noqa: E402
from tao_scout.main import create_app  # noqa: E402

OUT_DIR = Path("docs/screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = OUT_DIR / ".cache"

# Substring matchers for URLs that should be served from the local cache
# instead of fetched from the CDN. Required for sandboxed / offline runs
# where Chromium cannot reach the CDNs directly. Pre-populate with `curl`
# (see README "Screenshots" section).
CDN_CACHE: list[tuple[str, Path]] = [
    ("cdn.tailwindcss.com", CACHE_DIR / "tailwind.js"),
    ("unpkg.com/htmx.org", CACHE_DIR / "htmx.js"),
    ("unpkg.com/alpinejs", CACHE_DIR / "alpine.js"),
]


def _cache_for(url: str) -> Path | None:
    for needle, path in CDN_CACHE:
        if needle in url and path.exists():
            return path
    return None

DESKTOP = {"width": 1280, "height": 800}
MOBILE = {"width": 390, "height": 844}  # iPhone 14 Pro logical px


SUBNETS: list[dict] = [
    {
        "netuid": 1, "name": "apex", "emission": 0.0742, "tempo": 360,
        "burn_cost_tao": 1.20, "n_validators": 64, "n_miners": 188, "max_n": 256,
        "task_type": "text-gen", "hardware": "single-gpu-24gb",
        "scores": [4.2, 5.1, 6.0, 6.5, 7.1, 7.4],
    },
    {
        "netuid": 5, "name": "vision-net", "emission": 0.0413, "tempo": 360,
        "burn_cost_tao": 0.85, "n_validators": 32, "n_miners": 96, "max_n": 128,
        "task_type": "image-gen", "hardware": "single-gpu-24gb",
        "scores": [3.0, 4.5, 4.8, 5.2],
    },
    {
        "netuid": 11, "name": "audio-fwd", "emission": 0.0089, "tempo": 480,
        "burn_cost_tao": 0.40, "n_validators": 16, "n_miners": 24, "max_n": 64,
        "task_type": "audio", "hardware": "cpu-only",
        "scores": [6.8],
    },
    {
        "netuid": 19, "name": "infra-bench", "emission": 0.0021, "tempo": 720,
        "burn_cost_tao": 0.10, "n_validators": 8, "n_miners": 12, "max_n": 32,
        "task_type": "infra", "hardware": "cpu-only",
        "scores": [],
    },
]


async def seed(factory) -> None:
    async with factory() as s:
        now = datetime.now(UTC)
        for d in SUBNETS:
            s.add(Subnet(
                netuid=d["netuid"],
                name=d["name"],
                emission=d["emission"],
                tempo=d["tempo"],
                burn_cost_tao=d["burn_cost_tao"],
                n_validators=d["n_validators"],
                n_miners=d["n_miners"],
                max_n=d["max_n"],
                last_refreshed_at=now - timedelta(minutes=15),
            ))
        await s.commit()
        for d in SUBNETS:
            await services.upsert_note(
                s,
                services.NoteIn(
                    netuid=d["netuid"],
                    task_type=d["task_type"],
                    hardware_required=d["hardware"],
                    repo_url=f"https://github.com/example/{d['name']}",
                    repo_quality_notes="Active, recent commits, pyproject pinned.",
                    risk_notes="Validator concentration in top 3 hotkeys.",
                    opportunity_notes="Open hardware tier, good docs.",
                    tags=["llm", d["task_type"]],
                ),
            )
            for v in d["scores"]:
                vi = max(0, min(10, int(round(v))))
                await services.append_score(
                    s,
                    services.ScoreIn(
                        netuid=d["netuid"],
                        developer_fit=vi, hardware_fit=vi, competition_level=vi,
                        repo_quality=vi, reward_potential=vi, ecosystem_momentum=vi,
                        rationale=f"Round score {v:.1f} based on stage drafts.",
                    ),
                )


async def build_factory():
    Path("./data").mkdir(exist_ok=True)
    db_path = Path(os.environ["TAO_SCOUT_DB_PATH"])
    db_path.unlink(missing_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.resolve()}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await seed(factory)
    return engine, factory


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_listening(port: int, timeout: float = 10.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.connect(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.1)
    raise RuntimeError(f"server on port {port} did not start within {timeout}s")


def serve_in_thread(app, port: int) -> threading.Thread:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    def run() -> None:
        asyncio.run(server.serve())

    t = threading.Thread(target=run, daemon=True)
    t.start()
    _wait_until_listening(port)
    return t


def shoot(page, url: str, out: Path, viewport: dict) -> None:
    page.set_viewport_size(viewport)
    # `domcontentloaded` (not networkidle) because the Tailwind CDN runtime
    # opens a long-lived MutationObserver that keeps the network busy.
    page.goto(url, wait_until="domcontentloaded")
    # Wait until Tailwind's runtime has actually injected its <style> tag
    # and a known utility class resolves to its expected computed value.
    page.wait_for_function(
        """() => {
            const probe = document.querySelector('.bg-white');
            if (!probe) return true;
            const bg = getComputedStyle(probe).backgroundColor;
            return bg === 'rgb(255, 255, 255)';
        }""",
        timeout=10000,
    )
    page.wait_for_timeout(300)  # let any late layout shift settle
    page.screenshot(path=str(out), full_page=True)
    print(f"  wrote {out} ({viewport['width']}x{viewport['height']})")


def main() -> None:
    from playwright.sync_api import sync_playwright

    engine, factory = asyncio.run(build_factory())

    async def override_session():
        async with factory() as s:
            yield s

    app = create_app()
    app.dependency_overrides[deps_db_session] = override_session

    port = _free_port()
    serve_in_thread(app, port)
    base = f"http://127.0.0.1:{port}"

    targets: list[tuple[str, str]] = [
        ("home", "/"),
        ("home-filtered", "/?task_type=text-gen&min_score=5"),
        ("subnet-detail", "/subnet/1"),
        ("rank", "/rank"),
        ("settings", "/settings"),
    ]

    if not any(p.exists() for _, p in CDN_CACHE):
        print(
            "[warn] CDN cache empty; relying on direct internet access from Chromium. "
            "If your environment blocks outbound requests, run:\n"
            "  mkdir -p docs/screenshots/.cache\n"
            "  curl -sL https://cdn.tailwindcss.com/3.4.17 -o docs/screenshots/.cache/tailwind.js\n"
            "  curl -sL https://unpkg.com/htmx.org@1.9.12 -o docs/screenshots/.cache/htmx.js\n"
            "  curl -sL https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js -o docs/screenshots/.cache/alpine.js"
        )

    def handle_route(route):
        cached = _cache_for(route.request.url)
        if cached is not None:
            route.fulfill(
                status=200,
                content_type="application/javascript",
                body=cached.read_bytes(),
            )
        else:
            route.continue_()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, path in targets:
            print(f"capturing {name} ({path})")
            for label, vp in [("desktop", DESKTOP), ("mobile", MOBILE)]:
                ctx = browser.new_context(viewport=vp, device_scale_factor=2)
                page = ctx.new_page()
                page.route("**/*", handle_route)
                shoot(page, f"{base}{path}", OUT_DIR / f"{name}-{label}.png", vp)
                ctx.close()
        browser.close()

    asyncio.run(engine.dispose())
    Path(os.environ["TAO_SCOUT_DB_PATH"]).unlink(missing_ok=True)
    print(f"\nDone. Screenshots in {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
