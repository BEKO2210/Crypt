"""Typer CLI mirroring the web UI surface.

Every command shares the service layer with the HTTP routes; if you discover a
behavioural difference, that is a bug.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import typer

from tao_scout import services
from tao_scout.config import get_settings
from tao_scout.db.session import get_session_factory, reset_engine
from tao_scout.scoring.axes import AXES

app = typer.Typer(help="TAO-Scout: read-only Bittensor subnet intelligence.")
note_app = typer.Typer(help="Note operations.")
app.add_typer(note_app, name="note")


def _interactive_note(netuid: int, existing) -> services.NoteIn:
    task_type = typer.prompt(
        "task type",
        default=(existing.task_type if existing else "") or "",
        show_default=bool(existing),
    )
    repo_url = typer.prompt(
        "repo url",
        default=(existing.repo_url if existing else "") or "",
        show_default=bool(existing),
    )
    hardware_required = typer.prompt(
        "hardware required",
        default=(existing.hardware_required if existing else "unknown") or "unknown",
    )
    entry_difficulty = typer.prompt(
        "entry difficulty",
        default=(existing.entry_difficulty if existing else "unknown") or "unknown",
    )
    risk_notes = typer.prompt(
        "risk notes",
        default=(existing.risk_notes if existing else "") or "",
        show_default=False,
    )
    opportunity_notes = typer.prompt(
        "opportunity notes",
        default=(existing.opportunity_notes if existing else "") or "",
        show_default=False,
    )
    tags_csv = typer.prompt(
        "tags (csv)",
        default=", ".join(existing.tags) if existing and existing.tags else "",
        show_default=False,
    )
    return services.NoteIn(
        netuid=netuid,
        task_type=task_type or None,
        repo_url=repo_url or None,
        hardware_required=hardware_required or None,
        entry_difficulty=entry_difficulty or None,
        risk_notes=risk_notes or None,
        opportunity_notes=opportunity_notes or None,
        tags=[t.strip() for t in tags_csv.split(",") if t.strip()],
    )


@note_app.command("add")
def note_add(netuid: int) -> None:
    """Add or replace the note for a subnet."""

    async def _impl() -> None:
        async with get_session_factory()() as s:
            existing = await services.get_note(s, netuid)
            payload = _interactive_note(netuid, existing)
            note = await services.upsert_note(s, payload)
            typer.echo(f"saved note id={note.id}")
        await reset_engine()

    _run(_impl())


@note_app.command("edit")
def note_edit(netuid: int) -> None:
    """Edit the note for a subnet (defaults populate from current values)."""
    note_add(netuid)


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- list


@app.command("list")
def list_cmd() -> None:
    """List cached subnets in a compact table."""

    async def _impl() -> None:
        async with get_session_factory()() as s:
            cached = await services.get_cached_subnets(s)
            if not cached:
                typer.echo("(cache empty — run `tao-scout refresh`)")
                return
            typer.echo(
                f"{'netuid':>6}  {'name':<24}  {'emission':>10}  {'burn':>8}  "
                f"{'miners/max':>11}  {'cached':<19}  stale"
            )
            for c in cached:
                em = (
                    f"{c.info.emission:.6f}"
                    if c.info.emission is not None
                    else "—"
                )
                burn = (
                    f"{c.info.burn_cost_tao:.4f}"
                    if c.info.burn_cost_tao is not None
                    else "—"
                )
                miners = c.info.n_miners if c.info.n_miners is not None else "?"
                max_n = c.info.max_n if c.info.max_n is not None else "?"
                typer.echo(
                    f"{c.info.netuid:>6}  {(c.info.name or ''):<24}  {em:>10}  "
                    f"{burn:>8}  {str(miners) + '/' + str(max_n):>11}  "
                    f"{c.cached_at.strftime('%Y-%m-%d %H:%M'):<19}  "
                    f"{'YES' if c.is_stale else ''}"
                )
        await reset_engine()

    _run(_impl())


# --------------------------------------------------------------------------- show


@app.command("show")
def show_cmd(netuid: int) -> None:
    """Show details for a cached subnet."""

    async def _impl() -> None:
        async with get_session_factory()() as s:
            cached = await services.get_cached_subnet(s, netuid)
            if cached is None:
                typer.echo(f"subnet {netuid} not in cache; run `tao-scout refresh`")
                raise typer.Exit(code=1)
            note = await services.get_note(s, netuid)
            scores = await services.list_scores(s, netuid)
            payload = {
                "netuid": netuid,
                "cached_at": cached.cached_at.isoformat(),
                "is_stale": cached.is_stale,
                "info": cached.info.model_dump(exclude={"raw"}),
                "note": (
                    {
                        "task_type": note.task_type,
                        "repo_url": note.repo_url,
                        "hardware_required": note.hardware_required,
                        "tags": note.tags,
                    }
                    if note
                    else None
                ),
                "latest_score": (
                    {
                        "weighted_total": scores[0].weighted_total,
                        "created_at": scores[0].created_at.isoformat(),
                    }
                    if scores
                    else None
                ),
            }
            typer.echo(json.dumps(payload, indent=2, default=str))
        await reset_engine()

    _run(_impl())


# --------------------------------------------------------------------------- refresh


@app.command("refresh")
def refresh_cmd(
    netuid: int | None = typer.Option(None, "--netuid", "-n"),
    all_: bool = typer.Option(False, "--all", help="Refresh every subnet"),
) -> None:
    """Pull subnet info from chain into the cache."""

    async def _impl() -> None:
        async with get_session_factory()() as s:
            if netuid is not None and not all_:
                report = await services.refresh_one(s, netuid)
            else:
                report = await services.refresh_all(s)
            typer.echo(
                json.dumps(
                    {
                        "refreshed": report.refreshed,
                        "failed": report.failed,
                        "error": report.error,
                        "used_cache": report.used_cache,
                    },
                    indent=2,
                )
            )
        await reset_engine()

    _run(_impl())


# --------------------------------------------------------------------------- score


@app.command("score")
def score_cmd(netuid: int) -> None:
    """Interactive scoring (six 0-10 inputs, then optional rationale)."""

    async def _impl() -> None:
        async with get_session_factory()() as s:
            cached = await services.get_cached_subnet(s, netuid)
            if cached is None:
                typer.echo(f"subnet {netuid} not in cache; refresh first")
                raise typer.Exit(code=1)
            answers: dict[str, int] = {}
            for axis in AXES:
                hint = "(INVERTED)" if axis.inverted else ""
                v = typer.prompt(
                    f"{axis.label} {hint} [0-10]", type=int, default=5
                )
                answers[axis.key] = v
            rationale = typer.prompt(
                "rationale (blank = auto)", default="", show_default=False
            )
            score = await services.append_score(
                s,
                services.ScoreIn(
                    netuid=netuid,
                    developer_fit=answers["developer_fit"],
                    hardware_fit=answers["hardware_fit"],
                    competition_level=answers["competition_level"],
                    repo_quality=answers["repo_quality"],
                    reward_potential=answers["reward_potential"],
                    ecosystem_momentum=answers["ecosystem_momentum"],
                    rationale=rationale or None,
                ),
            )
            typer.echo(
                f"saved score id={score.id} weighted_total={score.weighted_total:.2f}"
            )
        await reset_engine()

    _run(_impl())


# --------------------------------------------------------------------------- rank


@app.command("rank")
def rank_cmd(
    by: str = typer.Option("total", "--by", help="total | reward | fit"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    async def _impl() -> None:
        async with get_session_factory()() as s:
            rows = await services.rank(s, by=by, limit=limit)
            typer.echo(f"{'#':>3}  {'netuid':>6}  {'total':>6}  {'name':<24}")
            for i, r in enumerate(rows, 1):
                total = (
                    f"{r.score.weighted_total:.2f}" if r.score else "  —"
                )
                typer.echo(
                    f"{i:>3}  {r.subnet.netuid:>6}  {total:>6}  {(r.subnet.name or ''):<24}"
                )
        await reset_engine()

    _run(_impl())


# --------------------------------------------------------------------------- export / import


@app.command("export")
def export_cmd(
    fmt: str = typer.Option("json", "--format", help="json | csv"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Dump notes + scores to ./data/exports/."""
    if fmt not in {"json", "csv"}:
        typer.echo(f"unknown format: {fmt!r} (expected: json | csv)")
        raise typer.Exit(2)

    async def _impl() -> None:
        from sqlalchemy import select

        from tao_scout.api.routes_export import _serialize_note, _serialize_score
        from tao_scout.db.models import Note, Score

        async with get_session_factory()() as s:
            notes = list((await s.execute(select(Note))).scalars().all())
            scores = list((await s.execute(select(Score))).scalars().all())
        if fmt == "json":
            body = {
                "version": 1,
                "exported_at": datetime.now(UTC).isoformat(),
                "notes": [_serialize_note(n) for n in notes],
                "scores": [_serialize_score(sc) for sc in scores],
            }
            target = out or Path(
                f"./data/exports/tao-scout-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(body, indent=2), encoding="utf-8")
            typer.echo(f"wrote {target}")
        else:
            buf = io.StringIO()
            buf.write("# notes\n")
            note_writer = csv.DictWriter(
                buf,
                fieldnames=[
                    "netuid", "task_type", "repo_url", "repo_quality_notes",
                    "hardware_required", "entry_difficulty", "risk_notes",
                    "opportunity_notes", "tags", "last_reviewed_at",
                ],
            )
            note_writer.writeheader()
            for n in notes:
                d = _serialize_note(n)
                d["tags"] = ";".join(d["tags"])
                note_writer.writerow(d)
            buf.write("\n# scores\n")
            score_writer = csv.DictWriter(
                buf,
                fieldnames=[
                    "netuid", "created_at", "developer_fit", "hardware_fit",
                    "competition_level", "repo_quality", "reward_potential",
                    "ecosystem_momentum", "weighted_total", "weights_snapshot",
                    "rationale",
                ],
            )
            score_writer.writeheader()
            for sc in scores:
                d = _serialize_score(sc)
                d["weights_snapshot"] = json.dumps(d["weights_snapshot"])
                score_writer.writerow(d)
            target = out or Path(
                f"./data/exports/tao-scout-{datetime.now(UTC):%Y%m%d-%H%M%S}.csv"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(buf.getvalue(), encoding="utf-8")
            typer.echo(f"wrote {target}")
        await reset_engine()

    _run(_impl())


@app.command("import")
def import_cmd(file: Path) -> None:
    """Restore notes + scores from a JSON export. Idempotent on notes; appends scores."""

    async def _impl() -> None:
        if not file.exists():
            typer.echo(f"no such file: {file}")
            raise typer.Exit(1)
        data = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            typer.echo("unsupported export version")
            raise typer.Exit(2)
        async with get_session_factory()() as s:
            note_count = 0
            for nd in data.get("notes", []):
                await services.upsert_note(
                    s,
                    services.NoteIn(
                        netuid=int(nd["netuid"]),
                        task_type=nd.get("task_type"),
                        repo_url=nd.get("repo_url"),
                        repo_quality_notes=nd.get("repo_quality_notes"),
                        hardware_required=nd.get("hardware_required"),
                        entry_difficulty=nd.get("entry_difficulty"),
                        risk_notes=nd.get("risk_notes"),
                        opportunity_notes=nd.get("opportunity_notes"),
                        tags=list(nd.get("tags", [])),
                    ),
                )
                note_count += 1
            score_count = 0
            for sd in data.get("scores", []):
                await services.append_score(
                    s,
                    services.ScoreIn(
                        netuid=int(sd["netuid"]),
                        developer_fit=int(sd["developer_fit"]),
                        hardware_fit=int(sd["hardware_fit"]),
                        competition_level=int(sd["competition_level"]),
                        repo_quality=int(sd["repo_quality"]),
                        reward_potential=int(sd["reward_potential"]),
                        ecosystem_momentum=int(sd["ecosystem_momentum"]),
                        rationale=sd.get("rationale"),
                        weights=sd.get("weights_snapshot"),
                    ),
                )
                score_count += 1
            typer.echo(f"imported notes={note_count} scores={score_count}")
        await reset_engine()

    _run(_impl())


# --------------------------------------------------------------------------- snapshot


@app.command("snapshot")
def snapshot_cmd(
    netuid: int | None = typer.Option(None, "--netuid", "-n"),
    all_: bool = typer.Option(False, "--all", help="Snapshot every cached subnet"),
    list_: bool = typer.Option(False, "--list", help="List existing snapshots for --netuid"),
) -> None:
    """Capture a Snapshot row for diffing chain+notes+score over time."""

    async def _impl() -> None:
        async with get_session_factory()() as s:
            if list_:
                if netuid is None:
                    typer.echo("--list requires --netuid")
                    raise typer.Exit(2)
                rows = await services.list_snapshots(s, netuid)
                if not rows:
                    typer.echo("(no snapshots)")
                    return
                for r in rows:
                    typer.echo(
                        f"id={r.id}  netuid={r.netuid}  "
                        f"captured_at={r.captured_at.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                return

            if all_:
                cached = await services.get_cached_subnets(s)
                if not cached:
                    typer.echo("cache empty; run `tao-scout refresh --all` first")
                    raise typer.Exit(1)
                count = 0
                for c in cached:
                    snap = await services.capture_snapshot(s, c.info.netuid)
                    typer.echo(f"snapshot id={snap.id} netuid={snap.netuid}")
                    count += 1
                typer.echo(f"captured {count} snapshot(s)")
                return

            if netuid is None:
                typer.echo("provide --netuid N or --all")
                raise typer.Exit(2)
            try:
                snap = await services.capture_snapshot(s, netuid)
            except LookupError as e:
                typer.echo(str(e))
                raise typer.Exit(1) from e
            typer.echo(
                f"snapshot id={snap.id} netuid={snap.netuid} "
                f"captured_at={snap.captured_at.isoformat()}"
            )
        await reset_engine()

    _run(_impl())


# --------------------------------------------------------------------------- serve


@app.command("serve")
def serve_cmd(port: int = typer.Option(8765, "--port")) -> None:
    """Launch the foreground HTMX web UI."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "tao_scout.main:app",
        host="127.0.0.1",
        port=port,
        log_level=settings.log_level.lower(),
    )


# --------------------------------------------------------------------------- doctor


@app.command("doctor")
def doctor_cmd() -> None:
    """Diagnose the local install."""

    async def _impl() -> None:
        settings = get_settings()
        ok = True

        # 1) read_only invariant
        if settings.read_only:
            typer.echo("[OK] read_only invariant: True")
        else:
            typer.echo("[FAIL] read_only invariant: must be True")
            ok = False

        # 2) DB reachable + migrations applied
        try:
            async with get_session_factory()() as s:
                await services.get_cached_subnets(s)
            typer.echo(f"[OK] db reachable at {settings.db_path}")
        except Exception as e:
            typer.echo(f"[FAIL] db: {e!r} (try `alembic upgrade head`)")
            ok = False

        # 3) bittensor SDK importable
        try:
            import bittensor

            typer.echo(f"[OK] bittensor SDK {getattr(bittensor, '__version__', '?')}")
        except Exception as e:
            typer.echo(f"[WARN] bittensor not importable: {e!r}")

        # 4) RPC ping (best-effort, non-fatal if unreachable)
        try:
            from tao_scout.chain.client import ReadOnlyChainClient

            async with ReadOnlyChainClient() as c:
                status = await c.status()
                if status.reachable:
                    typer.echo(f"[OK] RPC {status.rpc_url} block={status.block}")
                else:
                    typer.echo(f"[WARN] RPC unreachable: {status.error}")
        except Exception as e:
            typer.echo(f"[WARN] RPC probe failed: {e!r}")

        # 5) wallet env vars
        from tao_scout.safety import warn_if_wallet_env_present

        env_hits = warn_if_wallet_env_present()
        if env_hits:
            typer.echo(f"[WARN] wallet env vars present: {env_hits}")
        else:
            typer.echo("[OK] no wallet env vars present")

        # 6) AST scan for forbidden imports
        from tao_scout.safety import find_forbidden_wallet_imports

        src_root = Path(__file__).resolve().parent.parent
        findings = find_forbidden_wallet_imports(src_root)
        if findings:
            typer.echo(f"[FAIL] forbidden wallet imports in src/: {findings}")
            ok = False
        else:
            typer.echo("[OK] no forbidden wallet imports in src/")

        await reset_engine()
        sys.exit(0 if ok else 1)

    _run(_impl())


def main() -> None:  # pragma: no cover - entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
