"""Tests for post-init CLI entrypoint contract on installed VM.

Bug: On strict clean-5005 E2E, post-init CLI sweep hit a hard runtime
break. `sudo python3 -m freq init --check`, `sudo python3 -m freq doctor`,
`sudo python3 -m freq fleet status`, and `sudo python3 -m freq media
status` all failed with:

    /usr/bin/python3: No module named freq

The wrapper at /usr/local/bin/freq worked (it sets PYTHONPATH and
FREQ_DIR inline), but plain `python3 -m freq` didn't, because the
`freq` package was never exposed on the default sys.path of the
system Python.

Root cause: install.sh tried `pip3 install` and `python3 -m pip
install` strategies, but on modern Debian (Python 3.11+) the system
Python is PEP 668 / EXTERNALLY-MANAGED, so pip refuses with
'externally-managed-environment' unless --break-system-packages is
passed. Both strategies silently failed, Strategy C (wrapper only)
ran, and nothing was ever dropped into site-packages to expose the
`freq` package. `python3 -m freq` had no way to find it.

Fix:
1. install.sh always drops a `pve-freq.pth` file into every
   /usr/local/lib/python3.*/dist-packages directory. The file
   contains exactly one line: the install dir (default /opt/pve-freq).
   Python reads .pth files at startup and adds listed paths to
   sys.path — so `import freq` and `python3 -m freq` work globally
   without any pip magic or EXTERNALLY-MANAGED bypass.
2. The wrapper at /usr/local/bin/freq is still created unconditionally
   as the canonical CLI entrypoint — the .pth file is additive.
3. contrib/deploy-test.sh refreshes the same .pth file on every
   runtime sync so VMs installed before this commit also get the
   contract without a full reinstall.
4. We no longer attempt `pip install` at all. It copies files into
   site-packages that go stale the moment INSTALL_DIR is updated,
   which is a live-foot-gun on every redeploy.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestInstallShDropsPthFile(unittest.TestCase):
    """install.sh must drop pve-freq.pth into dist-packages."""

    def setUp(self):
        self.script = (FREQ_ROOT / "install.sh").read_text()

    def test_writes_pth_file_named_pve_freq(self):
        """Must create a file named pve-freq.pth, not an arbitrary name."""
        self.assertIn("pve-freq.pth", self.script)

    def test_pth_file_content_is_install_dir(self):
        """The .pth file content must be ${INSTALL_DIR} so sys.path
        points at the live install root."""
        # Look for `echo "$INSTALL_DIR" > "$site_dir/pve-freq.pth"`
        import re
        match = re.search(
            r'echo\s+"\$INSTALL_DIR"\s*>\s*"\$site_dir/pve-freq\.pth"',
            self.script,
        )
        self.assertIsNotNone(match,
                             "install.sh must write $INSTALL_DIR into pve-freq.pth")

    def test_iterates_dist_packages_dirs(self):
        """Must iterate over /usr/local/lib/python3.*/dist-packages."""
        self.assertIn("/usr/local/lib/python3.*/dist-packages", self.script)

    def test_wrapper_still_unconditional(self):
        """/usr/local/bin/freq wrapper must still be created — the .pth
        is additive, not a replacement."""
        self.assertIn("/usr/local/bin/freq", self.script)
        self.assertIn('FREQ_DIR="${INSTALL_DIR}"', self.script)
        self.assertIn('PYTHONPATH="${INSTALL_DIR}"', self.script)

    def test_no_more_pip_install_strategies(self):
        """install.sh must not attempt pip install of the package.
        pip install copies files into site-packages that go stale on
        every deploy and bombs on PEP 668 systems."""
        # The old Strategy A/B ran pip3 install <INSTALL_DIR>.
        # Make sure that's gone.
        self.assertNotIn("pip3 install --no-deps --root-user-action=ignore -q \"$INSTALL_DIR\"",
                         self.script)
        self.assertNotIn("python3 -m pip install --no-deps --root-user-action=ignore -q \"$INSTALL_DIR\"",
                         self.script)


class TestDeployTestRefreshesPthFile(unittest.TestCase):
    """deploy-test.sh must refresh pve-freq.pth on runtime sync."""

    def setUp(self):
        self.script = (FREQ_ROOT / "contrib" / "deploy-test.sh").read_text()

    def test_writes_pth_file_during_runtime_sync(self):
        """The runtime-sync block must drop pve-freq.pth into each
        site-packages dir so pre-existing VMs get the fix without a
        full reinstall."""
        self.assertIn("pve-freq.pth", self.script)

    def test_pth_points_at_runtime_dir(self):
        """The .pth content must be RUNTIME_DIR, not REMOTE_DIR."""
        # deploy-test.sh has RUNTIME_DIR=/opt/pve-freq and
        # REMOTE_DIR=/tmp/pve-freq-dev; we want RUNTIME_DIR
        self.assertIn("echo '${RUNTIME_DIR}' | sudo tee", self.script)

    def test_pth_refresh_only_when_runtime_exists(self):
        """.pth refresh must be inside the `if [ -d ${RUNTIME_DIR}/freq ]`
        block — if there's no runtime install, there's nothing to expose."""
        runtime_check_idx = self.script.find("if [ -d ${RUNTIME_DIR}/freq ]")
        pth_idx = self.script.find("pve-freq.pth")
        else_idx = self.script.find("No runtime install at")
        self.assertNotEqual(runtime_check_idx, -1)
        self.assertNotEqual(pth_idx, -1)
        self.assertNotEqual(else_idx, -1)
        self.assertLess(runtime_check_idx, pth_idx)
        self.assertLess(pth_idx, else_idx,
                        ".pth refresh must be inside the runtime-exists branch")


class TestBashSyntax(unittest.TestCase):
    """Both install.sh and deploy-test.sh must still parse cleanly."""

    def _bash_n(self, path):
        import subprocess
        r = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, f"bash -n {path} failed: {r.stderr}")

    def test_install_sh_syntax(self):
        self._bash_n(FREQ_ROOT / "install.sh")

    def test_deploy_test_sh_syntax(self):
        self._bash_n(FREQ_ROOT / "contrib" / "deploy-test.sh")


if __name__ == "__main__":
    unittest.main()
