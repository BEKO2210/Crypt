"""Read-only enforcement.

This module is the single source of truth for what TAO-Scout will refuse to do.
Every chain-touching code path MUST funnel through ``assert_read_only_call``
before performing network I/O.

The list is intentionally broad: any method whose name suggests a state change,
key handling, or signing is forbidden, even if a future SDK release renames a
read-only method to one of these strings. Errors at the boundary are cheap;
silent footguns are not.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Iterable
from pathlib import Path

FORBIDDEN_SDK_METHODS: frozenset[str] = frozenset(
    {
        # Stake / balance state changes
        "add_stake",
        "remove_stake",
        "transfer",
        "transfer_stake",
        "swap_stake",
        "move_stake",
        # Registration
        "register",
        "burned_register",
        "root_register",
        "swap_hotkey",
        # Validator weights
        "set_weights",
        "commit_weights",
        "reveal_weights",
        # Serving
        "serve_axon",
        "serve_prometheus",
        # Generic write/sign primitives
        "commit",
        "reveal",
        "sign",
        "sign_message",
        # Wallet / key handling
        "unlock_coldkey",
        "unlock_hotkey",
        "create_wallet",
        "create_new_coldkey",
        "create_new_hotkey",
        "regenerate_coldkey",
        "regenerate_hotkey",
        "new_coldkey",
        "new_hotkey",
    }
)

# Substrings that, if they appear in the source of ``src/``, indicate a
# wallet/keypair was probably imported. The AST scanner uses a stricter check;
# this list documents the intent.
WALLET_FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {"bittensor.wallet", "bittensor.Keypair", "bittensor_wallet"}
)


class ReadOnlyViolationError(RuntimeError):
    """Raised when a forbidden, write-capable SDK method is invoked."""


def assert_read_only_call(method_name: str) -> None:
    """Refuse any forbidden SDK method *before* any network I/O.

    Parameters
    ----------
    method_name:
        The SDK attribute name to be invoked.

    Raises
    ------
    ReadOnlyViolationError
        If ``method_name`` is in :data:`FORBIDDEN_SDK_METHODS`.
    """
    if not isinstance(method_name, str):
        raise ReadOnlyViolationError(
            f"method_name must be a string, got {type(method_name).__name__}"
        )
    if method_name in FORBIDDEN_SDK_METHODS:
        raise ReadOnlyViolationError(
            f"{method_name!r} is forbidden in TAO-Scout: this tool is read-only"
        )


def warn_if_wallet_env_present(env: dict[str, str] | None = None) -> list[str]:
    """Return a list of wallet-related env vars that are present.

    The app logs a warning at startup if any are set; it does not abort,
    because users may legitimately have these set for unrelated tools.
    """
    env = dict(os.environ if env is None else env)
    suspicious = [
        "BT_WALLET_PATH",
        "BT_WALLET_NAME",
        "BT_WALLET_HOTKEY",
        "BT_WALLET_COLDKEY",
        "BITTENSOR_WALLET_PATH",
    ]
    return [k for k in suspicious if env.get(k)]


# ----------------------------------------------------------------------------
# AST-based wallet-import scanner
# ----------------------------------------------------------------------------


def _iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        # The safety module itself contains the forbidden literals as data.
        if path.name == "safety.py":
            continue
        yield path


def _module_is_wallet(name: str) -> bool:
    if name == "bittensor.wallet":
        return True
    if name.startswith("bittensor.wallet."):
        return True
    if name == "bittensor_wallet":
        return True
    if name.startswith("bittensor_wallet."):
        return True
    return False


def find_forbidden_wallet_imports(root: Path) -> list[tuple[Path, int, str]]:
    """Walk ``root`` and return any wallet/Keypair imports found in source.

    Returns a list of ``(file_path, lineno, offending_name)``. Empty list means
    the source tree is clean.
    """
    findings: list[tuple[Path, int, str]] = []
    for file_path in _iter_python_files(root):
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _module_is_wallet(alias.name):
                        findings.append((file_path, node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _module_is_wallet(module):
                    findings.append((file_path, node.lineno, module))
                    continue
                # `from bittensor import wallet` / `Keypair`
                if module == "bittensor":
                    for alias in node.names:
                        if alias.name in {"wallet", "Wallet", "Keypair", "keypair"}:
                            findings.append((file_path, node.lineno, f"bittensor.{alias.name}"))
    return findings


__all__ = [
    "FORBIDDEN_SDK_METHODS",
    "WALLET_FORBIDDEN_IMPORTS",
    "ReadOnlyViolationError",
    "assert_read_only_call",
    "warn_if_wallet_env_present",
    "find_forbidden_wallet_imports",
]
