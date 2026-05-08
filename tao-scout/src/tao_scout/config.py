"""Application settings.

``read_only`` is hard-coded ``True`` and frozen. There is intentionally no env
override. If you need a build that writes to chain, this is the wrong project.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

NetworkLiteral = Literal["finney", "test", "local", "archive"]


class Settings(BaseSettings):
    """Frozen application settings.

    Notes
    -----
    The model is ``frozen=True`` so that ``settings.read_only = False`` raises
    a ``ValidationError`` rather than silently mutating the singleton.
    """

    model_config = SettingsConfigDict(
        env_prefix="TAO_SCOUT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # Hard invariant. There is no env var, no flag, no override.
    read_only: bool = Field(default=True, frozen=True)

    db_path: Path = Field(default=Path("./data/tao_scout.db"))
    rpc_url: str = Field(default="wss://entrypoint-finney.opentensor.ai:443")
    network: NetworkLiteral = Field(default="finney")
    cache_ttl_seconds: int = Field(default=300, ge=1)
    log_level: str = Field(default="INFO")
    port: int = Field(default=8765, ge=1, le=65535)
    rpc_timeout_seconds: float = Field(default=15.0, ge=1.0)

    @field_validator("read_only")
    @classmethod
    def _read_only_must_be_true(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("read_only is hard-coded True; do not override")
        return True

    @property
    def db_url(self) -> str:
        path = self.db_path.resolve()
        return f"sqlite+aiosqlite:///{path}"

    @property
    def db_url_sync(self) -> str:
        path = self.db_path.resolve()
        return f"sqlite:///{path}"


_cached: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings`."""
    global _cached
    if _cached is None:
        _cached = Settings()
    return _cached


def reset_settings_cache() -> None:
    """Test helper: clear the cached settings instance."""
    global _cached
    _cached = None


__all__ = ["NetworkLiteral", "Settings", "get_settings", "reset_settings_cache"]
