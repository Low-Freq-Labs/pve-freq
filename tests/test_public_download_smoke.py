"""Public download smoke tests — what a first-time user actually gets.

Proves: the install path, runtime entry points, and first-run promises
work as documented. A user who follows README → install → first run
must see working output, not crashes or misleading messages.
"""
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _freq(*args, timeout=10):
    """Run freq as a user would: python3 -m freq <args>."""
    cmd = [sys.executable, "-m", "freq"] + list(args)
    r = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        cwd=REPO_ROOT,
    )
    return r.returncode, r.stdout, r.stderr


class TestFreqVersion(unittest.TestCase):
    """freq --version must match pyproject and not crash."""

    def test_version_exits_zero(self):
        rc, out, err = _freq("--version")
        self.assertEqual(rc, 0, f"freq --version failed: {err}")

    def test_version_matches_module(self):
        from freq import __version__
        rc, out, _ = _freq("--version")
        self.assertIn(__version__, out,
                      f"--version output '{out.strip()}' missing {__version__}")

    def test_version_matches_pyproject(self):
        """Version in output must match pyproject.toml source."""
        rc, out, _ = _freq("--version")
        # pyproject uses dynamic version from freq.__version__
        with open(os.path.join(REPO_ROOT, "pyproject.toml")) as f:
            toml = f.read()
        if 'dynamic = ["version"]' in toml:
            # Version comes from freq.__version__
            from freq import __version__
            self.assertIn(__version__, out)
        else:
            m = re.search(r'version\s*=\s*"(\d+\.\d+\.\d+)"', toml)
            self.assertIsNotNone(m)
            self.assertIn(m.group(1), out)


class TestFreqHelp(unittest.TestCase):
    """freq --help must show all documented domains."""

    def test_help_exits_zero(self):
        rc, out, err = _freq("--help")
        self.assertEqual(rc, 0, f"freq --help failed: {err}")

    def test_help_shows_critical_commands(self):
        """All critical domains must appear in help output."""
        rc, out, _ = _freq("--help")
        critical = ["vm", "fleet", "host", "docker", "secure",
                    "observe", "state", "auto", "ops", "hw",
                    "store", "dr", "net", "serve", "init", "doctor"]
        missing = [c for c in critical if c not in out]
        self.assertEqual(missing, [],
                         f"Missing from help: {missing}")

    def test_help_shows_brand(self):
        rc, out, _ = _freq("--help")
        self.assertIn("PVE FREQ", out)


class TestFreqDoctor(unittest.TestCase):
    """freq doctor must run without crashing and report key findings."""

    def test_doctor_runs_without_crash(self):
        """Doctor may exit non-zero (warnings) but must not crash."""
        rc, out, err = _freq("doctor", timeout=30)
        self.assertIn(rc, (0, 1), f"freq doctor crashed: {err[:200]}")
        # Must produce diagnostic output, not a traceback
        self.assertNotIn("Traceback", out + err,
                         "freq doctor crashed with traceback")

    def test_doctor_reports_python_version(self):
        rc, out, _ = _freq("doctor", timeout=30)
        self.assertIn("Python", out)

    def test_doctor_reports_ssh_status(self):
        rc, out, _ = _freq("doctor", timeout=30)
        self.assertIn("SSH", out)

    def test_doctor_reports_fleet_count(self):
        rc, out, _ = _freq("doctor", timeout=30)
        self.assertIn("14 hosts", out)


class TestModuleImportable(unittest.TestCase):
    """Core freq modules must import without error."""

    def test_freq_init(self):
        from freq import __version__
        self.assertRegex(__version__, r"\d+\.\d+\.\d+")

    def test_freq_cli(self):
        from freq.cli import main
        self.assertTrue(callable(main))

    def test_freq_config(self):
        from freq.core.config import load_config
        self.assertTrue(callable(load_config))

    def test_freq_ssh(self):
        from freq.core.ssh import run, run_many
        self.assertTrue(callable(run))
        self.assertTrue(callable(run_many))


class TestInstallPromises(unittest.TestCase):
    """README install promises must be truthful."""

    def test_zero_dependencies(self):
        """Install requires no external packages (stdlib only)."""
        with open(os.path.join(REPO_ROOT, "pyproject.toml")) as f:
            toml = f.read()
        # dependencies should be empty list
        m = re.search(r"dependencies\s*=\s*\[(.*?)\]", toml, re.DOTALL)
        self.assertIsNotNone(m)
        deps = m.group(1).strip()
        self.assertEqual(deps, "",
                         f"pyproject.toml has dependencies: {deps}")

    def test_python_311_minimum(self):
        """Minimum Python version must be 3.11."""
        with open(os.path.join(REPO_ROOT, "pyproject.toml")) as f:
            toml = f.read()
        self.assertIn(">=3.11", toml)

    def test_console_script_entry_point(self):
        """pyproject must define 'freq' console script."""
        with open(os.path.join(REPO_ROOT, "pyproject.toml")) as f:
            toml = f.read()
        self.assertIn("freq = ", toml)
        self.assertIn("freq.cli:main", toml)


class TestVersionConsistency(unittest.TestCase):
    """All version surfaces must agree."""

    def _assert_toml_version_matches_module(self, rel_path):
        from freq import __version__
        import tomllib

        with open(os.path.join(REPO_ROOT, rel_path), "rb") as f:
            cfg = tomllib.load(f)
        self.assertEqual(cfg["freq"]["version"], __version__,
                         f"{rel_path} says {cfg['freq']['version']} but "
                         f"__version__ is {__version__}")

    def test_version_flag_matches_module(self):
        """freq --version must show freq.__version__."""
        from freq import __version__
        rc, out, _ = _freq("--version")
        self.assertIn(__version__, out)

    def test_config_version_matches_module(self):
        """The operator config version must match freq.__version__."""
        self._assert_toml_version_matches_module(os.path.join("conf", "freq.toml"))

    def test_example_config_version_matches_module(self):
        """The user-facing example config must match freq.__version__."""
        self._assert_toml_version_matches_module(
            os.path.join("conf", "freq.toml.example")
        )

    def test_runtime_template_version_matches_module(self):
        """The shipped init template must match freq.__version__."""
        self._assert_toml_version_matches_module(
            os.path.join("freq", "data", "conf-templates", "freq.toml.example")
        )

    def test_changelog_latest_matches_module(self):
        """CHANGELOG latest version must match freq.__version__."""
        from freq import __version__
        with open(os.path.join(REPO_ROOT, "CHANGELOG.md")) as f:
            content = f.read()
        match = re.search(r"## \[(\d+\.\d+\.\d+)\]", content)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), __version__)


if __name__ == "__main__":
    unittest.main()
