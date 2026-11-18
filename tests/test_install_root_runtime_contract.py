"""Owners for the fresh-install systemd 200/CHDIR journey defect."""

import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from freq.core import doctor
from freq.core.install_root import normalize_owned_install_root

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_installer_normalizes_owned_root_after_every_transfer_mode() -> None:
    source = _source("install.sh")
    install = source.split("do_install() {", 1)[1]
    after_transfer = install.split("  esac", 1)[1]
    before_data_setup = after_transfer.split("# Create data directories", 1)[0]

    assert 'chmod 0755 "$INSTALL_DIR"' in before_data_setup


def test_install_root_normalizer_overrides_private_umask_mode() -> None:
    container = Path(tempfile.mkdtemp(prefix="pve-freq-root-", dir="/tmp"))
    try:
        container.chmod(0o755)
        install_root = container / "pve-freq"
        install_root.mkdir(mode=0o700)

        normalize_owned_install_root(str(install_root))

        assert install_root.stat().st_mode & 0o777 == 0o755
    finally:
        shutil.rmtree(container)


def test_install_root_normalizer_rejects_inaccessible_ancestor() -> None:
    container = Path(tempfile.mkdtemp(prefix="pve-freq-parent-", dir="/tmp"))
    try:
        container.chmod(0o700)
        install_root = container / "pve-freq"
        install_root.mkdir(mode=0o700)

        try:
            normalize_owned_install_root(str(install_root))
        except PermissionError as exc:
            assert str(container) in str(exc)
        else:
            raise AssertionError("private install ancestor was accepted")
    finally:
        shutil.rmtree(container)


def test_private_install_root_is_not_a_false_green_for_runtime_account(
    tmp_path: Path, capsys
) -> None:
    install_root = tmp_path / "pve-freq"
    install_root.mkdir()
    install_root.chmod(0o700)
    cfg = SimpleNamespace(
        install_dir=str(install_root),
        ssh_service_account="nobody",
    )

    rc = doctor._check_install_dir(cfg)

    assert rc == 1
    output = capsys.readouterr().out
    assert "nobody" in output
    assert "traverse" in output.lower()


def test_doctor_reports_systemd_chdir_and_restart_count(capsys) -> None:
    result = SimpleNamespace(
        returncode=0,
        stdout=(
            "LoadState=loaded\n"
            "ActiveState=failed\n"
            "Result=exit-code\n"
            "ExecMainCode=exited\n"
            "ExecMainStatus=200\n"
            "NRestarts=637\n"
        ),
        stderr="",
    )
    with patch("freq.core.doctor.subprocess.run", return_value=result):
        rc = doctor._check_dashboard_service(SimpleNamespace())

    assert rc == 1
    output = capsys.readouterr().out
    assert "CHDIR" in output
    assert "637" in output


def test_doctor_keeps_absent_systemd_unit_nonfatal(capsys) -> None:
    result = SimpleNamespace(
        returncode=0,
        stdout=(
            "LoadState=not-found\n"
            "ActiveState=inactive\n"
            "Result=success\n"
            "ExecMainCode=exited\n"
            "ExecMainStatus=0\n"
            "NRestarts=0\n"
        ),
        stderr="",
    )
    with patch("freq.core.doctor.subprocess.run", return_value=result):
        rc = doctor._check_dashboard_service(SimpleNamespace())

    assert rc == 2
    assert "not installed" in capsys.readouterr().out.lower()


def test_init_and_web_handoff_repair_existing_install_root() -> None:
    source = _source("freq/modules/init_cmd.py")
    finalizer = source.split(
        "def _finalize_web_init_runtime_ownership", 1
    )[1].split("\ndef ", 1)[0]
    phase_9m = source.split("# ── 9m: Fix ownership for dashboard", 1)[1].split(
        "\ndef ", 1
    )[0]

    assert "normalize_owned_install_root" in finalizer
    assert "normalize_owned_install_root" in phase_9m


def test_host_managed_operator_docs_use_https_8888() -> None:
    break_glass = _source("docs/BREAK-GLASS.md")
    quick = _source("docs/QUICK-REFERENCE.md")
    api_reference = _source("docs/API-REFERENCE.md")

    for source in (break_glass, quick, api_reference):
        assert "http://localhost:8888" not in source
        assert "https://localhost:8888" in source


def test_doctor_local_scope_includes_dashboard_service_truth() -> None:
    source = _source("freq/core/doctor.py")
    installation = source.split('"Installation"', 1)[1].split(")", 1)[0]

    assert "_check_dashboard_service" in installation
