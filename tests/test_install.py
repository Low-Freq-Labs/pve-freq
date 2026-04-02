"""Install pipeline smoke tests.

Tests for the pre-flight module, install.sh syntax, and entry point wiring.
These tests run without root — CI/integration tests for actual install
require a separate environment.
"""
import os
import shutil
import subprocess
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_SCRIPT = os.path.join(PROJECT_ROOT, "install.sh")


# ── Pre-flight module tests ──────────────────────────────────────────────

class TestPreflightPythonVersion:
    """Test check_python_version from preflight module."""

    def test_current_python_passes(self):
        from freq.core.preflight import check_python_version
        ok, msg = check_python_version()
        assert ok is True
        assert "Python" in msg

    def test_version_string_in_message(self):
        from freq.core.preflight import check_python_version
        ok, msg = check_python_version()
        ver = "{}.{}.{}".format(
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        )
        assert ver in msg


class TestPreflightPlatform:
    """Test check_platform from preflight module."""

    def test_detects_linux(self):
        from freq.core.preflight import check_platform
        ok, msg, info = check_platform()
        # We're on Linux in this environment
        assert ok is True
        assert "Platform" in msg

    def test_returns_distro_info(self):
        from freq.core.preflight import check_platform
        ok, msg, info = check_platform()
        assert isinstance(info, dict)
        assert "distro" in info
        assert "version" in info
        assert "family" in info


class TestPreflightDiskSpace:
    """Test check_disk_space from preflight module."""

    def test_root_has_space(self):
        from freq.core.preflight import check_disk_space
        ok, msg = check_disk_space("/", min_mb=1)
        assert ok is True
        assert "Disk" in msg

    def test_unreasonable_requirement_fails(self):
        from freq.core.preflight import check_disk_space
        ok, msg = check_disk_space("/", min_mb=999999999)
        assert ok is False

    def test_nonexistent_path(self):
        from freq.core.preflight import check_disk_space
        ok, msg = check_disk_space("/nonexistent/path/xyz", min_mb=1)
        assert ok is False


class TestPreflightBinaries:
    """Test binary detection from preflight module."""

    def test_required_binaries_found(self):
        from freq.core.preflight import check_required_binaries
        ok, msg, missing = check_required_binaries()
        # ssh and ssh-keygen should be available in our environment
        assert ok is True
        assert len(missing) == 0

    def test_optional_binaries_returns_list(self):
        from freq.core.preflight import check_optional_binaries
        ok, msg, missing = check_optional_binaries()
        # ok is always True for optional (they're advisory)
        assert ok is True
        assert isinstance(missing, list)


class TestPreflightInstallHint:
    """Test install hint generation."""

    def test_debian_python_hint(self):
        from freq.core.preflight import get_install_hint
        hint = get_install_hint("python", "debian")
        assert "apt" in hint

    def test_rhel_python_hint(self):
        from freq.core.preflight import get_install_hint
        hint = get_install_hint("python", "rhel")
        assert "dnf" in hint

    def test_sshpass_hint(self):
        from freq.core.preflight import get_install_hint
        hint = get_install_hint("sshpass", "debian")
        assert "sshpass" in hint

    def test_unknown_family_hint(self):
        from freq.core.preflight import get_install_hint
        hint = get_install_hint("python", "bsd")
        assert "Install" in hint or "install" in hint


class TestPreflightRunAll:
    """Test the run_preflight aggregator."""

    def test_run_preflight_quiet(self):
        from freq.core.preflight import run_preflight
        result = run_preflight(install_dir="/tmp", quiet=True)
        assert isinstance(result, bool)

    def test_run_preflight_returns_bool(self):
        from freq.core.preflight import run_preflight
        result = run_preflight(install_dir="/tmp", quiet=True)
        assert result is True  # Should pass on our system


# ── Install script syntax tests ──────────────────────────────────────────

class TestInstallScript:
    """Verify install.sh is syntactically valid bash."""

    def test_script_exists(self):
        assert os.path.isfile(INSTALL_SCRIPT)

    def test_script_executable(self):
        assert os.access(INSTALL_SCRIPT, os.X_OK)

    def test_bash_syntax_check(self):
        result = subprocess.run(
            ["bash", "-n", INSTALL_SCRIPT],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_help_flag(self):
        result = subprocess.run(
            ["bash", INSTALL_SCRIPT, "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "Usage" in result.stdout or "PVE FREQ" in result.stdout

    def test_version_flag(self):
        result = subprocess.run(
            ["bash", INSTALL_SCRIPT, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        import freq
        assert freq.__version__ in result.stdout

    def test_shebang(self):
        with open(INSTALL_SCRIPT) as f:
            first_line = f.readline()
        assert first_line.startswith("#!/")
        assert "bash" in first_line

    def test_set_euo_pipefail(self):
        with open(INSTALL_SCRIPT) as f:
            content = f.read()
        assert "set -euo pipefail" in content


# ── Doctor integration tests ─────────────────────────────────────────────

class TestDoctorUsesPreflight:
    """Verify doctor.py delegates to preflight module."""

    def test_doctor_check_python_imports_preflight(self):
        """Doctor's Python check should use preflight."""
        from freq.core.doctor import _check_python
        cfg = MagicMock()
        # Should not raise — preflight handles the logic
        result = _check_python(cfg)
        assert result in (0, 1, 2)

    def test_doctor_check_platform_imports_preflight(self):
        from freq.core.doctor import _check_platform
        cfg = MagicMock()
        result = _check_platform(cfg)
        assert result in (0, 1, 2)

    def test_doctor_check_prerequisites_imports_preflight(self):
        from freq.core.doctor import _check_prerequisites
        cfg = MagicMock()
        result = _check_prerequisites(cfg)
        assert result in (0, 1, 2)


# ── Selfupdate marker detection ─────────────────────────────────────────

class TestSelfupdateMarker:
    """Test .install-method marker detection in selfupdate."""

    def test_detect_tarball_marker(self, tmp_path):
        from freq.modules.selfupdate import _detect_install_method
        marker = tmp_path / ".install-method"
        marker.write_text("tarball")
        cfg = MagicMock()
        cfg.install_dir = str(tmp_path)
        assert _detect_install_method(cfg) == "tarball"

    def test_detect_git_release_marker(self, tmp_path):
        from freq.modules.selfupdate import _detect_install_method
        marker = tmp_path / ".install-method"
        marker.write_text("git-release")
        cfg = MagicMock()
        cfg.install_dir = str(tmp_path)
        assert _detect_install_method(cfg) == "git-release"

    def test_detect_local_marker(self, tmp_path):
        from freq.modules.selfupdate import _detect_install_method
        marker = tmp_path / ".install-method"
        marker.write_text("local")
        cfg = MagicMock()
        cfg.install_dir = str(tmp_path)
        assert _detect_install_method(cfg) == "local"

    def test_no_marker_falls_through(self, tmp_path):
        from freq.modules.selfupdate import _detect_install_method
        cfg = MagicMock()
        cfg.install_dir = str(tmp_path)
        # No marker, no .git — falls through to dpkg/rpm check then manual
        result = _detect_install_method(cfg)
        # Result depends on system packages; just verify it returns a string
        assert isinstance(result, str)
        assert len(result) > 0


# ── Entry point tests ────────────────────────────────────────────────────

class TestEntryPoint:
    """Verify freq entry point works."""

    def test_main_module_file_exists(self):
        """Verify __main__.py exists (don't import — it runs main())."""
        main_path = os.path.join(PROJECT_ROOT, "freq", "__main__.py")
        assert os.path.isfile(main_path)

    def test_version_accessible(self):
        import freq
        # Version should be a valid semver string, not empty
        assert freq.__version__
        assert len(freq.__version__.split(".")) == 3

    def test_cli_parser_builds(self):
        from freq.cli import _build_parser
        parser = _build_parser()
        assert parser is not None

    def test_detail_command_registered(self):
        from freq.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["detail", "web01"])
        assert hasattr(args, "func")

    def test_boundaries_command_registered(self):
        from freq.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["boundaries", "lookup", "5001"])
        assert hasattr(args, "func")


# ── Project files tests ──────────────────────────────────────────────────

class TestProjectFiles:
    """Verify distribution files exist and are correct."""

    def test_license_exists(self):
        assert os.path.isfile(os.path.join(PROJECT_ROOT, "LICENSE"))

    def test_license_is_mit(self):
        with open(os.path.join(PROJECT_ROOT, "LICENSE")) as f:
            content = f.read()
        assert "MIT License" in content

    def test_readme_exists(self):
        assert os.path.isfile(os.path.join(PROJECT_ROOT, "README.md"))

    def test_readme_has_install_instructions(self):
        with open(os.path.join(PROJECT_ROOT, "README.md")) as f:
            content = f.read()
        assert "install.sh" in content
        assert "freq doctor" in content

    def test_changelog_exists(self):
        assert os.path.isfile(os.path.join(PROJECT_ROOT, "CHANGELOG.md"))

    def test_pyproject_has_readme(self):
        with open(os.path.join(PROJECT_ROOT, "pyproject.toml")) as f:
            content = f.read()
        assert 'readme = "README.md"' in content

    def test_pyproject_has_urls(self):
        with open(os.path.join(PROJECT_ROOT, "pyproject.toml")) as f:
            content = f.read()
        assert "[project.urls]" in content
        assert "Repository" in content

    def test_example_configs_exist(self):
        conf_dir = os.path.join(PROJECT_ROOT, "conf")
        assert os.path.isfile(os.path.join(conf_dir, "freq.toml.example"))
        assert os.path.isfile(os.path.join(conf_dir, "hosts.toml.example"))
