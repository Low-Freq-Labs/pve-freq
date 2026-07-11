"""Shared test isolation and fail-closed workspace-write guards."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from freq.core.config import FreqConfig


REPO_ROOT = Path(__file__).resolve().parents[1]

def _forbidden_repo_runtime_roots() -> tuple[Path, ...]:
    """Return known MagicMock output plus any top-level tilde artifact."""
    roots = {REPO_ROOT / "MagicMock"}
    roots.update(path for path in REPO_ROOT.glob("~*") if path.is_dir())
    return tuple(sorted(roots))


@pytest.fixture
def isolated_freq_config(tmp_path: Path) -> FreqConfig:
    """Return a real config whose mutable paths all live under ``tmp_path``."""
    cfg = FreqConfig()
    cfg.install_dir = str(tmp_path / "install")
    cfg.conf_dir = str(tmp_path / "conf")
    cfg.data_dir = str(tmp_path / "data")
    cfg.cache_dir = str(tmp_path / "cache")
    cfg.key_dir = str(tmp_path / "keys")
    cfg.credentials_dir = str(tmp_path / "credentials")
    cfg.vault_dir = str(tmp_path / "vault")
    cfg.vault_file = str(tmp_path / "vault" / "vault.enc")
    cfg.ssh_key_path = str(tmp_path / "keys" / "freq_id_ed25519")
    cfg.ssh_rsa_key_path = str(tmp_path / "keys" / "freq_id_rsa")
    for path in (
        cfg.install_dir,
        cfg.conf_dir,
        cfg.data_dir,
        cfg.cache_dir,
        cfg.key_dir,
        cfg.credentials_dir,
        cfg.vault_dir,
    ):
        Path(path).mkdir(parents=True, exist_ok=True)
    return cfg


@pytest.fixture(autouse=True)
def isolate_process_paths_and_reject_repo_pollution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Isolate process-local paths and fail any test that writes known scars.

    Bare ``MagicMock`` config attributes previously stringified into relative
    paths such as ``MagicMock/mock.data_dir`` and ``~freq-ops/.ssh``. Those
    paths are never legitimate test output. The guard removes a leak after
    identifying it so one bad test cannot contaminate every later test.
    """
    process_home = tmp_path / "home"
    process_tmp = tmp_path / "tmp"
    process_home.mkdir()
    process_tmp.mkdir()
    monkeypatch.setenv("HOME", str(process_home))
    monkeypatch.setenv("TMPDIR", str(process_tmp))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setattr(tempfile, "tempdir", str(process_tmp))

    unexpected_existing = [path for path in _forbidden_repo_runtime_roots() if path.exists()]
    if unexpected_existing:
        pytest.fail(
            "test isolation requires a clean pollution baseline; found: "
            + ", ".join(str(path) for path in unexpected_existing)
        )

    yield

    leaked = [path for path in _forbidden_repo_runtime_roots() if path.exists()]
    if not leaked:
        return

    details = []
    for root in leaked:
        files = [str(path.relative_to(REPO_ROOT)) for path in root.rglob("*") if path.is_file()]
        details.extend(files[:10])
        if len(files) > 10:
            details.append(f"{root.relative_to(REPO_ROOT)}: +{len(files) - 10} more files")
        shutil.rmtree(root)
    pytest.fail("test wrote runtime data into the repository: " + ", ".join(details))
