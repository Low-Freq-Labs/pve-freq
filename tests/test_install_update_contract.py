"""Tests for install method detection and update behavior contract.

Bug: cmd_update had real behavior only for 'git' installs. 'git-release'
fell through to "Manual install" even though it has a .git directory.
'tarball' and 'local' showed "Manual install" even though they were
installed by install.sh (not manually).

Contract:
- git, git-release: real update via git pull --ff-only
- dpkg: hint to use apt
- rpm: hint to use dnf
- tarball, local: hint to re-run install.sh (with exact command)
- manual/unknown: generic re-run installer hint

Install methods produced by install.sh:
- local: --from-local source copy
- git-release: git clone from GitHub
- tarball: download + extract from GitHub releases
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.modules import selfupdate
from freq.modules.selfupdate import _detect_install_method, cmd_update


class TestInstallMethodDetection(unittest.TestCase):
    """_detect_install_method must identify all known install types."""

    def _make_install(self, tmpdir, method=None, has_git=False):
        """Create a fake install dir with optional markers."""
        from dataclasses import dataclass

        @dataclass
        class FakeCfg:
            install_dir: str

        if method:
            with open(os.path.join(tmpdir, ".install-method"), "w") as f:
                f.write(method)
        if has_git:
            os.makedirs(os.path.join(tmpdir, ".git"))
        return FakeCfg(install_dir=tmpdir)

    def test_valid_markers_strip_and_short_circuit(self):
        for method in ("local", "git-release", "tarball"):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as d:
                cfg = self._make_install(d, has_git=True)
                with open(os.path.join(d, ".install-method"), "w") as marker:
                    marker.write(f"  {method}\n")
                with patch("freq.core.packages.subprocess.run") as run:
                    self.assertEqual(_detect_install_method(cfg), method)
                run.assert_not_called()

    def test_invalid_and_unreadable_markers_fall_through(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._make_install(d, method="invalid", has_git=True)
            with patch("freq.core.packages.subprocess.run") as run:
                self.assertEqual(_detect_install_method(cfg), "git")
            run.assert_not_called()

        with tempfile.TemporaryDirectory() as d:
            cfg = self._make_install(d, method="local", has_git=True)
            with (
                patch("builtins.open", side_effect=OSError("unreadable")),
                patch("freq.core.packages.subprocess.run") as run,
            ):
                self.assertEqual(_detect_install_method(cfg), "git")
            run.assert_not_called()

    def test_git_directory_short_circuits_packages(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._make_install(d, has_git=True)
            with patch("freq.core.packages.subprocess.run") as run:
                self.assertEqual(_detect_install_method(cfg), "git")
            run.assert_not_called()

    def test_package_manager_precedence(self):
        probe = call(["dpkg", "-s", "pve-freq"], capture_output=True, text=True)
        rpm_probe = call(["rpm", "-q", "pve-freq"], capture_output=True, text=True)
        cases = (
            ([SimpleNamespace(returncode=0)], "dpkg", [probe]),
            ([SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)], "rpm", [probe, rpm_probe]),
        )
        for results, expected, expected_calls in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as d:
                cfg = self._make_install(d)
                with patch("freq.core.packages.subprocess.run", side_effect=results) as run:
                    self.assertEqual(_detect_install_method(cfg), expected)
                self.assertEqual(run.call_args_list, expected_calls)

    def test_missing_managers_and_nonzero_results_reach_manual(self):
        probe = call(["dpkg", "-s", "pve-freq"], capture_output=True, text=True)
        rpm_probe = call(["rpm", "-q", "pve-freq"], capture_output=True, text=True)
        cases = (
            [FileNotFoundError("dpkg"), SimpleNamespace(returncode=1)],
            [SimpleNamespace(returncode=1), FileNotFoundError("rpm")],
            [FileNotFoundError("dpkg"), FileNotFoundError("rpm")],
            [SimpleNamespace(returncode=1), SimpleNamespace(returncode=1)],
        )
        for results in cases:
            with self.subTest(results=results), tempfile.TemporaryDirectory() as d:
                cfg = self._make_install(d)
                with patch("freq.core.packages.subprocess.run", side_effect=results) as run:
                    self.assertEqual(_detect_install_method(cfg), "manual")
                self.assertEqual(run.call_args_list, [probe, rpm_probe])

    def test_unexpected_package_probe_error_propagates(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._make_install(d)
            with patch("freq.core.packages.subprocess.run", side_effect=RuntimeError("probe failed")) as run:
                with self.assertRaisesRegex(RuntimeError, "probe failed"):
                    _detect_install_method(cfg)
            run.assert_called_once_with(
                ["dpkg", "-s", "pve-freq"],
                capture_output=True,
                text=True,
            )


class TestUpdateBehaviorContract(unittest.TestCase):
    """Every install method must have explicit update behavior — no silent fallthrough."""

    @staticmethod
    def _result(returncode=0, stdout="", stderr=""):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    @staticmethod
    def _colors():
        return SimpleNamespace(BOLD="", RESET="", GRAY="", DIM="", YELLOW="", GREEN="")

    @staticmethod
    def _rendered_lines(render):
        return [item.args[0] for item in render.line.call_args_list]

    def _assert_no_update_success(self, render, reload_module):
        self.assertNotIn(
            "Updated successfully",
            [item.args[0] for item in render.step_ok.call_args_list],
        )
        self.assertFalse(
            any("New version:" in line for line in self._rendered_lines(render))
        )
        reload_module.assert_not_called()

    def test_cmd_update_routes_every_method_and_preserves_hints(self):
        cfg = SimpleNamespace(install_dir="/tmp/freq")
        args = SimpleNamespace(yes=True)
        cases = (
            ("git", 17, None),
            ("git-release", 17, None),
            ("dpkg", 0, "Update via apt: sudo apt update && sudo apt upgrade pve-freq"),
            ("rpm", 0, "Update via dnf: sudo dnf update pve-freq"),
            ("tarball", 0, "Installed via tarball. Re-run the installer to update:"),
            ("local", 0, "Installed via local. Re-run the installer to update:"),
            ("manual", 0, "Manual install — no automatic update path available."),
            ("mystery", 0, "Unrecognized install method: mystery"),
        )
        for method, expected_rc, expected_line in cases:
            with (
                self.subTest(method=method),
                patch.object(selfupdate, "_detect_install_method", return_value=method) as detect,
                patch.object(selfupdate, "_update_git", return_value=17) as update,
                patch.object(selfupdate, "fmt") as render,
            ):
                render.C = self._colors()
                rc = cmd_update(cfg, None, args)

            self.assertEqual(rc, expected_rc)
            detect.assert_called_once_with(cfg)
            render.header.assert_called_once_with("Update")
            rendered_lines = self._rendered_lines(render)
            self.assertEqual(
                rendered_lines[:3],
                [
                    f"  Current version:  {selfupdate.freq.__version__}",
                    f"  Install method:   {method}",
                    f"  Install dir:      {cfg.install_dir}",
                ],
            )
            if method in {"git", "git-release"}:
                update.assert_called_once_with(cfg, args)
                render.footer.assert_not_called()
                self.assertEqual(render.blank.call_count, 2)
            else:
                update.assert_not_called()
                render.footer.assert_called_once_with()
                self.assertEqual(render.blank.call_count, 3)
                self.assertTrue(any(expected_line in line for line in rendered_lines))
                if method in {"tarball", "local", "manual"}:
                    self.assertTrue(any("install.sh" in line for line in rendered_lines))

    def test_git_transport_failures_and_no_update_are_fail_closed(self):
        cfg = SimpleNamespace(install_dir="/tmp/freq")
        args = SimpleNamespace(yes=False)
        fetch = call(
            ["git", "-C", cfg.install_dir, "fetch"],
            capture_output=True,
            text=True,
            timeout=selfupdate.UPDATE_FETCH_TIMEOUT,
        )
        status = call(
            ["git", "-C", cfg.install_dir, "status", "-uno", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=selfupdate.UPDATE_CHECK_TIMEOUT,
        )
        log = call(
            ["git", "-C", cfg.install_dir, "log", "HEAD..@{u}", "--oneline"],
            capture_output=True,
            text=True,
            timeout=selfupdate.UPDATE_CHECK_TIMEOUT,
        )
        long_error = "  first\n\t" + ("x" * 180) + "  "
        normalized_status = ("first " + ("x" * 180))[:160]
        cases = (
            (
                "fetch",
                [self._result(1, stderr="offline")],
                1,
                [fetch],
                "step_warn",
                "Cannot reach remote (offline or no remote configured)",
            ),
            (
                "status",
                [self._result(), self._result(2, stderr=long_error)],
                1,
                [fetch, status],
                "step_fail",
                f"Cannot inspect working tree: {normalized_status}",
            ),
            (
                "status-fallback",
                [self._result(), self._result(2, stderr="")],
                1,
                [fetch, status],
                "step_fail",
                "Cannot inspect working tree: git status failed without details",
            ),
            (
                "dirty",
                [self._result(), self._result(stdout=" M local.txt\n")],
                1,
                [fetch, status],
                "step_warn",
                "Working tree has local changes — commit or stash them before updating",
            ),
            (
                "log",
                [self._result(), self._result(), self._result(3, stderr="")],
                1,
                [fetch, status, log],
                "step_fail",
                "Cannot compare with upstream: git log failed without details",
            ),
            (
                "log-detail",
                [self._result(), self._result(), self._result(3, stderr=long_error)],
                1,
                [fetch, status, log],
                "step_fail",
                f"Cannot compare with upstream: {normalized_status}",
            ),
            (
                "empty",
                [self._result(), self._result(), self._result()],
                0,
                [fetch, status, log],
                "step_ok",
                "Already up to date",
            ),
        )
        for name, results, expected_rc, expected_calls, render_method, message in cases:
            with (
                self.subTest(name=name),
                patch.object(selfupdate.subprocess, "run", side_effect=results) as run,
                patch.object(selfupdate, "fmt") as render,
                patch("importlib.reload") as reload_module,
            ):
                render.C = self._colors()
                rc = selfupdate._update_git(cfg, args)

            self.assertEqual(rc, expected_rc)
            self.assertEqual(run.call_args_list, expected_calls)
            getattr(render, render_method).assert_any_call(message)
            render.blank.assert_called_once_with()
            render.footer.assert_called_once_with()
            self._assert_no_update_success(render, reload_module)
            self.assertNotIn(call.step_start("Pulling updates"), render.method_calls)
            if expected_rc == 0:
                render.step_warn.assert_not_called()
                render.step_fail.assert_not_called()

        with (
            patch.object(
                selfupdate.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["git", "fetch"], 30),
            ),
            patch.object(selfupdate, "fmt") as render,
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                selfupdate._update_git(cfg, args)
        render.blank.assert_not_called()
        render.footer.assert_not_called()

    def test_git_confirmation_apply_and_real_remote_update(self):
        cfg = SimpleNamespace(install_dir="/tmp/freq")
        commits = "\n".join(f"{index:07x} commit-{index}" for index in range(1, 7))
        base_results = [self._result(), self._result(), self._result(stdout=commits)]
        fetch = call(
            ["git", "-C", cfg.install_dir, "fetch"],
            capture_output=True,
            text=True,
            timeout=selfupdate.UPDATE_FETCH_TIMEOUT,
        )
        status = call(
            ["git", "-C", cfg.install_dir, "status", "-uno", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=selfupdate.UPDATE_CHECK_TIMEOUT,
        )
        log = call(
            ["git", "-C", cfg.install_dir, "log", "HEAD..@{u}", "--oneline"],
            capture_output=True,
            text=True,
            timeout=selfupdate.UPDATE_CHECK_TIMEOUT,
        )
        pull = call(
            ["git", "-C", cfg.install_dir, "pull", "--ff-only"],
            capture_output=True,
            text=True,
            timeout=selfupdate.UPDATE_APPLY_TIMEOUT,
        )

        success_modes = ((True, None), (False, "y"))
        for yes, answer in success_modes:
            with (
                self.subTest(success=(yes, answer)),
                patch.object(
                    selfupdate.subprocess,
                    "run",
                    side_effect=[*base_results, self._result()],
                ) as run,
                patch.object(selfupdate, "fmt") as render,
                patch("builtins.input", return_value=answer) as prompt,
                patch("importlib.reload") as reload_module,
            ):
                render.C = self._colors()
                rc = selfupdate._update_git(cfg, SimpleNamespace(yes=yes))

            self.assertEqual(rc, 0)
            self.assertEqual(run.call_args_list, [fetch, status, log, pull])
            if yes:
                prompt.assert_not_called()
            else:
                prompt.assert_called_once()
            reload_module.assert_called_once_with(selfupdate.freq)
            render.step_ok.assert_any_call("6 new commit(s) available")
            render.step_ok.assert_any_call("Updated successfully")
            self.assertEqual(
                [item.args[0] for item in render.step_ok.call_args_list].count(
                    "Updated successfully"
                ),
                1,
            )
            rendered_lines = self._rendered_lines(render)
            self.assertEqual(
                rendered_lines.count(f"  New version: {selfupdate.freq.__version__}"),
                1,
            )
            self.assertTrue(any("commit-5" in line for line in rendered_lines))
            self.assertFalse(any("commit-6" in line for line in rendered_lines))
            self.assertTrue(any("... and 1 more" in line for line in rendered_lines))
            render.footer.assert_called_once_with()
            render.step_fail.assert_not_called()
            render.step_warn.assert_not_called()

        for answer in ("n", "yes"):
            with (
                self.subTest(declined=answer),
                patch.object(selfupdate.subprocess, "run", side_effect=base_results) as run,
                patch.object(selfupdate, "fmt") as render,
                patch("builtins.input", return_value=answer),
                patch("importlib.reload") as reload_module,
            ):
                render.C = self._colors()
                rc = selfupdate._update_git(cfg, SimpleNamespace(yes=False))
            self.assertEqual(rc, 0)
            self.assertEqual(run.call_args_list, [fetch, status, log])
            render.footer.assert_called_once_with()
            self._assert_no_update_success(render, reload_module)
            self.assertNotIn(call.step_start("Pulling updates"), render.method_calls)

        for error in (EOFError, KeyboardInterrupt):
            with (
                self.subTest(cancelled=error.__name__),
                patch.object(selfupdate.subprocess, "run", side_effect=base_results) as run,
                patch.object(selfupdate, "fmt") as render,
                patch("builtins.input", side_effect=error),
                patch("builtins.print"),
                patch("importlib.reload") as reload_module,
            ):
                render.C = self._colors()
                rc = selfupdate._update_git(cfg, SimpleNamespace(yes=False))
            self.assertEqual(rc, 1)
            self.assertEqual(run.call_args_list, [fetch, status, log])
            render.step_warn.assert_any_call(
                "Update cancelled — rerun with --yes for non-interactive update"
            )
            render.footer.assert_called_once_with()
            self._assert_no_update_success(render, reload_module)
            self.assertNotIn(call.step_start("Pulling updates"), render.method_calls)

        pull_failures = (
            (" denied\n" + ("z" * 180), ("denied " + ("z" * 180))[:160]),
            ("", "git pull failed without details"),
        )
        for pull_error, expected_pull_detail in pull_failures:
            with (
                self.subTest(pull_failure=expected_pull_detail),
                patch.object(
                    selfupdate.subprocess,
                    "run",
                    side_effect=[*base_results, self._result(1, stderr=pull_error)],
                ) as run,
                patch.object(selfupdate, "fmt") as render,
                patch("importlib.reload") as reload_module,
            ):
                render.C = self._colors()
                rc = selfupdate._update_git(cfg, SimpleNamespace(yes=True))
            self.assertEqual(rc, 1)
            self.assertEqual(run.call_args_list, [fetch, status, log, pull])
            render.step_fail.assert_called_once_with(f"Pull failed: {expected_pull_detail}")
            self._assert_no_update_success(render, reload_module)
            self.assertEqual(render.method_calls[-2:], [call.blank(), call.footer()])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            writer = root / "writer"
            client = root / "client"

            def git(*args, cwd=None):
                return subprocess.run(
                    ["git", *args],
                    cwd=cwd,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            git("init", "--bare", str(remote))
            git("init", str(writer))
            git("config", "user.name", "FREQ Test", cwd=writer)
            git("config", "user.email", "freq-test@example.invalid", cwd=writer)
            (writer / "version.txt").write_text("one\n")
            git("add", "version.txt", cwd=writer)
            git("commit", "-m", "initial", cwd=writer)
            git("branch", "-M", "main", cwd=writer)
            git("remote", "add", "origin", str(remote), cwd=writer)
            git("push", "-u", "origin", "main", cwd=writer)
            git("symbolic-ref", "HEAD", "refs/heads/main", cwd=remote)
            git("clone", str(remote), str(client))
            (writer / "version.txt").write_text("two\n")
            git("add", "version.txt", cwd=writer)
            git("commit", "-m", "remote update", cwd=writer)
            git("push", cwd=writer)

            with (
                patch.object(selfupdate, "fmt") as render,
                patch("importlib.reload") as reload_module,
            ):
                render.C = self._colors()
                rc = selfupdate._update_git(
                    SimpleNamespace(install_dir=str(client)),
                    SimpleNamespace(yes=True),
                )

            self.assertEqual(rc, 0)
            self.assertEqual(
                git("rev-parse", "HEAD", cwd=client).stdout.strip(),
                git("rev-parse", "refs/heads/main", cwd=remote).stdout.strip(),
            )
            render.step_ok.assert_any_call("1 new commit(s) available")
            render.step_ok.assert_any_call("Updated successfully")
            reload_module.assert_called_once_with(selfupdate.freq)


class TestInstallShMarkers(unittest.TestCase):
    """install.sh must write valid markers for each install method."""

    def test_install_modes_write_exact_scoped_markers(self):
        with open(Path(__file__).parent.parent / "install.sh") as f:
            content = f.read()
        case_body = content.split('case "$MODE" in', 1)[1].split("  esac", 1)[0]
        local_branch = case_body.split("    local)", 1)[1].split("      ;;", 1)[0]
        git_branch = case_body.split("    git)", 1)[1].split("      ;;", 1)[0]
        install_branch = case_body.split("    install)", 1)[1].split("      ;;", 1)[0]
        branches = {
            "local": local_branch,
            "git-release": git_branch,
            "tarball": install_branch,
        }
        for marker, branch in branches.items():
            with self.subTest(marker=marker):
                exact_write = f'echo "{marker}" > "$INSTALL_DIR/.install-method"'
                self.assertEqual(content.count(exact_write), 1)
                self.assertEqual(branch.count(exact_write), 1)
                for other_marker, other_branch in branches.items():
                    if other_marker != marker:
                        self.assertNotIn(exact_write, other_branch)


if __name__ == "__main__":
    unittest.main()
