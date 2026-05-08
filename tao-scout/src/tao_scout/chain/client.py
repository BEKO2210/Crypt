"""Async, read-only Bittensor chain client.

Every SDK call goes through :func:`tao_scout.safety.assert_read_only_call`
*before* any network I/O. The wrapper exposes only methods we have audited as
read-only.

If the bittensor SDK is not installed (e.g. test environments without network
deps), the client raises a clear :class:`ChainUnavailableError` instead of an
opaque ImportError. UI code is expected to catch this and render the cached-
data banner.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, AsyncIterator

from tao_scout.chain.models import ChainStatus, SubnetInfo
from tao_scout.config import get_settings
from tao_scout.safety import assert_read_only_call

logger = logging.getLogger(__name__)


class ChainUnavailableError(RuntimeError):
    """Raised when the chain cannot be reached or the SDK isn't importable."""


# The exact list of SDK attributes this client is allowed to call.
# Adding to this list is a deliberate audit step: every entry must be a
# read-only call. The wrapper enforces this list at runtime in addition to
# the FORBIDDEN_SDK_METHODS deny-list in safety.py.
ALLOWED_SDK_METHODS: frozenset[str] = frozenset(
    {
        "get_current_block",
        "get_subnets",
        "get_all_subnets_info",
        "get_subnet_info",
        "subnet_exists",
        "get_total_subnets",
        "neurons_lite",
        "get_neurons_lite",
        "metagraph",
    }
)


def _ensure_audited(method_name: str) -> None:
    """Both the deny-list check AND the allow-list check must pass."""
    assert_read_only_call(method_name)
    if method_name not in ALLOWED_SDK_METHODS:
        raise PermissionError(
            f"{method_name!r} is not in the audited read-only allow-list; "
            "add it to ALLOWED_SDK_METHODS only after verifying it is read-only."
        )


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        v = getattr(obj, attr, default)
    except Exception:
        return default
    return v


def _to_subnet_info(payload: Any, netuid: int) -> SubnetInfo:
    """Best-effort coercion from an SDK SubnetInfo-like object to ours."""
    fetched_at = datetime.now(UTC)

    # SDK objects vary across versions. Try common attribute names.
    name = _safe_get(payload, "name") or _safe_get(payload, "subnet_name")
    owner = _safe_get(payload, "owner_hotkey") or _safe_get(payload, "owner")
    emission = _safe_get(payload, "emission_value")
    if emission is None:
        emission = _safe_get(payload, "emission")
    tempo = _safe_get(payload, "tempo")
    burn = _safe_get(payload, "burn", _safe_get(payload, "burn_cost"))
    recycle = _safe_get(payload, "recycle")
    n_val = _safe_get(payload, "num_validators", _safe_get(payload, "n_validators"))
    n_min = _safe_get(payload, "num_miners", _safe_get(payload, "n_miners"))
    max_n = _safe_get(payload, "max_n")
    alpha_in = _safe_get(payload, "alpha_in")
    alpha_out = _safe_get(payload, "alpha_out")
    tao_in = _safe_get(payload, "tao_in")

    raw: dict | None
    try:
        if hasattr(payload, "model_dump"):
            raw = payload.model_dump()
        elif hasattr(payload, "__dict__"):
            raw = {
                k: (v if _is_jsonable(v) else repr(v))
                for k, v in vars(payload).items()
                if not k.startswith("_")
            }
        else:
            raw = None
    except Exception:
        raw = None

    return SubnetInfo(
        netuid=int(netuid),
        name=str(name) if name else None,
        owner_hotkey=str(owner) if owner else None,
        emission=_to_float(emission),
        tempo=_to_int(tempo),
        burn_cost_tao=_to_float(burn),
        recycle=_to_float(recycle),
        n_validators=_to_int(n_val),
        n_miners=_to_int(n_min),
        max_n=_to_int(max_n),
        alpha_in=_to_float(alpha_in),
        alpha_out=_to_float(alpha_out),
        tao_in=_to_float(tao_in),
        fetched_at=fetched_at,
        raw=raw,
    )


def _is_jsonable(v: Any) -> bool:
    try:
        json.dumps(v)
        return True
    except Exception:
        return False


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class ReadOnlyChainClient:
    """Audited read-only wrapper around ``bittensor.AsyncSubtensor``."""

    def __init__(self, rpc_url: str | None = None, network: str | None = None) -> None:
        s = get_settings()
        self.rpc_url = rpc_url or s.rpc_url
        self.network = network or s.network
        self.timeout = s.rpc_timeout_seconds
        self._subtensor: Any = None

    async def __aenter__(self) -> "ReadOnlyChainClient":
        await self._connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._close()

    async def _connect(self) -> None:
        try:
            import bittensor  # type: ignore[import-not-found]
        except Exception as e:  # pragma: no cover - SDK-not-present path
            raise ChainUnavailableError(
                f"bittensor SDK not importable: {e!r}"
            ) from e

        AsyncSubtensor = getattr(bittensor, "AsyncSubtensor", None)
        if AsyncSubtensor is None:  # pragma: no cover
            raise ChainUnavailableError(
                "bittensor.AsyncSubtensor is missing; upgrade the SDK."
            )

        try:
            # Prefer explicit network arg; fall back to URL.
            self._subtensor = AsyncSubtensor(network=self.network)
            connect = getattr(self._subtensor, "initialize", None) or getattr(
                self._subtensor, "connect", None
            )
            if connect is not None:
                await asyncio.wait_for(connect(), timeout=self.timeout)
        except asyncio.TimeoutError as e:
            raise ChainUnavailableError(
                f"connect to {self.rpc_url} timed out after {self.timeout}s"
            ) from e
        except Exception as e:
            raise ChainUnavailableError(f"connect to {self.rpc_url} failed: {e!r}") from e

    async def _close(self) -> None:
        if self._subtensor is None:
            return
        close = getattr(self._subtensor, "close", None)
        try:
            if close is not None:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
        except Exception:
            logger.debug("subtensor close raised; ignored", exc_info=True)
        finally:
            self._subtensor = None

    async def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        _ensure_audited(method_name)
        if self._subtensor is None:
            raise ChainUnavailableError("client not connected; use 'async with' context")
        method = getattr(self._subtensor, method_name, None)
        if method is None:
            raise ChainUnavailableError(
                f"SDK has no attribute {method_name!r}; SDK upgrade may have renamed it."
            )
        try:
            result = method(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await asyncio.wait_for(result, timeout=self.timeout)
            return result
        except asyncio.TimeoutError as e:
            raise ChainUnavailableError(
                f"{method_name} timed out after {self.timeout}s"
            ) from e

    # ---------------- public read-only API ----------------

    async def get_block(self) -> int | None:
        try:
            v = await self._call("get_current_block")
            return _to_int(v)
        except ChainUnavailableError:
            raise
        except Exception as e:
            raise ChainUnavailableError(f"get_current_block failed: {e!r}") from e

    async def list_subnets(self) -> list[SubnetInfo]:
        # Try the bulk call first; fall back to per-netuid loop.
        try:
            payload = await self._call("get_all_subnets_info")
        except (ChainUnavailableError, AttributeError):
            payload = None
        except Exception as e:
            raise ChainUnavailableError(f"get_all_subnets_info failed: {e!r}") from e

        if payload:
            out: list[SubnetInfo] = []
            for entry in payload:
                netuid = _safe_get(entry, "netuid", _safe_get(entry, "uid"))
                if netuid is None:
                    continue
                out.append(_to_subnet_info(entry, int(netuid)))
            return out

        # Fallback path: enumerate netuids and fetch each.
        try:
            netuids = await self._call("get_subnets")
        except Exception as e:
            raise ChainUnavailableError(f"get_subnets failed: {e!r}") from e
        out = []
        for netuid in netuids or []:
            info = await self.get_subnet(int(netuid))
            if info is not None:
                out.append(info)
        return out

    async def get_subnet(self, netuid: int) -> SubnetInfo | None:
        try:
            payload = await self._call("get_subnet_info", netuid)
        except ChainUnavailableError:
            raise
        except Exception as e:
            raise ChainUnavailableError(f"get_subnet_info({netuid}) failed: {e!r}") from e
        if payload is None:
            return None
        return _to_subnet_info(payload, netuid)

    async def status(self) -> ChainStatus:
        try:
            block = await self.get_block()
            return ChainStatus(
                rpc_url=self.rpc_url,
                network=self.network,
                block=block,
                reachable=True,
            )
        except Exception as e:
            return ChainStatus(
                rpc_url=self.rpc_url,
                network=self.network,
                reachable=False,
                error=str(e),
            )


@asynccontextmanager
async def open_client(
    rpc_url: str | None = None, network: str | None = None
) -> AsyncIterator[ReadOnlyChainClient]:
    client = ReadOnlyChainClient(rpc_url=rpc_url, network=network)
    async with client:
        yield client


__all__ = [
    "ALLOWED_SDK_METHODS",
    "ChainUnavailableError",
    "ReadOnlyChainClient",
    "open_client",
]
