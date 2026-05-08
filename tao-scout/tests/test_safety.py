"""Read-only invariants. These tests are the foundation of the project.

They MUST pass before any other test runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tao_scout.safety import (
    FORBIDDEN_SDK_METHODS,
    ReadOnlyViolationError,
    assert_read_only_call,
    find_forbidden_wallet_imports,
    warn_if_wallet_env_present,
)


@pytest.mark.parametrize("name", sorted(FORBIDDEN_SDK_METHODS))
def test_every_forbidden_method_raises(name: str) -> None:
    with pytest.raises(ReadOnlyViolationError):
        assert_read_only_call(name)


def test_safe_method_passes() -> None:
    # A few representative read-only names that should always be allowed.
    for ok in ["get_subnet_info", "get_all_subnets_info", "get_current_block"]:
        assert_read_only_call(ok)  # no raise


def test_non_string_input_is_rejected() -> None:
    with pytest.raises(ReadOnlyViolationError):
        assert_read_only_call(123)  # type: ignore[arg-type]


def test_no_wallet_imports_in_src(project_root: str) -> None:
    src_root = Path(project_root) / "src"
    findings = find_forbidden_wallet_imports(src_root)
    assert findings == [], f"forbidden wallet imports leaked into src/: {findings}"


def test_warn_if_wallet_env_present_detects_known_vars() -> None:
    fake_env = {"BT_WALLET_PATH": "/tmp/fake", "PATH": "/usr/bin"}
    hits = warn_if_wallet_env_present(fake_env)
    assert "BT_WALLET_PATH" in hits


def test_warn_if_wallet_env_present_clean() -> None:
    hits = warn_if_wallet_env_present({"PATH": "/usr/bin"})
    assert hits == []


def test_ast_scan_detects_bare_import(tmp_path: Path) -> None:
    f = tmp_path / "evil1.py"
    f.write_text("import bittensor.wallet\n", encoding="utf-8")
    hits = find_forbidden_wallet_imports(tmp_path)
    assert hits and hits[0][2] == "bittensor.wallet"


def test_ast_scan_detects_dotted_submodule_import(tmp_path: Path) -> None:
    f = tmp_path / "evil2.py"
    f.write_text("import bittensor.wallet.coldkey\n", encoding="utf-8")
    hits = find_forbidden_wallet_imports(tmp_path)
    assert hits


def test_ast_scan_detects_bittensor_wallet_pkg(tmp_path: Path) -> None:
    (tmp_path / "evil3.py").write_text(
        "import bittensor_wallet\n", encoding="utf-8"
    )
    (tmp_path / "evil4.py").write_text(
        "from bittensor_wallet.something import x\n", encoding="utf-8"
    )
    hits = find_forbidden_wallet_imports(tmp_path)
    names = {n for _, _, n in hits}
    assert "bittensor_wallet" in names


def test_ast_scan_detects_from_bittensor_import_keypair(tmp_path: Path) -> None:
    (tmp_path / "evil5.py").write_text(
        "from bittensor import Keypair, AsyncSubtensor\n", encoding="utf-8"
    )
    hits = find_forbidden_wallet_imports(tmp_path)
    names = {n for _, _, n in hits}
    assert "bittensor.Keypair" in names


def test_ast_scan_detects_from_bittensor_import_wallet(tmp_path: Path) -> None:
    (tmp_path / "evil6.py").write_text(
        "from bittensor import wallet\n", encoding="utf-8"
    )
    hits = find_forbidden_wallet_imports(tmp_path)
    names = {n for _, _, n in hits}
    assert "bittensor.wallet" in names


def test_ast_scan_detects_from_bittensor_wallet_module(tmp_path: Path) -> None:
    (tmp_path / "evil7.py").write_text(
        "from bittensor.wallet import Wallet\n", encoding="utf-8"
    )
    hits = find_forbidden_wallet_imports(tmp_path)
    names = {n for _, _, n in hits}
    assert "bittensor.wallet" in names


def test_ast_scan_skips_unparseable_files(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text(
        "this is not valid python !!!@@@\n", encoding="utf-8"
    )
    hits = find_forbidden_wallet_imports(tmp_path)
    assert hits == []


def test_ast_scan_ignores_clean_imports(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text(
        "import bittensor\nfrom bittensor import AsyncSubtensor\n",
        encoding="utf-8",
    )
    hits = find_forbidden_wallet_imports(tmp_path)
    assert hits == []


def test_settings_read_only_cannot_be_overridden(monkeypatch) -> None:
    """Even if someone tries to flip read_only via env, validators reject it."""
    from pydantic import ValidationError

    monkeypatch.setenv("TAO_SCOUT_READ_ONLY", "false")
    from tao_scout.config import Settings

    with pytest.raises(ValidationError):
        Settings()


def test_settings_default_is_read_only() -> None:
    from tao_scout.config import Settings

    s = Settings()
    assert s.read_only is True


def test_settings_explicit_false_kwarg_is_rejected() -> None:
    """Passing read_only=False to the model directly must also fail."""
    from pydantic import ValidationError

    from tao_scout.config import Settings

    with pytest.raises(ValidationError):
        Settings(read_only=False)


def test_settings_frozen_blocks_reassignment() -> None:
    """Once constructed, settings.read_only cannot be flipped."""
    from pydantic import ValidationError

    from tao_scout.config import Settings

    s = Settings()
    with pytest.raises(ValidationError):
        s.read_only = False  # type: ignore[misc]


def test_deny_list_covers_known_dangerous_methods() -> None:
    """Belt-and-suspenders: a few names we always expect to be denied."""
    must_deny = {
        "set_weights", "set_root_weights", "commit_weights",
        "commit_reveal_weights", "register", "burned_register",
        "pow_register", "transfer", "transfer_stake",
        "add_stake", "remove_stake", "swap_hotkey",
        "submit_extrinsic", "compose_call",
    }
    assert must_deny.issubset(FORBIDDEN_SDK_METHODS)
