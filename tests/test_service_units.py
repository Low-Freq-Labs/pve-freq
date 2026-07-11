"""Executable contract for the canonical host-systemd service renderer."""

from pathlib import Path

import pytest

from freq.core.service_units import dashboard_service_unit


def test_dashboard_unit_contains_complete_host_lifecycle_contract():
    unit = dashboard_service_unit("freq-ops", "/srv/pve freq", freq_bin="/usr/local/bin/freq")

    assert "User=freq-ops" in unit
    assert "Group=freq-ops" in unit
    assert r"WorkingDirectory=/srv/pve\x20freq" in unit
    assert 'Environment="FREQ_DIR=/srv/pve freq"' in unit
    assert 'ExecStart="/usr/local/bin/freq" serve' in unit
    assert "Restart=always" in unit
    assert "RestartSec=10" in unit
    assert "TimeoutStopSec=10" in unit
    assert "KillMode=mixed" in unit
    assert "StandardOutput=journal" in unit
    assert unit.endswith("WantedBy=multi-user.target\n")


@pytest.mark.parametrize("user", ["", "root user", "bad\nuser", "UPPER"])
def test_dashboard_unit_rejects_invalid_service_accounts(user):
    with pytest.raises(ValueError, match="invalid service account"):
        dashboard_service_unit(user, "/opt/pve-freq")


@pytest.mark.parametrize("install_dir", ["", "relative/path", "bad\n/path"])
def test_dashboard_unit_rejects_unsafe_install_paths(install_dir):
    with pytest.raises(ValueError):
        dashboard_service_unit("freq-ops", install_dir)


def test_dashboard_unit_escapes_systemd_quoted_values():
    unit = dashboard_service_unit("freq-ops", '/srv/freq%20"quoted', freq_bin='/usr/local/bin/freq"bin')

    assert r"WorkingDirectory=/srv/freq\x2520\x22quoted" in unit
    assert 'ExecStart="/usr/local/bin/freq\\"bin" serve' in unit


def test_dashboard_unit_rejects_nul_bytes():
    with pytest.raises(ValueError, match="NUL"):
        dashboard_service_unit("freq-ops", "/srv/freq\0bad")


def test_real_consumers_use_renderer_and_contrib_definition_is_absent():
    installer = Path("install.sh").read_text()
    init_source = Path("freq/modules/init_cmd.py").read_text()

    assert "dashboard_service_unit" in installer
    assert "dashboard_service_unit" in init_source
    assert "except (OSError, ValueError)" in init_source
    assert not Path("contrib/freq-serve.service").exists()
    assert "Description=PVE FREQ Dashboard" not in installer
    assert "Description=PVE FREQ Dashboard" not in init_source
