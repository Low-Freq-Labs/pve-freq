"""FREQ init_cmd tests — _run_with_input, _ssh_with_pass, _load_device_credentials.

Tests the stdin-piping helpers for IOS switch config and the per-device
credential loading from TOML files.
"""
import os
import shutil
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.case_matrix import run_case_matrix  # noqa: E402, I001

from freq.modules.init_cmd import _run_with_input, _ssh_with_pass
from freq.modules.init_cmd import _init_dry_run
from freq.modules.init_cmd import (
    _reset_local_init_state,
    _remote_home_probe,
    INIT_LIVE_CONFIG_FILES,
    INIT_GENERATED_TOKEN_FILES,
    INIT_GENERATED_WATCHDOG_FILES,
)
from freq.core.config import FreqConfig, _resolve_paths


class TestInitPhaseVerifyTruthContract(unittest.TestCase):
    """Init verification must not green-light hosts doctor will degrade."""

    def _phase_verify_src(self):
        repo_root = Path(__file__).parent.parent
        with open(repo_root / "freq/modules/init_cmd.py") as f:
            src = f.read()
        return src.split("def _phase_verify", 1)[1].split("\n    # \u2500\u2500 Enhanced checks", 1)[0]

    def test_phase_verify_uses_managed_probe_scope(self):
        with open(Path(__file__).parent.parent / "freq/modules/init_cmd.py") as f:
            src = f.read()
        self.assertIn("from freq.core.host_scope import managed_probe_hosts", src)
        block = self._phase_verify_src()
        self.assertIn("managed_probe_hosts(cfg)", block)

    def test_phase_verify_does_not_skip_managed_hosts_not_deployed_this_run(self):
        block = self._phase_verify_src()
        self.assertNotIn("not deployed this run", block)
        self.assertIn("managed host verification failed", block)
        self.assertIn("managed host not verified", block)


class TestInitFixTruthContract(unittest.TestCase):
    """init --fix must repair VM SSH drift through product-owned fallbacks."""

    def _init_fix_src(self):
        repo_root = Path(__file__).parent.parent
        with open(repo_root / "freq/modules/init_cmd.py") as f:
            src = f.read()
        return src.split("def _init_fix", 1)[1].split("\n\n# \u2550", 1)[0]

    def test_init_fix_has_guest_agent_fallback_for_linux_vms(self):
        block = self._init_fix_src()
        self.assertIn("_populate_fix_vmid_node_map(cfg, ctx)", block)
        self.assertIn("_deploy_via_guest_agent", block)
        self.assertIn("bootstrap repair failed", block)

    def test_scan_fleet_carries_vmid_for_fix(self):
        repo_root = Path(__file__).parent.parent
        with open(repo_root / "freq/modules/init_cmd.py") as f:
            src = f.read()
        scan = src.split("def _scan_fleet", 1)[1].split("\ndef _init_check", 1)[0]
        self.assertIn('"vmid": int(getattr(h, "vmid", 0) or 0)', scan)


# ═══════════════════════════════════════════════════════════════════
# _run_with_input() tests
# ═══════════════════════════════════════════════════════════════════

class TestRunWithInput(unittest.TestCase):
    """Test the stdin-piping subprocess helper."""

    def _case_pipes_stdin_to_command(self):
        """Input text is piped via stdin and echoed back."""
        rc, out, err = _run_with_input(["cat"], "hello from stdin")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "hello from stdin")

    def _case_multiline_input(self):
        """Multi-line input (IOS config style) is piped correctly."""
        config = "conf t\ninterface vlan 10\nip address 10.0.0.1 255.255.255.0\nend\n"
        rc, out, err = _run_with_input(["cat"], config)
        self.assertEqual(rc, 0)
        self.assertIn("conf t", out)
        self.assertIn("interface vlan 10", out)
        self.assertIn("end", out)

    def _case_returns_nonzero_on_failure(self):
        """Non-zero return code propagated from subprocess."""
        rc, out, err = _run_with_input(["false"], "ignored")
        self.assertNotEqual(rc, 0)

    def _case_returns_tuple_of_three(self):
        """Always returns (rc, stdout, stderr) tuple."""
        result = _run_with_input(["echo", "test"], "input")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

    def _case_timeout_returns_error(self):
        """Timeout produces rc=124 and error in stderr."""
        rc, out, err = _run_with_input(["sleep", "10"], "x", timeout=1)
        self.assertEqual(rc, 124)
        self.assertTrue(len(err) > 0)

    def _case_invalid_command_returns_error(self):
        """Non-existent command returns non-zero rc."""
        rc, out, err = _run_with_input(["__nonexistent_binary_xyz__"], "x")
        # rc=1 (Python OSError) or rc=127 (shell "command not found" when
        # wrapped in GNU timeout by _run_bounded).
        self.assertNotEqual(rc, 0)

    def _case_empty_input(self):
        """Empty string input doesn't crash."""
        rc, out, err = _run_with_input(["cat"], "")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "")


RUN_WITH_INPUT_CASES = (
    "_case_pipes_stdin_to_command",
    "_case_multiline_input",
    "_case_returns_nonzero_on_failure",
    "_case_returns_tuple_of_three",
    "_case_timeout_returns_error",
    "_case_invalid_command_returns_error",
    "_case_empty_input",
)


class TestRunWithInputMatrix(unittest.TestCase):
    def test_run_with_input_matrix(self):
        run_case_matrix(self, TestRunWithInput, RUN_WITH_INPUT_CASES)


class TestInitResetLocalState(unittest.TestCase):
    """Reset must produce a true first-run state without destroying templates."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freq-init-reset-")
        self.cfg = FreqConfig()
        self.cfg.install_dir = self.tmp
        _resolve_paths(self.cfg)
        os.makedirs(self.cfg.conf_dir, exist_ok=True)
        os.makedirs(self.cfg.key_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.cfg.vault_file), exist_ok=True)
        os.makedirs(os.path.join(self.cfg.data_dir, "secrets"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, path, body="x"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(body)

    def _case_reset_removes_generated_state_and_live_config_only(self):
        generated = [
            os.path.join(self.cfg.conf_dir, ".initialized"),
            os.path.join(self.cfg.conf_dir, ".web-setup-complete"),
            os.path.join(self.cfg.data_dir, "setup-complete"),
            self.cfg.vault_file,
            os.path.join(self.cfg.key_dir, "freq_id_ed25519"),
            os.path.join(self.cfg.key_dir, "freq_id_ed25519.pub"),
            os.path.join(self.cfg.key_dir, "freq_id_rsa"),
            os.path.join(self.cfg.key_dir, "freq_id_rsa.pub"),
        ]
        for path in generated:
            self._touch(path)

        for name in INIT_LIVE_CONFIG_FILES:
            self._touch(os.path.join(self.cfg.conf_dir, name), "live\n")
            self._touch(os.path.join(self.cfg.conf_dir, f"{name}.example"), "template\n")

        staging_secret = os.path.join(self.cfg.data_dir, "secrets", "truenas-prod.key")
        self._touch(staging_secret, "operator supplied\n")

        with patch("freq.modules.init_cmd.fmt") as _fmt:
            _fmt.step_ok = MagicMock()
            _fmt.step_warn = MagicMock()
            with patch("freq.modules.init_cmd.INIT_GENERATED_TOKEN_FILES", ()):
                _reset_local_init_state(self.cfg, remove_live_config=True)

        for path in generated:
            self.assertFalse(os.path.exists(path), f"generated init state survived reset: {path}")

        for name in INIT_LIVE_CONFIG_FILES:
            self.assertFalse(
                os.path.exists(os.path.join(self.cfg.conf_dir, name)),
                f"live generated config survived reset: {name}",
            )
            self.assertTrue(
                os.path.isfile(os.path.join(self.cfg.conf_dir, f"{name}.example")),
                f"template was removed by reset: {name}.example",
            )

        self.assertTrue(os.path.isfile(staging_secret), "explicit staging secret must survive reset")

    def _case_reset_inventory_names_external_generated_pve_tokens(self):
        self.assertIn("/etc/freq/credentials/pve-token-rw", INIT_GENERATED_TOKEN_FILES)
        self.assertIn("/etc/freq/credentials/pve-token", INIT_GENERATED_TOKEN_FILES)
        self.assertIn("pve-inventory.toml", INIT_LIVE_CONFIG_FILES)

    def _case_reset_removes_generated_runtime_truth_state(self):
        cache_dir = os.path.join(self.cfg.data_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        self._touch(os.path.join(cache_dir, "health.json"), '{"stale":true}\n')
        self._touch(os.path.join(cache_dir, "fleet_overview.json"), '{"stale":true}\n')
        self._touch(os.path.join(cache_dir, "infra_quick.json"), '{"stale":true}\n')
        self._touch(os.path.join(cache_dir, "rule_state.json"), '{"stale":true}\n')
        self._touch(os.path.join(cache_dir, "doctor-fleet-connectivity.lock"), "")
        self._touch(os.path.join(cache_dir, ".gitkeep"), "")

        with tempfile.TemporaryDirectory(prefix="freq-watchdog-state-") as watch_dir:
            watchdog_files = (
                os.path.join(watch_dir, "status.json"),
                os.path.join(watch_dir, "state.json"),
            )
            for path in watchdog_files:
                self._touch(path, '{"status":"degraded"}\n')

            with patch("freq.modules.init_cmd.fmt") as _fmt:
                _fmt.step_ok = MagicMock()
                _fmt.step_warn = MagicMock()
                with patch("freq.modules.init_cmd.INIT_GENERATED_TOKEN_FILES", ()):
                    with patch("freq.modules.init_cmd.INIT_GENERATED_WATCHDOG_FILES", watchdog_files):
                        _reset_local_init_state(self.cfg)

            for name in (
                "health.json",
                "fleet_overview.json",
                "infra_quick.json",
                "rule_state.json",
                "doctor-fleet-connectivity.lock",
            ):
                self.assertFalse(
                    os.path.exists(os.path.join(cache_dir, name)),
                    f"stale runtime cache survived reset: {name}",
                )
            self.assertTrue(
                os.path.isfile(os.path.join(cache_dir, ".gitkeep")),
                "cache placeholder should survive runtime truth cleanup",
            )
            for path in watchdog_files:
                self.assertFalse(os.path.exists(path), f"watchdog state survived reset: {path}")

    def _case_reset_stops_watchdog_before_removing_state(self):
        from freq.modules import init_cmd

        with patch("freq.modules.init_cmd._run", return_value=(1, "", "")) as mock_run:
            with patch("freq.modules.init_cmd.INIT_GENERATED_TOKEN_FILES", ()):
                with patch("freq.modules.init_cmd.INIT_GENERATED_WATCHDOG_FILES", ()):
                    init_cmd._reset_local_init_state(self.cfg)

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn(["systemctl", "disable", "--now", "freq-watchdog.service"], commands)
        self.assertIn(["pkill", "-f", "python3 -m freq watchdog run"], commands)

    def _case_reset_removes_generated_watchdog_user(self):
        from freq.modules import init_cmd

        def fake_run(cmd, **_kwargs):
            if cmd[:2] == ["id", "freq-watch"]:
                return 0, "", ""
            return 0, "", ""

        with patch("freq.modules.init_cmd._run", side_effect=fake_run) as mock_run:
            with patch("freq.modules.init_cmd.INIT_GENERATED_TOKEN_FILES", ()):
                with patch("freq.modules.init_cmd.INIT_GENERATED_WATCHDOG_FILES", ()):
                    init_cmd._reset_local_init_state(self.cfg)

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn(["pkill", "-u", "freq-watch"], commands)
        self.assertIn(["userdel", "-r", "freq-watch"], commands)

    def _case_reset_removes_generated_runtime_ssh_state(self):
        fake_home = os.path.join(self.tmp, "home", "freq")
        ssh_dir = os.path.join(fake_home, ".ssh")
        mux_dir = os.path.join(ssh_dir, "freq-mux")
        self._touch(os.path.join(ssh_dir, "known_hosts"), "old host key\n")
        self._touch(os.path.join(ssh_dir, "known_hosts.old"), "older host key\n")
        os.makedirs(mux_dir, exist_ok=True)
        self._touch(os.path.join(mux_dir, "socket"), "")

        with patch.dict(os.environ, {"HOME": fake_home}):
            with patch("freq.modules.init_cmd.fmt") as _fmt:
                _fmt.step_ok = MagicMock()
                _fmt.step_warn = MagicMock()
                with patch("freq.modules.init_cmd.INIT_GENERATED_TOKEN_FILES", ()):
                    _reset_local_init_state(self.cfg)

        self.assertFalse(os.path.exists(os.path.join(ssh_dir, "known_hosts")))
        self.assertFalse(os.path.exists(os.path.join(ssh_dir, "known_hosts.old")))
        self.assertFalse(os.path.exists(mux_dir))

    def _case_reset_removes_generated_credentials_and_setup_init_secrets(self):
        cred_dir = os.path.join(self.tmp, "runtime-credentials")
        self.cfg.credentials_dir = cred_dir
        self._touch(os.path.join(cred_dir, "device-credentials.toml"), "generated\n")
        self._touch(os.path.join(cred_dir, "pve-token-rw"), "generated\n")
        setup_secret = os.path.join(self.cfg.data_dir, "secrets", "setup-init", "job1", "dashboard-password")
        self._touch(setup_secret, "generated\n")

        with patch("freq.modules.init_cmd.fmt") as _fmt:
            _fmt.step_ok = MagicMock()
            _fmt.step_warn = MagicMock()
            with patch("freq.modules.init_cmd.INIT_GENERATED_TOKEN_FILES", ()):
                _reset_local_init_state(self.cfg, remove_live_config=True)

        self.assertFalse(os.path.exists(cred_dir), "generated runtime credential dir survived reset")
        self.assertFalse(
            os.path.exists(os.path.join(self.cfg.data_dir, "secrets", "setup-init")),
            "stale web-init secret dir survived reset",
        )

    def _case_reset_removes_init_status_and_live_config_backups(self):
        self._touch(os.path.join(self.cfg.conf_dir, "init-status.json"), '{"initialized":true}\n')
        self._touch(os.path.join(self.cfg.conf_dir, "hosts.toml.bak"), "stale\n")
        self._touch(os.path.join(self.cfg.conf_dir, "hosts.toml.tmp"), "stale\n")
        self._touch(os.path.join(self.cfg.conf_dir, "hosts.toml.example"), "template\n")

        with patch("freq.modules.init_cmd.fmt") as _fmt:
            _fmt.step_ok = MagicMock()
            _fmt.step_warn = MagicMock()
            with patch("freq.modules.init_cmd.INIT_GENERATED_TOKEN_FILES", ()):
                _reset_local_init_state(self.cfg, remove_live_config=True)

        self.assertFalse(os.path.exists(os.path.join(self.cfg.conf_dir, "init-status.json")))
        self.assertFalse(os.path.exists(os.path.join(self.cfg.conf_dir, "hosts.toml.bak")))
        self.assertFalse(os.path.exists(os.path.join(self.cfg.conf_dir, "hosts.toml.tmp")))
        self.assertTrue(os.path.isfile(os.path.join(self.cfg.conf_dir, "hosts.toml.example")))

    def _case_reset_inventory_names_generated_watchdog_state(self):
        self.assertIn("/var/lib/freq-watchdog/status.json", INIT_GENERATED_WATCHDOG_FILES)
        self.assertIn("/var/lib/freq-watchdog/state.json", INIT_GENERATED_WATCHDOG_FILES)

    def _case_missing_generated_runtime_truth_is_clean_not_warning(self):
        from freq.modules.init_cmd import _clear_generated_runtime_truth_state

        with tempfile.TemporaryDirectory(prefix="freq-runtime-clean-") as tmp:
            cfg = types.SimpleNamespace(data_dir=os.path.join(tmp, "data"))
            watchdog_files = (
                os.path.join(tmp, "watchdog", "status.json"),
                os.path.join(tmp, "watchdog", "state.json"),
            )
            with patch("freq.modules.init_cmd.INIT_GENERATED_WATCHDOG_FILES", watchdog_files):
                with patch("freq.modules.init_cmd.fmt") as mock_fmt:
                    mock_fmt.step_ok = MagicMock()
                    mock_fmt.step_warn = MagicMock()
                    _clear_generated_runtime_truth_state(cfg)

            mock_fmt.step_warn.assert_not_called()
            messages = " ".join(str(c.args[0]) for c in mock_fmt.step_ok.call_args_list)
            self.assertIn("Runtime truth cache clean", messages)
            self.assertIn("Watchdog state status.json already clean", messages)


INIT_RESET_LOCAL_STATE_CASES = (
    "_case_reset_removes_generated_state_and_live_config_only",
    "_case_reset_inventory_names_external_generated_pve_tokens",
    "_case_reset_removes_generated_runtime_truth_state",
    "_case_reset_stops_watchdog_before_removing_state",
    "_case_reset_removes_generated_watchdog_user",
    "_case_reset_removes_generated_runtime_ssh_state",
    "_case_reset_removes_generated_credentials_and_setup_init_secrets",
    "_case_reset_removes_init_status_and_live_config_backups",
    "_case_reset_inventory_names_generated_watchdog_state",
    "_case_missing_generated_runtime_truth_is_clean_not_warning",
)


class TestInitResetLocalStateMatrix(unittest.TestCase):
    def test_init_reset_local_state_matrix(self):
        run_case_matrix(self, TestInitResetLocalState, INIT_RESET_LOCAL_STATE_CASES)


class TestPureNothingInitContract(unittest.TestCase):
    """Pure first-run init must create the runtime world from empty state."""

    def _src(self):
        return (Path(__file__).parent.parent / "freq" / "modules" / "init_cmd.py").read_text()

    def _assert_optional_sshpass_package_contract(self):
        from freq.core.packages import install_command_candidates
        from freq.modules import init_cmd

        managers = ("apt-get", "dnf", "zypper")
        installs = {
            "apt-get": ["sudo", "apt-get", "install", "-y", "sshpass"],
            "dnf": ["sudo", "dnf", "install", "-y", "sshpass"],
            "zypper": [
                "sudo",
                "zypper",
                "--non-interactive",
                "install",
                "sshpass",
            ],
        }
        self.assertIs(
            init_cmd._install_command_candidates,
            install_command_candidates,
        )
        self.assertEqual(
            install_command_candidates("sshpass", sudo=True),
            tuple((manager, installs[manager]) for manager in managers),
        )
        cases = (
            ("already-present", None, 0),
            ("apt-get-success", "apt-get", 0),
            ("dnf-success", "dnf", 0),
            ("zypper-success", "zypper", 0),
            ("dnf-install-failure", "dnf", 17),
            ("no-manager", "", 0),
        )
        for case, available_manager, install_rc in cases:
            with self.subTest(package_case=case), tempfile.TemporaryDirectory(
                prefix="freq-package-owner-"
            ) as root:
                cfg = types.SimpleNamespace(
                    conf_dir=os.path.join(root, "conf"),
                    data_dir=os.path.join(root, "data"),
                    log_file=os.path.join(root, "log", "freq.log"),
                    vault_dir=os.path.join(root, "vault"),
                    key_dir=os.path.join(root, "keys"),
                    credentials_dir=os.path.join(root, "credentials"),
                )

                def run(command, timeout=None):
                    if command[0] == "which":
                        executable = command[1]
                        if executable in {"ssh", "ssh-keygen", "openssl", "jq", "curl"}:
                            return 0, f"/usr/bin/{executable}", ""
                        if executable == "sshpass":
                            return (
                                (0, "/usr/bin/sshpass", "")
                                if available_manager is None
                                else (1, "", "")
                            )
                        return (
                            (0, f"/usr/bin/{executable}", "")
                            if executable == available_manager
                            else (1, "", "")
                        )
                    if available_manager and command == installs[available_manager]:
                        return install_rc, "", "install failed" if install_rc else ""
                    self.fail(f"unexpected prerequisite command: {command!r}")

                with patch.object(init_cmd, "_run", side_effect=run) as run_mock, patch.object(
                    init_cmd, "_seed_config_files"
                ) as seed, patch.object(init_cmd, "fmt") as render, patch.object(
                    init_cmd, "logger"
                ):
                    render.C = types.SimpleNamespace(DIM="", RESET="", RED="")
                    self.assertTrue(init_cmd._phase_welcome(cfg))

                manager_probes = [
                    call.args[0]
                    for call in run_mock.call_args_list
                    if call.args[0][0] == "which" and call.args[0][1] in managers
                ]
                if available_manager is None:
                    self.assertEqual(manager_probes, [])
                    self.assertFalse(
                        any(
                            call.args[0] in installs.values()
                            for call in run_mock.call_args_list
                        )
                    )
                elif available_manager:
                    manager_index = managers.index(available_manager)
                    self.assertEqual(
                        manager_probes,
                        [["which", manager] for manager in managers[: manager_index + 1]],
                    )
                    run_mock.assert_any_call(installs[available_manager], timeout=120)
                    if install_rc:
                        render.step_warn.assert_any_call(
                            "Password-based SSH (for initial deployment) — "
                            "auto-install failed (install manually)"
                        )
                    else:
                        render.step_ok.assert_any_call(
                            "Password-based SSH (for initial deployment) (auto-installed)"
                        )
                else:
                    self.assertEqual(
                        manager_probes,
                        [["which", manager] for manager in managers],
                    )
                    render.step_warn.assert_any_call(
                        "Password-based SSH (for initial deployment) — "
                        "'sshpass' not found (install recommended)"
                    )
                seed.assert_called_once_with(cfg)
                for path in (
                    cfg.conf_dir,
                    cfg.data_dir,
                    os.path.dirname(cfg.log_file),
                    cfg.vault_dir,
                    cfg.key_dir,
                    cfg.credentials_dir,
                ):
                    self.assertTrue(os.path.isdir(path))

        with tempfile.TemporaryDirectory(prefix="freq-package-required-") as root:
            cfg = types.SimpleNamespace(
                conf_dir=os.path.join(root, "conf"),
                data_dir=os.path.join(root, "data"),
                log_file=os.path.join(root, "log", "freq.log"),
                vault_dir=os.path.join(root, "vault"),
                key_dir=os.path.join(root, "keys"),
                credentials_dir=os.path.join(root, "credentials"),
            )

            def missing_required(command, timeout=None):
                if command[:2] == ["which", "ssh"]:
                    return 1, "", ""
                return 0, "", ""

            with patch.object(
                init_cmd, "_run", side_effect=missing_required
            ), patch.object(init_cmd, "_seed_config_files") as seed, patch.object(
                init_cmd, "fmt"
            ) as render, patch.object(
                init_cmd, "logger"
            ):
                render.C = types.SimpleNamespace(DIM="", RESET="", RED="")
                self.assertFalse(init_cmd._phase_welcome(cfg))
            render.step_fail.assert_any_call("SSH client (required) — 'ssh' not found")
            seed.assert_not_called()
            self.assertFalse(os.path.exists(cfg.conf_dir))

    def _assert_pdm_package_contract(self):
        from freq.core.packages import install_argv, update_argv
        from freq.modules import init_cmd

        os_check = ["cat", "/etc/os-release"]
        key_download = [
            "wget",
            "-qO",
            "/etc/apt/trusted.gpg.d/proxmox-release-trixie.gpg",
            "https://enterprise.proxmox.com/debian/proxmox-release-trixie.gpg",
        ]
        update = ["apt-get", "update", "-qq"]
        install = [
            "apt-get",
            "install",
            "-y",
            "proxmox-datacenter-manager",
        ]
        service = ["systemctl", "is-active", "proxmox-datacenter-api"]
        complete_flow = (
            (os_check, None),
            (key_download, 30),
            (update, 120),
            (install, 600),
            (service, None),
        )
        cases = (
            ("incompatible-os", "os", 1, False),
            ("os-probe-failure", "os-probe", 1, False),
            ("key-download-failure", "key", 2, False),
            ("repository-write-failure", "repository", 2, False),
            ("package-index-failure", "update", 3, False),
            ("package-install-failure", "install", 4, False),
            ("service-inactive", "service", 5, False),
            ("success", "success", 5, True),
        )
        repo_line = "deb http://download.proxmox.com/debian/pdm trixie pdm-no-subscription\n"
        repo_path = "/etc/apt/sources.list.d/pdm.list"
        self.assertIs(init_cmd._package_update_argv, update_argv)
        self.assertIs(init_cmd._package_install_argv, install_argv)
        self.assertEqual(update_argv("apt-get", quiet=True), update)
        self.assertEqual(
            install_argv("proxmox-datacenter-manager", "apt-get"),
            install,
        )

        for case, failure, expected_count, expected_result in cases:
            with self.subTest(pdm_package_case=case):
                def run(command, timeout=None):
                    if command == os_check:
                        if failure == "os-probe":
                            return 23, "VERSION_CODENAME=trixie", "probe failed"
                        if failure == "os":
                            return 0, "VERSION_CODENAME=bookworm", ""
                        return 0, "VERSION_CODENAME=trixie", ""
                    if command == key_download:
                        return (17, "", "key download failed") if failure == "key" else (0, "", "")
                    if command == update:
                        return (18, "", "index update failed") if failure == "update" else (0, "", "")
                    if command == install:
                        return (19, "", "package install failed") if failure == "install" else (0, "", "")
                    if command == service:
                        return (20, "", "") if failure == "service" else (0, "", "")
                    self.fail(f"unexpected PDM package command: {command!r}")

                repo_file = MagicMock()
                repo_handle = repo_file.return_value.__enter__.return_value
                if failure == "repository":
                    repo_file.side_effect = OSError("repository read-only")

                with patch.object(
                    init_cmd, "_package_update_argv", wraps=update_argv
                ) as update_builder, patch.object(
                    init_cmd, "_package_install_argv", wraps=install_argv
                ) as install_builder, patch.object(
                    init_cmd, "_run", side_effect=run
                ) as run_mock, patch(
                    "builtins.open", repo_file
                ), patch.object(init_cmd, "fmt") as render:
                    render.C = types.SimpleNamespace(DIM="", RESET="")
                    self.assertIs(init_cmd._pdm_install(), expected_result)

                if failure in {"update", "install", "service", "success"}:
                    update_builder.assert_called_once_with("apt-get", quiet=True)
                else:
                    update_builder.assert_not_called()
                if failure in {"install", "service", "success"}:
                    install_builder.assert_called_once_with(
                        "proxmox-datacenter-manager", "apt-get"
                    )
                else:
                    install_builder.assert_not_called()
                actual_flow = [
                    (mock_call.args[0], mock_call.kwargs.get("timeout"))
                    for mock_call in run_mock.call_args_list
                ]
                self.assertEqual(actual_flow, list(complete_flow[:expected_count]))
                if failure not in {"os", "os-probe", "key"}:
                    repo_file.assert_called_once_with(repo_path, "w")
                    if failure != "repository":
                        repo_handle.write.assert_called_once_with(repo_line)
                else:
                    repo_file.assert_not_called()

                if failure in {"os", "os-probe"}:
                    render.step_fail.assert_any_call("PDM requires Debian 13 (trixie)")
                elif failure == "key":
                    render.step_fail.assert_any_call("Failed to download GPG key: key download failed")
                elif failure == "repository":
                    render.step_fail.assert_any_call(
                        f"Cannot write {repo_path}: repository read-only"
                    )
                elif failure == "update":
                    render.step_fail.assert_any_call("apt-get update failed: index update failed")
                elif failure == "install":
                    render.step_fail.assert_any_call("Installation failed: package install failed")
                elif failure == "service":
                    render.step_warn.assert_any_call(
                        "PDM installed but service not running — try: "
                        "systemctl start proxmox-datacenter-api"
                    )
                else:
                    render.step_ok.assert_any_call("PDM installed and running")

    def _assert_guest_agent_package_contract(self):
        from freq.core.packages import remote_install_script
        from freq.modules import init_cmd

        package_script = (
            "which apt-get >/dev/null 2>&1 && sudo apt-get install -y "
            "qemu-guest-agent >/dev/null 2>&1"
            " || which dnf >/dev/null 2>&1 && sudo dnf install -y "
            "qemu-guest-agent >/dev/null 2>&1"
            " || which zypper >/dev/null 2>&1 && sudo zypper install -y "
            "qemu-guest-agent >/dev/null 2>&1"
        )
        install_script = (
            package_script
            + "; sudo systemctl enable --now qemu-guest-agent 2>/dev/null"
        )
        self.assertIs(init_cmd._package_remote_install_script, remote_install_script)
        self.assertEqual(
            remote_install_script("qemu-guest-agent", sudo=True, quiet=True),
            package_script,
        )
        hostile_package = "pkg; touch /tmp/guest-agent-owner-false-green"
        self.assertEqual(
            remote_install_script(
                hostile_package,
                managers=("apt-get",),
                sudo=True,
            ),
            "which apt-get && sudo apt-get install -y "
            "'pkg; touch /tmp/guest-agent-owner-false-green'",
        )
        with self.assertRaisesRegex(
            ValueError,
            "^Unsupported remote package manager candidate: unsupported-manager$",
        ):
            remote_install_script(
                "qemu-guest-agent",
                managers=("apt-get", "unsupported-manager"),
                sudo=True,
            )
        cases = (
            ("unmanaged", False, 1, ()),
            ("already-running", True, 0, ("check",)),
            ("install-success", True, 0, ("check-failed", "install")),
            ("install-failure", True, 23, ("check-failed", "install")),
        )

        for case, managed, install_rc, expected_stages in cases:
            with self.subTest(guest_agent_package_case=case), tempfile.TemporaryDirectory(
                prefix="freq-guest-agent-owner-"
            ) as root:
                root_path = Path(root)
                conf_dir = root_path / "conf"
                key_dir = root_path / "data" / "keys"
                tls_dir = root_path / "tls"
                credentials_dir = root_path / "credentials"
                for directory in (conf_dir, key_dir, tls_dir, credentials_dir):
                    directory.mkdir(parents=True)
                key_path = key_dir / "freq_id_ed25519"
                key_path.write_text("private-key")
                cert_path = tls_dir / "freq.crt"
                tls_key_path = tls_dir / "freq.key"
                cert_path.write_text("certificate")
                tls_key_path.write_text("private-key")
                (conf_dir / "freq.toml").write_text(
                    "[server]\n"
                    f'tls_cert = "{cert_path}"\n'
                    f'tls_key = "{tls_key_path}"\n'
                    "[safety]\n"
                )
                host = types.SimpleNamespace(
                    ip="192.0.2.50",
                    label="guest-linux",
                    htype="linux",
                    managed=managed,
                )
                cfg = types.SimpleNamespace(
                    hosts=[host],
                    pve_nodes=[],
                    pve_node_names=[],
                    ssh_key_path=str(key_path),
                    ssh_service_account="freq-admin",
                    conf_dir=str(conf_dir),
                    credentials_dir=str(credentials_dir),
                    install_dir=str(root_path),
                    pfsense_ip="",
                    vlans=[],
                    _headless=True,
                )
                ssh_prefix = [
                    "ssh",
                    "-n",
                    "-o",
                    "ConnectTimeout=5",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "-i",
                    str(key_path),
                    "freq-admin@192.0.2.50",
                ]
                check = ssh_prefix + [
                    "systemctl is-active qemu-guest-agent 2>/dev/null"
                ]
                install = ssh_prefix + [install_script]

                def run(command, timeout=None):
                    if command == check:
                        return (0, "", "") if case == "already-running" else (1, "", "")
                    if command == install:
                        return install_rc, "", ""
                    self.fail(f"unexpected guest-agent command: {command!r}")

                with patch.object(init_cmd, "_fetch_pve_resources", return_value=[]), patch.object(
                    init_cmd, "_metrics_agent_hosts", return_value=[]
                ), patch.object(
                    init_cmd, "_non_systemd_metrics_hosts", return_value=[]
                ), patch.object(
                    init_cmd.shutil, "which", return_value=None
                ), patch.object(
                    init_cmd, "_post_init_runtime_owner", return_value="freq-admin"
                ), patch.object(
                    init_cmd, "normalize_owned_install_root"
                ), patch.object(
                    init_cmd, "_chown", return_value=True
                ), patch.object(
                    init_cmd.audit, "record"
                ), patch.object(
                    init_cmd,
                    "_package_remote_install_script",
                    wraps=remote_install_script,
                ) as install_builder, patch.object(
                    init_cmd, "_run", side_effect=run
                ) as run_mock, patch.object(
                    init_cmd, "fmt"
                ) as render, patch.object(
                    init_cmd, "logger"
                ):
                    render.C = types.SimpleNamespace(
                        BOLD="", RESET="", DIM="", GREEN="", RED="", YELLOW=""
                    )
                    init_cmd._phase_fleet_configure(cfg, {})

                if "install" in expected_stages:
                    install_builder.assert_called_once_with(
                        "qemu-guest-agent",
                        sudo=True,
                        quiet=True,
                    )
                else:
                    install_builder.assert_not_called()

                actual_calls = [
                    (mock_call.args[0], mock_call.kwargs.get("timeout"))
                    for mock_call in run_mock.call_args_list
                ]
                expected_calls = []
                if "check" in expected_stages or "check-failed" in expected_stages:
                    expected_calls.append((check, 10))
                if "install" in expected_stages:
                    expected_calls.append((install, 60))
                self.assertEqual(actual_calls, expected_calls)
                if case == "already-running":
                    render.step_ok.assert_any_call(
                        "Guest agent: all 1 VMs already have it"
                    )
                elif case == "install-success":
                    render.step_ok.assert_any_call(
                        "Guest agent: 1 newly installed, 0 already running"
                    )
                elif case == "install-failure":
                    render.line.assert_any_call(
                        "  No VMs reachable for guest agent install."
                    )
                else:
                    render.line.assert_any_call(
                        "  No VM hosts to install guest agent on."
                    )

    def test_first_run_lifecycle_wiring_contract(self):
        self._assert_optional_sshpass_package_contract()
        src = self._src()
        phase1 = src.split("def _phase_welcome", 1)[1].split("\ndef _seed_config_files", 1)[0]
        for token in (
            "cfg.conf_dir",
            "cfg.data_dir",
            'os.path.join(cfg.data_dir, "cache")',
            'os.path.join(cfg.data_dir, "secrets")',
            "_credentials_dir(cfg)",
        ):
            with self.subTest(contract="phase1-directory", token=token):
                self.assertIn(token, phase1)

        headless = src.split("def _init_headless", 1)[1].split("\ndef _headless_local_account", 1)[0]
        self.assertLess(
            headless.index("_begin_init_phase(phases[0], headless_total, ctx)"),
            headless.index(
                "_cross_init_point_of_no_return(cfg, ctx, clear_runtime_truth=True)"
            ),
        )
        ponr = src.split("def _cross_init_point_of_no_return", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("_clear_generated_runtime_truth_state(cfg)", ponr)
        self.assertIn("if not _ensure_post_init_runtime_state_ownership", headless)
        self.assertIn("Post-init runtime ownership could not be applied", headless)
        self.assertIn("return 1", headless)
        self.assertGreaterEqual(src.count("if not _ensure_post_init_runtime_state_ownership"), 2)

        cmd_init = src.split("def cmd_init", 1)[1].split("\ndef _print_status_table", 1)[0]
        self.assertLess(cmd_init.index("if reset_mode:"), cmd_init.index("# --headless: non-interactive mode"))
        self.assertIn('assume_yes=getattr(args, "headless", False)', cmd_init)

        stale_retry = src.split("def _run_ssh_with_stale_hostkey_retry", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("_is_host_key_mismatch", stale_retry)
        self.assertIn("_forget_stale_known_host_for_init", stale_retry)
        self.assertEqual(stale_retry.count("_run(cmd, timeout=timeout)"), 2)
        self.assertIn("_run_ssh_with_stale_hostkey_retry(ssh_cmd, VERIFY_TIMEOUT", src)
        self.assertIn(
            '_run_ssh_with_stale_hostkey_retry(\n                    ssh_cmd + ["echo ok"]',
            src,
        )
        forget = src.split("def _forget_stale_known_host_for_init", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('["ssh-keygen", "-R", ip, "-f", known_hosts]', forget)

        phase9 = src.split("Fix ownership for dashboard", 1)[1].split(
            'logger.info("init_phase_complete: Phase 9', 1
        )[0]
        self.assertIn("cred_dir = _credentials_dir(cfg)", phase9)
        self.assertIn("runtime_owner = _post_init_runtime_owner(svc_name)", phase9)
        self.assertIn("_chown(_credential_owner(runtime_owner), cred_dir, recursive=False)", phase9)
        self.assertNotIn('"credentials"', phase9.split("for subdir in", 1)[1].split("]:", 1)[0])

    def test_identity_storage_behavior_contract(self):
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory() as td:
            cfg = types.SimpleNamespace(
                credentials_dir=td,
                conf_dir=td,
                ssh_key_path=os.path.join(td, "id_ed25519"),
                ssh_rsa_key_path=os.path.join(td, "id_rsa"),
            )
            owners = []
            with patch.object(init_cmd, "_chown", side_effect=lambda owner, *paths, **kwargs: owners.append((owner, paths, kwargs)) or True), \
                 patch.object(init_cmd, "fmt"):
                init_cmd._persist_service_account_credentials_metadata(cfg, "dc01-admin", "stored-secret")

            password_path = os.path.join(td, "dc01-admin-password")
            metadata_path = os.path.join(td, "device-credentials.toml")
            self.assertEqual(stat.S_IMODE(os.stat(password_path).st_mode), 0o640)
            self.assertEqual(stat.S_IMODE(os.stat(metadata_path).st_mode), 0o640)
            self.assertEqual(init_cmd._load_existing_service_account_password(cfg, "dc01-admin"), "stored-secret")
            self.assertEqual(init_cmd._load_existing_service_account_password(cfg, "missing"), "")
            self.assertEqual([paths[0] for _owner, paths, _kwargs in owners], [password_path, metadata_path])
            self.assertTrue(all(owner == init_cmd._credential_owner("dc01-admin") for owner, _paths, _kwargs in owners))

        src = self._src()
        fix = src.split("def _init_fix", 1)[1].split("# Build deploy context", 1)[1].split(
            'if not ctx["pubkey"]', 1
        )[0]
        self.assertIn("_load_existing_service_account_password(cfg, svc_name)", fix)
        self.assertIn("secrets.token_urlsafe(24)", fix)

    def test_dashboard_admin_input_and_auth_behavior_contract(self):
        from freq.api.auth import verify_password
        from freq.cli import _build_parser
        from freq.modules import init_cmd

        args = _build_parser().parse_args(
            [
                "init",
                "--headless",
                "--dashboard-user",
                "sonny-aif",
                "--dashboard-password-file",
                "/tmp/dashboard.pass",
            ]
        )
        self.assertEqual(args.dashboard_user, "sonny-aif")
        self.assertEqual(args.dashboard_password_file, "/tmp/dashboard.pass")

        with tempfile.TemporaryDirectory() as td:
            cfg = types.SimpleNamespace(conf_dir=td, vault_file=os.path.join(td, "vault.enc"))
            written = {}

            def vault_set(_cfg, section, key, value):
                written[(section, key)] = value
                return True

            with patch("freq.modules.vault.vault_init", return_value=True), \
                 patch("freq.modules.vault.vault_set", side_effect=vault_set), \
                 patch("freq.modules.vault.vault_get", side_effect=lambda _cfg, section, key: written.get((section, key), "")), \
                 patch.object(init_cmd, "fmt"):
                self.assertTrue(
                    init_cmd._seed_headless_dashboard_auth(
                        cfg, "sonny-aif", "correct-horse-battery-staple", "dc01-admin", verbose=True
                    )
                )

            self.assertIn("sonny-aif:admin", Path(td, "roles.conf").read_text())
            self.assertIn("sonny-aif admin", Path(td, "users.conf").read_text())
            self.assertNotIn("dc01-admin", Path(td, "roles.conf").read_text())
            self.assertTrue(
                verify_password(
                    "correct-horse-battery-staple",
                    written[("auth", "password_sonny-aif")],
                )
            )

            with patch("freq.modules.vault.vault_init", return_value=True), \
                 patch("freq.modules.vault.vault_set", return_value=False), \
                 patch.object(init_cmd, "fmt"):
                self.assertFalse(
                    init_cmd._seed_headless_dashboard_auth(
                        cfg, "sonny-aif", "correct-horse-battery-staple", "dc01-admin", verbose=True
                    )
                )

    def test_dry_run_and_pdm_behavior_contract(self):
        from freq.modules import init_cmd

        self._assert_pdm_package_contract()
        self._assert_guest_agent_package_contract()

        cfg = FreqConfig()
        cfg.install_dir = "/opt/pve-freq"
        _resolve_paths(cfg)
        args = types.SimpleNamespace(service_account="dc01-admin", pve_nodes="10.25.255.26,10.25.255.27")
        lines = []
        colors = types.SimpleNamespace(DIM="", RESET="", BOLD="")
        with patch.object(init_cmd, "fmt") as mock_fmt:
            mock_fmt.C = colors
            mock_fmt.line.side_effect = lines.append
            self.assertEqual(_init_dry_run(cfg, args), 0)
        plan = "\n".join(lines)
        self.assertIn("Deploy dc01-admin to 2 PVE node(s)", plan)
        self.assertIn("Create dc01-admin@pam!freq-rw token", plan)
        self.assertNotIn("Deploy freq-admin to 0 PVE node(s)", plan)

        with patch.object(init_cmd, "fmt") as mock_fmt:
            init_cmd._phase_pdm(
                types.SimpleNamespace(),
                {},
                types.SimpleNamespace(skip_pdm=True, install_pdm=False, headless=True),
            )
        mock_fmt.step_ok.assert_called_once_with("PDM setup intentionally skipped (--skip-pdm)")
        mock_fmt.step_warn.assert_not_called()

        token_json = '{"full-tokenid":"pdm@pve!pdm","value":"secret-value"}'
        token_cfg = types.SimpleNamespace(ssh_service_account="dc01-admin")
        with patch.object(init_cmd, "_run") as mock_run:
            mock_run.side_effect = [(0, "[]", ""), (0, "", ""), (0, "", ""), (0, token_json, "")]
            self.assertEqual(
                init_cmd._pdm_create_pve_token("10.25.255.26", {"key_path": "/tmp/freq_id_ed25519"}, token_cfg),
                ("pdm@pve!pdm", "secret-value"),
            )
        self.assertIn("dc01-admin@10.25.255.26", mock_run.call_args_list[0].args[0])

        cli_src = (Path(__file__).parent.parent / "freq" / "cli.py").read_text()
        self.assertIn("readonly_init_dry_run", cli_src)
        self.assertIn('getattr(args, "domain", "") == "init"', cli_src)
        self.assertIn('getattr(args, "dry_run", False)', cli_src)
        self.assertIn("watchdog_command", cli_src)
        self.assertIn("nonroot_init", cli_src)
        self.assertIn("skip_runtime_writes", cli_src)
        self.assertIn("if not skip_runtime_writes:", cli_src)

    def test_managed_host_reconciliation_policy_contract(self):
        from freq.modules import init_cmd

        cases = (
            (
                "demote non-owned and preserve owned",
                [
                    ("pve-freq", "10.25.255.50", "pve", 100, True),
                    ("blue", "10.25.255.75", "linux", 0, True),
                    ("email-server", "10.25.255.44", "linux", 404, True),
                    ("plex", "10.25.255.30", "docker", 201, True),
                ],
                {100, 201},
                {802},
                {"ip_vmid_map": {"10.25.255.75": 802}, "label_vmid_map": {"blue": 802}},
                (False, False, False, True),
                3,
                None,
            ),
            (
                "promote newly owned despite stale category",
                [("dc01-proxy", "10.25.255.38", "linux", 106, False)],
                {106},
                set(),
                {},
                (True,),
                1,
                ("dc01-proxy (10.25.255.38) — owned VMID 106",),
            ),
            (
                "do not promote operator or nested pve",
                [
                    ("pve-freq", "10.25.255.50", "linux", 100, False),
                    ("lab-pve1", "10.25.10.202", "pve", 5002, False),
                ],
                {100, 5002},
                set(),
                {},
                (True, False),
                1,
                ("pve-freq (10.25.255.50) — owned VMID 100",),
            ),
        )
        self.assertEqual(len(cases), 3)
        for title, specs, owned, acknowledged, ctx, expected, changed_count, expected_changes in cases:
            hosts = [
                types.SimpleNamespace(label=label, ip=ip, htype=htype, vmid=vmid, managed=managed, all_ips=[ip])
                for label, ip, htype, vmid, managed in specs
            ]
            boundaries = types.SimpleNamespace(
                categorize=lambda vmid: ("out_of_contract", "probe") if vmid in {404, 106} else ("production", "operator")
            )
            cfg = types.SimpleNamespace(
                hosts=hosts,
                hosts_file="/tmp/hosts.toml",
                pve_nodes=["10.25.255.26"],
                operator_exclude_labels=[],
                fleet_boundaries=boundaries,
                _owned_vmids=owned,
                _acknowledged_out_of_contract_vmids=acknowledged,
            )
            with self.subTest(policy=title), patch("freq.core.config.save_hosts_toml") as save:
                changed = init_cmd._reconcile_existing_managed_hosts(cfg, ctx)
                self.assertEqual(tuple(h.managed for h in hosts), expected)
                self.assertEqual(len(changed), changed_count)
                if expected_changes is not None:
                    self.assertEqual(tuple(changed), expected_changes)
                self.assertEqual(save.call_count, int(changed_count > 0))

        src = self._src()
        scan = src.split("def _scan_fleet", 1)[1].split("def _init_check", 1)[0]
        self.assertIn("not _inventory_only_reason(cfg, {}, h)", scan)
        headless = src.split("def _init_headless", 1)[1]
        imported = headless.split("# Import hosts from --hosts-file if provided", 1)[1].split(
            "# Load per-device credentials", 1
        )[0]
        self.assertLess(
            imported.index("_reconcile_existing_managed_hosts(cfg, ctx)"),
            imported.index('fmt.step_ok(f"Imported {len(cfg.hosts)} host(s) from {hosts_file_arg}")'),
        )
        interactive_phase9 = src.split("# Phase 10: PDM Setup (optional)", 1)[1].split(
            "# Phase 11: Admin Accounts", 1
        )[0]
        headless_phase9 = src.split("# ── Phase 10: PDM Setup ──", 1)[1].split("# ── Phase 11: RBAC ──", 1)[0]
        self.assertIn("_reconcile_existing_managed_hosts(cfg, ctx)", interactive_phase9)
        self.assertIn("_reconcile_existing_managed_hosts(cfg, ctx)", headless_phase9)

    def test_inventory_and_metrics_truth_contract(self):
        from freq.modules import init_cmd

        hosts = [
            types.SimpleNamespace(label="linux-a", htype="linux", managed=True),
            types.SimpleNamespace(label="docker-a", htype="docker", managed=True),
            types.SimpleNamespace(label="pve-a", htype="pve", managed=True),
            types.SimpleNamespace(label="truenas-a", htype="truenas", managed=True),
            types.SimpleNamespace(label="switch-a", htype="switch", managed=True),
            types.SimpleNamespace(label="linux-unmanaged", htype="linux", managed=False),
        ]
        self.assertEqual([h.label for h in init_cmd._metrics_agent_hosts(hosts)], ["linux-a", "docker-a", "pve-a"])
        self.assertEqual([h.label for h in init_cmd._non_systemd_metrics_hosts(hosts)], ["truenas-a"])

        if tomllib is None:
            self.skipTest("tomllib unavailable")
        resources = [
            {"vmid": 100, "name": "pve-freq", "node": "pve01", "type": "qemu", "status": "running"},
            {"vmid": 400, "name": "RunescapeBotVM", "node": "pve01", "type": "qemu", "status": "running"},
            {"vmid": 9000, "name": "debian-template", "node": "pve02", "type": "qemu", "status": "stopped"},
            {"vmid": 500, "name": "flag-template", "node": "pve03", "type": "qemu", "status": "stopped", "template": 1},
        ]
        with tempfile.TemporaryDirectory(prefix="freq-pve-inventory-") as tmp:
            path, vm_count, template_count, container_count = init_cmd._write_pve_inventory_toml(
                types.SimpleNamespace(conf_dir=tmp), resources
            )
            with open(path, "rb") as f:
                data = tomllib.load(f)
        self.assertEqual((vm_count, template_count, container_count), (2, 2, 0))
        self.assertEqual(data["summary"], {"resource_count": 4, "vm_count": 2, "template_count": 2, "container_count": 0})
        self.assertEqual({row["vmid"]: row["kind"] for row in data["resource"]}, {100: "vm", 400: "vm", 500: "template", 9000: "template"})

        src = self._src()
        metrics_verify = src.split("# Metrics agent verification for every generic systemd agent host.", 1)[1].split(
            "# Dashboard readiness", 1
        )[0]
        self.assertIn("for h in agent_hosts:", metrics_verify)
        self.assertIn('f"Metrics agents responding: {agent_ok}/{len(agent_hosts)}"', metrics_verify)
        inventory = src.split("# pve-inventory.toml", 1)[1].split("# containers.toml", 1)[0]
        for token in (
            'inv_path = os.path.join(cfg.conf_dir, "pve-inventory.toml")',
            'r.get("kind") == "vm"',
            'r.get("kind") == "template"',
            "summary mismatch",
        ):
            self.assertIn(token, inventory)

    def test_device_verification_truth_contract(self):
        src = self._src()
        init_check = src.split("\ndef _init_check(", 1)[1]
        labels = init_check.split("if json_output:", 1)[0]
        self.assertIn('detail = f"SSH verified [{htype}]"', labels)
        self.assertIn('elif htype in ("pfsense", "idrac", "switch")', labels)
        self.assertNotIn('detail = "account + key verified"', labels)

        linux = init_check.split('if htype in ("linux", "pve", "docker"):', 1)[1].split(
            'elif htype == "truenas":', 1
        )[0]
        self.assertIn("_remote_home_probe(svc_name)", linux)
        self.assertIn('test -f \\"$home/.ssh/authorized_keys\\"', linux)
        self.assertNotIn("_home_dir_for_user", linux)
        truenas = init_check.split('elif htype == "truenas":', 1)[1].split('elif htype == "pfsense":', 1)[0]
        self.assertIn("test -f ~/.ssh/authorized_keys", truenas)
        self.assertNotIn("auth_keys", truenas)

        remote_home = _remote_home_probe("freq-admin")
        self.assertIn("getent passwd", remote_home)
        self.assertIn("/home/freq-admin", remote_home)
        self.assertIn("awk -F:", remote_home)

        container = init_check.split('rc, _, _ = _run(["id", svc_name])', 1)[1].split("key_file =", 1)[0]
        for token in ("_is_container_runtime()", "_service_account_is_remote_runtime(cfg, True)", "os.path.isfile(marker)"):
            self.assertIn(token, container)
        self.assertIn("is remote-only on this runtime", container)

        verify_host = src.split('if htype == "pfsense" and cfg is not None:', 1)[1].split(
            "# Select key and command", 1
        )[0]
        self.assertIn('resolve_staged_device_ssh_auth(cfg, "pfsense")', verify_host)
        self.assertIn('local_user=auth.get("local_user")', verify_host)

        deployable = src.split("def _pfsense_is_deployable():", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("_device_cred_has_ssh_material(pfsense_creds)", deployable)
        self.assertNotIn('user in {"root", "admin"}', deployable)
        deep = src.split("def _deep_check(entry):", 1)[1].split("with _cf.ThreadPoolExecutor", 1)[0]
        pfsense = deep.split('elif htype == "pfsense":', 1)[1].split("else:", 1)[0]
        self.assertIn('cmd = "echo DEEP_CHECK_OK"', pfsense)
        self.assertIn("use_key = key_file", pfsense)
        self.assertNotIn("return label, ip, htype, True", pfsense)


# ═══════════════════════════════════════════════════════════════════
# _ssh_with_pass() tests
# ═══════════════════════════════════════════════════════════════════

class TestSSHWithPass(unittest.TestCase):
    """Test the sshpass-based SSH runner with tempfile password handling."""

    @patch("freq.modules.init_cmd._run")
    def _case_calls_run_without_input_text(self, mock_run):
        """Without input_text, delegates to _run (no stdin)."""
        mock_run.return_value = (0, "ok", "")
        rc, out, err = _ssh_with_pass("secret", ["ssh", "user@host", "uptime"])
        self.assertEqual(rc, 0)
        mock_run.assert_called_once()
        # sshpass is wrapped in GNU timeout for hard process-level kill.
        # Command shape is:
        # timeout -k 5s <N> sshpass -f <tmpfile> <ssh_cmd...>
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "timeout")
        self.assertEqual(cmd[1], "-k")
        self.assertEqual(cmd[2], "5s")
        # cmd[3] is the timeout value (string)
        self.assertEqual(cmd[4], "sshpass")
        self.assertEqual(cmd[5], "-f")
        # cmd[6] is the tempfile path, then original SSH args follow
        self.assertEqual(cmd[7:], ["ssh", "user@host", "uptime"])

    @patch("freq.modules.init_cmd._run_with_input")
    def _case_calls_run_with_input_when_input_text_provided(self, mock_run_input):
        """With input_text, delegates to _run_with_input (stdin piped)."""
        mock_run_input.return_value = (0, "configured", "")
        rc, out, err = _ssh_with_pass(
            "secret", ["ssh", "user@switch", ""], input_text="conf t\nend\n"
        )
        self.assertEqual(rc, 0)
        mock_run_input.assert_called_once()
        # Verify input_text passed through
        call_args = mock_run_input.call_args
        self.assertEqual(call_args[0][1], "conf t\nend\n")

    @patch("freq.modules.init_cmd._run")
    def _case_password_file_created_with_correct_permissions(self, mock_run):
        """Tempfile is created with 0o600 permissions."""
        created_files = []

        def capture_run(cmd, **kwargs):
            # cmd[6] is the tempfile path (after timeout -s KILL <N> sshpass -f)
            if len(cmd) > 6 and os.path.isfile(cmd[6]):
                mode = os.stat(cmd[6]).st_mode
                created_files.append((cmd[6], mode))
            return (0, "", "")

        mock_run.side_effect = capture_run
        _ssh_with_pass("mypassword", ["ssh", "user@host", "test"])
        self.assertEqual(len(created_files), 1)
        path, mode = created_files[0]
        self.assertEqual(stat.S_IMODE(mode), 0o600)

    @patch("freq.modules.init_cmd._run")
    def _case_password_file_contains_password(self, mock_run):
        """Tempfile contains the exact password string."""
        contents = []

        def capture_run(cmd, **kwargs):
            # cmd[6] is the tempfile path (after timeout -s KILL <N> sshpass -f)
            if len(cmd) > 6 and os.path.isfile(cmd[6]):
                with open(cmd[6]) as f:
                    contents.append(f.read())
            return (0, "", "")

        mock_run.side_effect = capture_run
        _ssh_with_pass("hunter2", ["ssh", "user@host", "test"])
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0], "hunter2")

    @patch("freq.modules.init_cmd._run")
    def _case_password_file_cleaned_up_after_success(self, mock_run):
        """Tempfile is deleted after successful execution."""
        tempfile_paths = []

        def capture_run(cmd, **kwargs):
            if len(cmd) > 2:
                tempfile_paths.append(cmd[2])
            return (0, "", "")

        mock_run.side_effect = capture_run
        _ssh_with_pass("secret", ["ssh", "user@host", "test"])
        self.assertEqual(len(tempfile_paths), 1)
        self.assertFalse(os.path.exists(tempfile_paths[0]))

    @patch("freq.modules.init_cmd._run")
    def _case_password_file_cleaned_up_on_exception(self, mock_run):
        """Tempfile is deleted even when _run raises."""
        tempfile_paths = []

        def capture_run(cmd, **kwargs):
            if len(cmd) > 6:
                tempfile_paths.append(cmd[6])
            raise RuntimeError("simulated failure")

        mock_run.side_effect = capture_run
        with self.assertRaises(RuntimeError):
            _ssh_with_pass("secret", ["ssh", "user@host", "test"])
        self.assertEqual(len(tempfile_paths), 1)
        self.assertFalse(os.path.exists(tempfile_paths[0]))

    @patch("freq.modules.init_cmd._run")
    def _case_timeout_passed_through(self, mock_run):
        """Custom timeout is forwarded to _run with +10s buffer for GNU timeout."""
        mock_run.return_value = (0, "", "")
        _ssh_with_pass("secret", ["ssh", "host", "cmd"], timeout=60)
        call_kwargs = mock_run.call_args[1]
        # Python-side timeout is caller_timeout + 10 (GNU timeout fires
        # at caller_timeout; Python fallback fires 10s later as belt-and-suspenders)
        self.assertEqual(call_kwargs.get("timeout"), 70)
        # GNU timeout value in the command is the original caller timeout
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[3], "60")


SSH_WITH_PASS_CASES = (
    "_case_calls_run_without_input_text",
    "_case_calls_run_with_input_when_input_text_provided",
    "_case_password_file_created_with_correct_permissions",
    "_case_password_file_contains_password",
    "_case_password_file_cleaned_up_after_success",
    "_case_password_file_cleaned_up_on_exception",
    "_case_timeout_passed_through",
)


class TestSSHWithPassMatrix(unittest.TestCase):
    def test_ssh_with_pass_matrix(self):
        run_case_matrix(self, TestSSHWithPass, SSH_WITH_PASS_CASES)


class TestIdracParsing(unittest.TestCase):
    """Test helpers for live iDRAC RACADM output."""

    def _case_parse_idrac_username_output_handles_real_racadm_format(self):
        from freq.modules.init_cmd import _parse_idrac_username_output

        output = "[Key=iDRAC.Embedded.1#Users.8]\nUserName=\n"
        self.assertEqual(_parse_idrac_username_output(output), "")

        output = "[Key=iDRAC.Embedded.1#Users.8]\nUserName=freq-admin\n"
        self.assertEqual(_parse_idrac_username_output(output), "freq-admin")

    def _case_parse_idrac_slots_treats_null_as_empty(self):
        from freq.modules.init_cmd import _parse_idrac_slots

        slot_dump = "\n".join([
            "SLOT3=root",
            "SLOT4=(NULL)",
            "SLOT5=",
            "SLOT6=freq-admin",
        ])
        target_slot, existing_slot = _parse_idrac_slots(slot_dump, "freq-admin")
        self.assertEqual(target_slot, 4)
        self.assertEqual(existing_slot, 6)

    def _case_query_idrac_slots_prefers_lowest_service_slot_first(self):
        from freq.modules.init_cmd import _query_idrac_slots

        seen = []

        def fake_ssh(cmd, extra_opts=None, timeout=None):
            seen.append(cmd)
            slot = int(cmd.split(".")[2])
            if slot == 3:
                return 0, "[Key=iDRAC.Embedded.1#Users.8]\nUserName=\n", ""
            return 0, f"[Key=iDRAC.Embedded.1#Users.{slot}]\nUserName=occupied\n", ""

        target_slot, existing_slot = _query_idrac_slots(fake_ssh, [], "freq-admin")
        self.assertEqual(target_slot, 3)
        self.assertIsNone(existing_slot)
        self.assertEqual(seen[0], "racadm get iDRAC.Users.3.UserName")

    def _case_query_idrac_slots_can_stop_at_first_empty_for_deploy(self):
        from freq.modules.init_cmd import _query_idrac_slots

        seen = []

        def fake_ssh(cmd, extra_opts=None, timeout=None):
            seen.append(cmd)
            slot = int(cmd.split(".")[2])
            if slot == 3:
                return 0, "[Key=iDRAC.Embedded.1#Users.3]\nUserName=\n", ""
            return 0, f"[Key=iDRAC.Embedded.1#Users.{slot}]\nUserName=freq-admin\n", ""

        target_slot, existing_slot = _query_idrac_slots(fake_ssh, [], "freq-admin", stop_at_empty=True)
        self.assertEqual(target_slot, 3)
        self.assertIsNone(existing_slot)
        self.assertEqual(len(seen), 1)

    def _case_idrac_slot_query_timeout_matches_real_bmc_latency(self):
        from freq.modules.init_cmd import IDRAC_SLOT_QUERY_TIMEOUT

        self.assertGreaterEqual(IDRAC_SLOT_QUERY_TIMEOUT, 15)

    def _case_idrac_command_failure_includes_command_context(self):
        from freq.modules.init_cmd import _run_idrac_command

        def fake_ssh(cmd, extra_opts=None, timeout=None):
            return 255, "", "Permission denied (publickey,password)."

        ok, details = _run_idrac_command(
            fake_ssh,
            [],
            "racadm set iDRAC.Users.8.Privilege 0x1ff",
        )

        self.assertFalse(ok)
        self.assertIn("iDRAC.Users.8.Privilege", details)
        self.assertIn("Permission denied", details)

    @patch("freq.modules.init_cmd.time.sleep")
    def _case_idrac_command_retries_transient_auth_failure(self, mock_sleep):
        from freq.modules.init_cmd import _run_idrac_command

        calls = []

        def flaky_ssh(cmd, extra_opts=None, timeout=None):
            calls.append(cmd)
            if len(calls) == 1:
                return 255, "", "Permission denied (publickey,password)."
            return 0, "Object value modified successfully", ""

        ok, details = _run_idrac_command(
            flaky_ssh,
            [],
            "racadm set iDRAC.Users.8.Privilege 0x1ff",
        )

        self.assertTrue(ok)
        self.assertIn("modified successfully", details)
        self.assertEqual(len(calls), 2)
        mock_sleep.assert_called_once_with(5)

    @patch("freq.modules.init_cmd._run_with_input")
    def _case_init_ssh_pipes_sensitive_input_without_ssh_n(self, mock_run_with_input):
        from freq.modules.init_cmd import _init_ssh

        mock_run_with_input.return_value = (0, "", "")
        ssh = _init_ssh("10.25.255.10", "", "/tmp/fleet_key", "freq-ops")
        ssh("read -r secret; echo OK", input_text="secret-value\n")

        cmd = mock_run_with_input.call_args[0][0]
        self.assertNotIn("-n", cmd)
        self.assertNotIn("secret-value", " ".join(cmd))
        self.assertEqual(mock_run_with_input.call_args[0][1], "secret-value\n")

    @patch("freq.modules.init_cmd.audit")
    @patch("freq.modules.init_cmd.logger")
    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.init_cmd._run_idrac_interactive_command")
    @patch("freq.modules.init_cmd._query_idrac_slots")
    @patch("freq.modules.init_cmd._init_ssh")
    def _case_idrac_password_is_piped_not_embedded_in_command_line(
        self,
        mock_init_ssh,
        mock_query_slots,
        mock_interactive,
        mock_fmt,
        _logger,
        _audit,
    ):
        from freq.modules.init_cmd import _deploy_idrac

        secret = "SvcPass-Not-On-Command"
        calls = []

        def fake_ssh(cmd, extra_opts=None, timeout=None, as_root=False, input_text=None):
            calls.append({"cmd": cmd, "input_text": input_text})
            if "iDRAC.Users.8.Enable" in cmd and " get " in f" {cmd} ":
                return 0, "[Key=iDRAC.Embedded.1#Users.8]\nEnable=Enabled\n", ""
            if "sshpkauth -v" in cmd:
                return 0, "Key 1 : ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQ test", ""
            return 0, "Object value modified successfully", ""

        mock_query_slots.return_value = (8, None)
        mock_init_ssh.return_value = fake_ssh
        mock_interactive.return_value = (True, "Object value modified successfully")

        ok = _deploy_idrac(
            "10.25.255.10",
            {
                "svc_name": "dc01-admin",
                "svc_pass": secret,
                "rsa_pubkey": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQ test",
            },
            "bootstrap-pass",
            "",
            "freq-ops",
        )

        self.assertTrue(ok)
        command_text = "\n".join(c["cmd"] for c in calls)
        self.assertNotIn(secret, command_text)
        interactive_args = mock_interactive.call_args_list[0][0]
        self.assertEqual(interactive_args[5], f"racadm set iDRAC.Users.8.Password {secret}")
        self.assertEqual(mock_interactive.call_args_list[0][1]["redact"], secret)

    def _case_deploy_idrac_verifies_enable_and_current_rsa_key(self):
        """iDRAC deploy must reject disabled users or stale stored keys."""
        with open(os.path.join(Path(__file__).parent.parent, "freq/modules/init_cmd.py")) as f:
            src = f.read()
        block = src.split("def _deploy_idrac(", 1)[1].split("\ndef _deploy_switch", 1)[0]

        self.assertIn("racadm get iDRAC.Users.{target_slot}.Enable", block)
        self.assertIn("iDRAC user remains disabled after Enable=1", block)
        self.assertIn("rsa_key_material = rsa_pubkey.split()[1]", block)
        self.assertIn("rsa_key_material not in verify_text", block)
        self.assertIn("RSA key upload did not verify against current FREQ key", block)

    @patch("freq.modules.init_cmd._ssh_with_pass")
    def _case_idrac_interactive_command_redacts_echoed_secret(self, mock_ssh_with_pass):
        from freq.modules.init_cmd import _run_idrac_interactive_command

        secret = "SvcPass-Not-In-Logs"
        mock_ssh_with_pass.return_value = (
            255,
            f"/admin1-> racadm set iDRAC.Users.8.Password {secret}\nObject value modified successfully\n/admin1-> exit\n",
            "CLP Session terminated",
        )

        ok, details = _run_idrac_interactive_command(
            "10.25.255.10",
            "bootstrap-pass",
            "",
            "freq-ops",
            ["-o", "KexAlgorithms=+diffie-hellman-group14-sha1"],
            f"racadm set iDRAC.Users.8.Password {secret}",
            redact=secret,
        )

        self.assertTrue(ok)
        self.assertNotIn(secret, details)
        self.assertIn("<redacted>", details)
        cmd = mock_ssh_with_pass.call_args[0][1]
        self.assertNotIn(secret, " ".join(cmd))
        self.assertIn(secret, mock_ssh_with_pass.call_args[1]["input_text"])


IDRAC_PARSING_CASES = (
    "_case_parse_idrac_username_output_handles_real_racadm_format",
    "_case_parse_idrac_slots_treats_null_as_empty",
    "_case_query_idrac_slots_prefers_lowest_service_slot_first",
    "_case_query_idrac_slots_can_stop_at_first_empty_for_deploy",
    "_case_idrac_slot_query_timeout_matches_real_bmc_latency",
    "_case_idrac_command_failure_includes_command_context",
    "_case_idrac_command_retries_transient_auth_failure",
    "_case_init_ssh_pipes_sensitive_input_without_ssh_n",
    "_case_idrac_password_is_piped_not_embedded_in_command_line",
    "_case_deploy_idrac_verifies_enable_and_current_rsa_key",
    "_case_idrac_interactive_command_redacts_echoed_secret",
)


class TestIdracParsingMatrix(unittest.TestCase):
    def test_idrac_parsing_matrix(self):
        run_case_matrix(self, TestIdracParsing, IDRAC_PARSING_CASES)


class TestHeadlessFleetDeployTruth(unittest.TestCase):
    @patch("freq.modules.init_cmd._run")
    def _case_init_ssh_uses_noninteractive_sudo_for_privileged_bootstrap(self, mock_run):
        from freq.modules.init_cmd import _init_ssh

        mock_run.return_value = (0, "", "")
        ssh = _init_ssh("10.0.0.1", "", "/tmp/bootstrap-key", "freq-ops")
        ssh("id", as_root=True)

        cmd = mock_run.call_args[0][0]
        self.assertIn("sudo -n sh", cmd[-1])

    @patch("freq.modules.init_cmd.audit")
    @patch("freq.modules.init_cmd.logger")
    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.init_cmd._init_ssh")
    def _case_truenas_deploy_uses_storage_timeout_and_reports_timeout(self, mock_init_ssh, mock_fmt, _logger, _audit):
        from freq.modules.init_cmd import TRUENAS_DEPLOY_TIMEOUT, _deploy_linux

        calls = []

        def fake_ssh(cmd, extra_opts=None, timeout=None, as_root=False):
            calls.append({"cmd": cmd, "timeout": timeout, "as_root": as_root})
            if cmd == "echo OK":
                return 0, "OK\n", ""
            return 124, "", f"command timed out after {timeout}s"

        mock_init_ssh.return_value = fake_ssh
        ok = _deploy_linux(
            "10.25.10.201",
            {"svc_name": "dc01-admin", "svc_pass": "secret", "pubkey": "ssh-ed25519 AAA test"},
            "",
            "/tmp/fleet_key",
            "freq-ops",
            htype="truenas",
        )

        self.assertFalse(ok)
        self.assertEqual(calls[1]["timeout"], TRUENAS_DEPLOY_TIMEOUT)
        messages = " ".join(str(c.args[0]) for c in mock_fmt.step_fail.call_args_list)
        self.assertIn("TrueNAS deploy script timed out", messages)

    @patch("freq.modules.init_cmd.fmt")
    def _case_truenas_target_api_only_credentials_fail_preflight(self, mock_fmt):
        from freq.modules.init_cmd import _validate_truenas_deployment_credentials

        ok = _validate_truenas_deployment_credentials({
            "truenas": {"api_key": "tn-secret", "api_key_only": True, "host": "10.25.255.25"},
            "truenas-lab": {"api_key": "tn-lab-secret", "api_key_only": True, "host": "10.25.10.201"},
        })

        self.assertFalse(ok)
        messages = " ".join(str(c.args[0]) for c in mock_fmt.step_fail.call_args_list)
        self.assertIn("TrueNAS target [truenas] has host(s) but only API credentials", messages)
        self.assertIn("TrueNAS target [truenas-lab] has host(s) but only API credentials", messages)

    @patch("freq.modules.init_cmd.fmt")
    def _case_truenas_target_with_ssh_credentials_passes_preflight(self, mock_fmt):
        from freq.modules.init_cmd import _validate_truenas_deployment_credentials

        ok = _validate_truenas_deployment_credentials({
            "truenas": {"user": "root", "password": "secret", "host": "10.25.255.25"},
            "truenas-lab": {"user": "root", "key_path": "/tmp/fleet_key", "host": "10.25.10.201"},
        })

        self.assertTrue(ok)
        mock_fmt.step_fail.assert_not_called()

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.fmt")
    def _case_truenas_probe_uses_resolved_device_credentials(self, mock_fmt, mock_run, mock_dispatch):
        from freq.modules.init_cmd import _headless_fleet_deploy

        cfg = types.SimpleNamespace(
            pve_nodes=[],
            pve_node_names=[],
            hosts=[types.SimpleNamespace(ip="10.0.0.25", label="nexus", htype="truenas")],
            ssh_service_account="freq-admin",
        )
        ctx = {"svc_name": "freq-admin", "svc_pass": "SvcPass2026!"}
        mock_run.return_value = (0, "OK", "")
        mock_dispatch.return_value = True

        _headless_fleet_deploy(
            cfg,
            ctx,
            bootstrap_key="/home/freq-ops/.ssh/fleet_key",
            bootstrap_user="freq-ops",
            bootstrap_pass="",
            device_creds={"truenas": {"user": "root", "password": "changeme1234"}},
            pve_only=False,
        )

        ssh_check = mock_run.call_args_list[0][0][0]
        self.assertIn("root@10.0.0.25", ssh_check)
        self.assertIn("sshpass", ssh_check)

        dispatch_args = mock_dispatch.call_args[0]
        self.assertEqual(dispatch_args[3], "changeme1234")
        self.assertEqual(dispatch_args[4], "")
        self.assertEqual(dispatch_args[5], "root")

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.fmt")
    def _case_core_truenas_api_only_credentials_do_not_fallback_to_bootstrap(self, mock_fmt, mock_run, mock_dispatch):
        from freq.modules.init_cmd import _headless_fleet_deploy

        cfg = types.SimpleNamespace(
            pve_nodes=[],
            pve_node_names=[],
            hosts=[types.SimpleNamespace(ip="10.0.0.25", label="truenas", htype="truenas")],
            ssh_service_account="freq-admin",
        )
        ctx = {"svc_name": "freq-admin", "svc_pass": "SvcPass2026!"}

        _headless_fleet_deploy(
            cfg,
            ctx,
            bootstrap_key="/home/freq-ops/.ssh/fleet_key",
            bootstrap_user="freq-ops",
            bootstrap_pass="",
            device_creds={"truenas": {"api_key": "tn-secret", "api_key_only": True, "host": "10.0.0.25"}},
            pve_only=False,
        )

        mock_run.assert_not_called()
        mock_dispatch.assert_not_called()
        fail_messages = " ".join(str(c.args[0]) for c in mock_fmt.step_fail.call_args_list)
        self.assertIn("TrueNAS 'truenas' has API credentials only", fail_messages)
        self.assertIn("ssh_key_file", fail_messages)

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.fmt")
    def _case_named_truenas_api_only_credentials_fail_deploy(self, mock_fmt, mock_run, mock_dispatch):
        from freq.modules.init_cmd import _headless_fleet_deploy

        cfg = types.SimpleNamespace(
            pve_nodes=[],
            pve_node_names=[],
            hosts=[types.SimpleNamespace(ip="10.25.10.201", label="truenas-lab", htype="truenas")],
            ssh_service_account="freq-admin",
        )
        ctx = {"svc_name": "freq-admin", "svc_pass": "SvcPass2026!"}

        _headless_fleet_deploy(
            cfg,
            ctx,
            bootstrap_key="/home/freq-ops/.ssh/fleet_key",
            bootstrap_user="freq-ops",
            bootstrap_pass="",
            device_creds={"truenas-lab": {"api_key": "tn-lab-secret", "api_key_only": True, "host": "10.25.10.201"}},
            pve_only=False,
        )

        mock_run.assert_not_called()
        mock_dispatch.assert_not_called()
        self.assertEqual(ctx.get("fleet_deploy_failures"), 1)
        self.assertEqual(ctx.get("fleet_deploy_failed_ips"), {"10.25.10.201"})
        fail_messages = " ".join(str(c.args[0]) for c in mock_fmt.step_fail.call_args_list)
        self.assertIn("TrueNAS 'truenas-lab' has API credentials only", fail_messages)

    def _case_phase12_reconciles_transient_deploy_failure_by_host_verification(self):
        """Final verification, not stale Phase 8 count, decides init success."""
        src = Path("freq/modules/init_cmd.py").read_text()
        self.assertIn("deploy_failed_verified_ips", src)
        self.assertIn("fleet_deploy_recovered_failed_ips", src)
        self.assertIn("0 unresolved failed hosts", src)
        self.assertIn("if h.ip in deploy_failed_ips:", src)
        self.assertIn("deploy_failed_ips - deploy_failed_verified_ips", src)

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.fmt")
    def _case_named_truenas_uses_matching_ssh_credentials(self, mock_fmt, mock_run, mock_dispatch):
        from freq.modules.init_cmd import _headless_fleet_deploy

        cfg = types.SimpleNamespace(
            pve_nodes=[],
            pve_node_names=[],
            hosts=[types.SimpleNamespace(ip="10.25.10.201", label="truenas-lab", htype="truenas")],
            ssh_service_account="freq-admin",
        )
        ctx = {"svc_name": "freq-admin", "svc_pass": "SvcPass2026!"}
        mock_run.return_value = (0, "OK", "")
        mock_dispatch.return_value = True

        _headless_fleet_deploy(
            cfg,
            ctx,
            bootstrap_key="/home/freq-ops/.ssh/fleet_key",
            bootstrap_user="freq-ops",
            bootstrap_pass="",
            device_creds={"truenas-lab": {"user": "root", "password": "labpass", "host": "10.25.10.201"}},
            pve_only=False,
        )

        ssh_check = mock_run.call_args_list[0][0][0]
        self.assertIn("root@10.25.10.201", ssh_check)
        self.assertIn("sshpass", ssh_check)
        dispatch_args = mock_dispatch.call_args[0]
        self.assertEqual(dispatch_args[3], "labpass")
        self.assertEqual(dispatch_args[5], "root")

    @patch("freq.modules.init_cmd._persist_legacy_password_file")
    @patch("freq.modules.init_cmd._deploy_to_host_dispatch", return_value=True)
    @patch("freq.modules.init_cmd.fmt")
    def _case_legacy_devices_use_bootstrap_password_when_no_device_creds(
        self, _mock_fmt, mock_dispatch, mock_persist
    ):
        from freq.modules.init_cmd import _headless_fleet_deploy

        cfg = types.SimpleNamespace(
            pve_nodes=[],
            pve_node_names=[],
            hosts=[
                types.SimpleNamespace(ip="10.25.255.10", label="bmc-10", htype="idrac"),
                types.SimpleNamespace(ip="10.25.255.5", label="switch", htype="switch"),
            ],
            ssh_service_account="freq-admin",
        )
        ctx = {"svc_name": "freq-admin", "svc_pass": "SvcPass2026!"}

        _headless_fleet_deploy(
            cfg,
            ctx,
            bootstrap_key="",
            bootstrap_user="freq-ops",
            bootstrap_pass="BootstrapPass2026!",
            device_creds={},
            pve_only=False,
        )

        calls = [call.args for call in mock_dispatch.call_args_list]
        self.assertEqual(len(calls), 2)
        for args in calls:
            self.assertEqual(args[3], "BootstrapPass2026!")
            self.assertEqual(args[4], "")
            self.assertEqual(args[5], "freq-ops")
        mock_persist.assert_called_once_with(cfg, "freq-admin", "SvcPass2026!")

    @patch("freq.modules.init_cmd._persist_legacy_password_file")
    @patch("freq.modules.init_cmd._deploy_to_host_dispatch", return_value=True)
    @patch("freq.modules.init_cmd._run", return_value=(0, "OK", ""))
    @patch("freq.modules.init_cmd.fmt")
    def _case_legacy_password_not_persisted_when_only_linux_deployed(
        self, _mock_fmt, _mock_run, _mock_dispatch, mock_persist
    ):
        from freq.modules.init_cmd import _headless_fleet_deploy

        cfg = types.SimpleNamespace(
            pve_nodes=[],
            pve_node_names=[],
            hosts=[types.SimpleNamespace(ip="10.25.255.40", label="pdm-manager", htype="linux")],
            ssh_service_account="freq-admin",
        )
        ctx = {"svc_name": "freq-admin", "svc_pass": "SvcPass2026!"}

        _headless_fleet_deploy(
            cfg,
            ctx,
            bootstrap_key="",
            bootstrap_user="freq-ops",
            bootstrap_pass="BootstrapPass2026!",
            device_creds={},
            pve_only=False,
        )

        mock_persist.assert_not_called()

    @patch("freq.modules.init_cmd._chown", return_value=True)
    @patch("freq.modules.init_cmd.fmt")
    def _case_legacy_password_persist_uses_credentials_dir(self, _mock_fmt, _mock_chown):
        from freq.modules.init_cmd import _persist_legacy_password_file

        with tempfile.TemporaryDirectory() as td:
            conf_dir = os.path.join(td, "conf")
            os.makedirs(conf_dir)
            Path(conf_dir, "freq.toml").write_text("[ssh]\nlegacy_password_file = \"\"\n")
            cfg = types.SimpleNamespace(conf_dir=conf_dir, credentials_dir=os.path.join(td, "credentials"))

            _persist_legacy_password_file(cfg, "freq-admin", "SvcPass2026!")

            self.assertEqual(
                cfg.legacy_password_file,
                os.path.join(td, "credentials", "freq-admin-legacy-device-pass"),
            )
            self.assertEqual(Path(cfg.legacy_password_file).read_text(), "SvcPass2026!")
            self.assertIn(cfg.legacy_password_file, Path(conf_dir, "freq.toml").read_text())


HEADLESS_FLEET_DEPLOY_CASES = (
    "_case_init_ssh_uses_noninteractive_sudo_for_privileged_bootstrap",
    "_case_truenas_deploy_uses_storage_timeout_and_reports_timeout",
    "_case_truenas_target_api_only_credentials_fail_preflight",
    "_case_truenas_target_with_ssh_credentials_passes_preflight",
    "_case_truenas_probe_uses_resolved_device_credentials",
    "_case_core_truenas_api_only_credentials_do_not_fallback_to_bootstrap",
    "_case_named_truenas_api_only_credentials_fail_deploy",
    "_case_phase12_reconciles_transient_deploy_failure_by_host_verification",
    "_case_named_truenas_uses_matching_ssh_credentials",
    "_case_legacy_devices_use_bootstrap_password_when_no_device_creds",
    "_case_legacy_password_not_persisted_when_only_linux_deployed",
    "_case_legacy_password_persist_uses_credentials_dir",
)


class TestHeadlessFleetDeployTruthMatrix(unittest.TestCase):
    def test_headless_fleet_deploy_matrix(self):
        run_case_matrix(self, TestHeadlessFleetDeployTruth, HEADLESS_FLEET_DEPLOY_CASES)


# ═══════════════════════════════════════════════════════════════════
# _load_device_credentials() tests
# ═══════════════════════════════════════════════════════════════════

class TestLoadDeviceCredentials(unittest.TestCase):
    """Test per-device TOML credential loading.

    Function under test: _load_device_credentials(cred_file) -> dict
    Expected return: {"device_type": {"user": "...", "password": "actual_pass"}, ...}
    """

    def setUp(self):
        """Create temp directory for test TOML + password files."""
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-creds-")

    def tearDown(self):
        """Clean up temp files."""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_file(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def _load(self, cred_file):
        """Import and call _load_device_credentials."""
        from freq.modules.init_cmd import _load_device_credentials
        return _load_device_credentials(cred_file)

    def test_load_device_credentials_input_and_secret_matrix(self):
        """One exact matrix owns accepted files, secret sources, and omissions."""
        password_path = self._write_file("switch-password", "file-secret\n\n")
        key_path = self._write_file("fleet-key", "not-a-real-key")
        missing_path = os.path.join(self.tmpdir, "missing-secret")

        documents = {
            "empty": "",
            "unknown-section": """
[metadata]
user = "ghost"
password = "must-not-load"
""",
            "missing-secret": """
[switch]
user = "operator"
""",
            "unreadable-file-without-inline": f"""
[idrac]
user = "root"
password_file = "{missing_path}"
""",
            "default-root": """
[pfsense]
password = "default-root-secret"
""",
            "secret-sources": f"""
[pfsense]
user = "root"
password = "inline-secret"

[switch]
user = "operator"
password_file = "{password_path}"
password = "must-lose"

[idrac]
user = "root"
password_file = "{missing_path}"
password = "fallback-secret"
""",
            "ssh-key": f"""
[pfsense]
username = "freq-ops"
ssh_key_file = "{key_path}"
""",
        }
        paths = {
            name: self._write_file(f"{name}.toml", content)
            for name, content in documents.items()
        }
        expected = {
            "empty": {},
            "unknown-section": {},
            "missing-secret": {},
            "default-root": {
                "pfsense": {"user": "root", "password": "default-root-secret"},
            },
            "ssh-key": {
                "pfsense": {"user": "freq-ops", "password": "", "key_path": key_path},
            },
        }

        with patch("freq.modules.init_cmd.fmt"):
            for name, expected_result in expected.items():
                with self.subTest(name=name):
                    self.assertEqual(self._load(paths[name]), expected_result)
            with self.subTest(name="none"):
                self.assertEqual(self._load(None), {})
            with self.subTest(name="missing-file"), self.assertRaisesRegex(
                ValueError, "/freq-init-inputs/<relative-path>"
            ):
                self._load(os.path.join(self.tmpdir, "missing.toml"))
            for name in ("unreadable-file-without-inline", "secret-sources"):
                with self.subTest(loud_missing_file_value=name), self.assertRaisesRegex(
                    ValueError, "/freq-init-inputs/<relative-path>"
                ):
                    self._load(paths[name])

        malformed = self._write_file("malformed.toml", '[switch\npassword = "bad"\n')
        self.assertEqual(self._load(malformed), {})

    def test_load_device_credentials_section_priority_and_metadata(self):
        """Section priority, typed metadata, migration, and both consumers agree."""
        from freq.core.device_credentials import load_device_credentials_toml
        from freq.modules.init_cmd import _upsert_toml_section
        from freq.modules.serve import _write_setup_device_credentials

        priority_documents = {
            "vendor-beats-category-and-legacy": """
[firewall:pfsense]
username = "vendor-user"
password = "vendor-secret"

[firewall]
username = "category-user"
password = "category-secret"

[pfsense]
user = "legacy-user"
password = "legacy-secret"
""",
            "category-beats-legacy": """
[firewall]
username = "category-user"
password = "category-secret"

[pfsense]
user = "legacy-user"
password = "legacy-secret"
""",
            "legacy-only": """
[pfsense]
user = "legacy-user"
password = "legacy-secret"
""",
            "category-default-root": """
[firewall]
password = "category-secret"
""",
        }
        expected_priority = {
            "vendor-beats-category-and-legacy": ("vendor-user", "vendor-secret"),
            "category-beats-legacy": ("category-user", "category-secret"),
            "legacy-only": ("legacy-user", "legacy-secret"),
            "category-default-root": ("root", "category-secret"),
        }
        with patch("freq.modules.init_cmd.fmt"):
            for name, body in priority_documents.items():
                with self.subTest(priority=name):
                    path = self._write_file(f"priority-{name}.toml", body)
                    result = self._load(path)
                    self.assertEqual(
                        (result["pfsense"]["user"], result["pfsense"]["password"]),
                        expected_priority[name],
                    )

        mixed_path = self._write_file(
            "mixed-sections.toml",
            """
[switch:cisco]
username = "switch-user"
password = "switch-secret"

[pfsense]
user = "firewall-user"
password = "firewall-secret"

[idrac]
user = "bmc-user"
password = "bmc-secret"

[truenas]
type = "truenas"
url = "https://10.0.0.20/api/v2.0"
api_key = "generic-key"

[truenas-lab]
type = "truenas"
url = "https://10.0.0.21/api/v2.0"
hosts = ["10.0.0.21", "10.0.0.22"]
label = "lab-storage"
groups = "storage,lab"
scope = "lab"
api_key = "lab-key"

[truenas-prod]
type = "truenas"
host = "10.0.0.30"
url = "https://10.0.0.31/api/v2.0"
api_key = "prod-key"

[metadata]
type = "unknown"
password = "ignored"
""",
        )
        raw = load_device_credentials_toml(mixed_path)
        self.assertEqual(raw["truenas-lab"]["hosts"], ["10.0.0.21", "10.0.0.22"])
        with patch("freq.modules.init_cmd.fmt"):
            loaded = self._load(mixed_path)
        self.assertEqual(
            {name: loaded[name]["password"] for name in ("pfsense", "switch", "idrac")},
            {
                "pfsense": "firewall-secret",
                "switch": "switch-secret",
                "idrac": "bmc-secret",
            },
        )
        self.assertEqual(loaded["truenas"]["host"], "10.0.0.20")
        self.assertNotIn("type", loaded["truenas"])
        self.assertEqual(
            loaded["truenas-lab"],
            {
                "user": "root",
                "password": "",
                "label": "lab-storage",
                "groups": "storage,lab",
                "scope": "lab",
                "url": "https://10.0.0.21/api/v2.0",
                "host": "10.0.0.21",
                "hosts": ["10.0.0.21", "10.0.0.22"],
                "api_key": "lab-key",
                "api_key_only": True,
                "type": "truenas",
            },
        )
        self.assertEqual(loaded["truenas-prod"]["host"], "10.0.0.30")
        self.assertNotEqual(loaded["truenas-prod"]["host"], "10.0.0.31")
        self.assertNotIn("metadata", loaded)

        migrated_path = self._write_file(
            "migrated-writer.toml",
            """
[firewall:pfsense]
username = "old-user"
password = "old-secret"

[truenas]
api_key = "preserved"
""",
        )
        _upsert_toml_section(
            migrated_path,
            "firewall:pfsense",
            {"username": "new-user", "password": "new-secret"},
        )
        _upsert_toml_section(
            migrated_path,
            "firewall:pfsense",
            {"username": "final-user", "password": "final-secret"},
        )
        migrated_text = Path(migrated_path).read_text()
        self.assertEqual(migrated_text.count('["firewall:pfsense"]'), 1)
        self.assertNotIn("[firewall:pfsense]", migrated_text)
        self.assertIn("[truenas]", migrated_text)
        self.assertEqual(
            load_device_credentials_toml(migrated_path)["firewall:pfsense"],
            {"username": "final-user", "password": "final-secret"},
        )

        single_quoted_path = self._write_file(
            "single-quoted-writer.toml",
            """
['switch:cisco']
username = "old-switch"
password = "old-secret"

[service_account]
username = "preserved"
""",
        )
        _upsert_toml_section(
            single_quoted_path,
            "switch:cisco",
            {"username": "new-switch", "password": "new-secret"},
        )
        single_quoted_text = Path(single_quoted_path).read_text()
        self.assertEqual(single_quoted_text.count('["switch:cisco"]'), 1)
        self.assertNotIn("['switch:cisco']", single_quoted_text)
        self.assertIn("[service_account]", single_quoted_text)
        self.assertEqual(
            load_device_credentials_toml(single_quoted_path)["switch:cisco"],
            {"username": "new-switch", "password": "new-secret"},
        )

        with tempfile.TemporaryDirectory(prefix="freq-web-device-creds-") as secret_dir:
            web_path = _write_setup_device_credentials(
                secret_dir,
                {
                    "firewall:pfsense": {
                        "username": "web-user",
                        "password": "web-secret",
                        "hosts": ["10.0.0.40", "10.0.0.41"],
                    }
                },
            )
            web_text = Path(web_path).read_text()
            self.assertIn('["firewall:pfsense"]', web_text)
            self.assertNotIn("[firewall:pfsense]", web_text)
            self.assertEqual(
                load_device_credentials_toml(web_path)["firewall:pfsense"]["hosts"],
                ["10.0.0.40", "10.0.0.41"],
            )
            with patch("freq.modules.init_cmd.fmt"):
                web_loaded = self._load(web_path)
            self.assertEqual(web_loaded["pfsense"]["user"], "web-user")
            self.assertEqual(web_loaded["pfsense"]["password"], "web-secret")

    def test_load_device_credentials_container_path_aliases(self):
        """F3-1: one legacy mapper, portable container paths, loud failures."""
        import inspect

        from freq.core.setup_paths import legacy_init_input_candidate
        from freq.modules import init_cmd
        from freq.services import setup_inputs

        cred_file = "/root/freq-init-inputs/device-credentials.run.toml"
        cred_alias = "/freq-init-inputs/device-credentials.run.toml"
        switch_pass_alias = "/freq-init-inputs/switch-password"
        container_key = "/freq-init-inputs/fleet-key"
        files = {
            cred_alias: f"""
[switch:cisco]
user = "gigecolo"
password_file = "{switch_pass_alias}"

[firewall:pfsense]
user = "root"
ssh_key_file = "{container_key}"
""",
            switch_pass_alias: "switch-secret\n",
            container_key: "not-a-real-key\n",
        }

        def fake_isfile(path):
            return path in files

        def fake_open(path, *args, **kwargs):
            if path not in files:
                raise FileNotFoundError(path)
            return unittest.mock.mock_open(read_data=files[path]).return_value

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("freq.modules.init_cmd.os.path.isfile", side_effect=fake_isfile),
            patch("builtins.open", side_effect=fake_open),
            patch("freq.modules.init_cmd.fmt"),
        ):
            result = self._load(cred_file)

        self.assertEqual(result["switch"]["password"], "switch-secret")
        self.assertEqual(result["pfsense"]["key_path"], container_key)

        self.assertEqual(
            legacy_init_input_candidate("/root/freq-init-inputs/nested/key"),
            "/freq-init-inputs/nested/key",
        )
        for rejected in (
            "/root/freq-init-inputs-sibling/key",
            "/root/freq-init-inputs/../escape",
            "/custom/host-inputs/key",
            "/home/" + "freq" + "-ops/.ssh/key",
        ):
            with self.subTest(rejected_mapping=rejected):
                self.assertEqual(legacy_init_input_candidate(rejected), "")

        missing_documents = {
            "custom-host-source": "/custom/host-inputs/fleet-key",
            "old-home-source": "/home/" + "freq" + "-ops/.ssh/fleet-key",
            "unresolved-container": "/freq-init-inputs/missing-key",
        }
        for name, missing_key in missing_documents.items():
            missing_toml = os.path.join(self.tmpdir, f"{name}.toml")
            with open(missing_toml, "w") as handle:
                handle.write(
                    "[firewall:pfsense]\nuser = \"root\"\n"
                    f"ssh_key_file = \"{missing_key}\"\n"
                )
            with self.subTest(loud_failure=name), patch(
                "freq.modules.init_cmd.os.path.isfile",
                side_effect=lambda path, toml=missing_toml: path == toml,
            ), self.assertRaisesRegex(ValueError, "/freq-init-inputs/<relative-path>"):
                self._load(missing_toml)

        py_sources = {
            path.relative_to(Path(__file__).parents[1]).as_posix(): path.read_text()
            for path in (Path(__file__).parents[1] / "freq").rglob("*.py")
        }
        prefix = "/root/" + "freq-init-inputs"
        owners = [name for name, source in py_sources.items() if prefix in source]
        self.assertEqual(owners, ["freq/core/setup_paths.py"])
        self.assertIn("legacy_init_input_candidate", inspect.getsource(setup_inputs))
        self.assertIn("legacy_init_input_candidate", inspect.getsource(init_cmd))

        taught_host_paths = []
        teach_roots = (
            Path(__file__).parents[1] / "docs",
            Path(__file__).parents[1] / "freq" / "data",
        )
        for root in teach_roots:
            for path in root.rglob("*"):
                if path.is_file() and prefix in path.read_text(errors="ignore"):
                    taught_host_paths.append(path.relative_to(Path(__file__).parents[1]).as_posix())
        compose = (Path(__file__).parents[1] / "docker-compose.yml").read_text()
        self.assertNotIn("reference the same absolute paths from the setup UI", compose)
        self.assertEqual(taught_host_paths, [])

    def test_custom_host_staging_dir_still_uses_container_toml_path(self):
        """F3-1: host staging configuration never becomes a TOML path contract."""
        container_toml = "/freq-init-inputs/custom-device-credentials.toml"
        container_key = "/freq-init-inputs/custom-fleet-key"
        files = {
            container_toml: (
                '[firewall:pfsense]\nuser = "root"\n'
                f'ssh_key_file = "{container_key}"\n'
            ),
            container_key: "runner-visible-key\n",
        }

        def fake_open(path, *args, **kwargs):
            if path not in files:
                raise FileNotFoundError(path)
            return unittest.mock.mock_open(read_data=files[path]).return_value

        with (
            patch.dict(os.environ, {"FREQ_INIT_INPUTS_DIR": "/srv/operator-staging"}, clear=True),
            patch("freq.modules.init_cmd.os.path.isfile", side_effect=lambda path: path in files),
            patch("builtins.open", side_effect=fake_open),
            patch("freq.modules.init_cmd.fmt"),
        ):
            loaded = self._load(container_toml)
        self.assertEqual(loaded["pfsense"]["key_path"], container_key)

    def test_custom_host_staging_spelling_fails_during_credential_load(self):
        """F3-1: an unresolved host-side spelling cannot silently survive load."""
        missing_key = "/srv/operator-staging/fleet-key"
        missing_toml = os.path.join(self.tmpdir, "custom-host-spelling.toml")
        with open(missing_toml, "w") as handle:
            handle.write(
                '[firewall:pfsense]\nuser = "root"\n'
                f'ssh_key_file = "{missing_key}"\n'
            )
        with (
            patch.dict(os.environ, {"FREQ_INIT_INPUTS_DIR": "/srv/operator-staging"}, clear=True),
            patch(
                "freq.modules.init_cmd.os.path.isfile",
                side_effect=lambda path: path == missing_toml,
            ),
            patch("freq.modules.init_cmd.fmt"),
            self.assertRaisesRegex(ValueError, "/freq-init-inputs/<relative-path>"),
        ):
            self._load(missing_toml)

    def test_legacy_mapper_has_one_definition_and_exactly_two_consumers(self):
        """F3-1: translation policy has one pure owner and no third caller."""
        import ast

        repo = Path(__file__).parents[1]
        mapper_path = repo / "freq/core/setup_paths.py"
        self.assertTrue(mapper_path.is_file(), "shared setup-path owner is missing")
        definitions = []
        calls = []
        for path in (repo / "freq").rglob("*.py"):
            rel = path.relative_to(repo).as_posix()
            tree = ast.parse(path.read_text())
            definitions.extend(
                rel
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "legacy_init_input_candidate"
            )
            calls.extend(
                rel
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "legacy_init_input_candidate"
                )
            )
        self.assertEqual(definitions, ["freq/core/setup_paths.py"])
        self.assertEqual(
            sorted(calls),
            ["freq/modules/init_cmd.py", "freq/services/setup_inputs.py"],
        )

        host_prefix = "/root/" + "freq-init-inputs"
        prefix_owners = [
            path.relative_to(repo).as_posix()
            for path in (repo / "freq").rglob("*.py")
            if host_prefix in path.read_text()
        ]
        self.assertEqual(prefix_owners, ["freq/core/setup_paths.py"])

    def test_setup_input_consumer_retains_permission_probe_and_labelled_error(self):
        """F3-1: the pure mapper does not absorb setup's permission policy."""
        import inspect
        from freq.services.setup_inputs import resolve_existing_secret_file

        source = inspect.getsource(resolve_existing_secret_file)
        self.assertIn("legacy_init_input_candidate", source)
        self.assertIn('["sudo", "-n", "test", "-f", candidate]', source)
        self.assertIn('raise ValueError(f"{label} file not found:', source)

    def test_unresolved_nested_file_value_fails_before_credential_return(self):
        """F3-1: init's caller owns a loud boundary distinct from mapping."""
        missing_toml = os.path.join(self.tmpdir, "missing-nested-file.toml")
        with open(missing_toml, "w") as handle:
            handle.write(
                '[nas:truenas]\nuser = "root"\n'
                'api_key_file = "/freq-init-inputs/missing-api-key"\n'
            )
        with (
            patch(
                "freq.modules.init_cmd.os.path.isfile",
                side_effect=lambda path: path == missing_toml,
            ),
            patch("freq.modules.init_cmd.fmt"),
            self.assertRaisesRegex(ValueError, "/freq-init-inputs/<relative-path>"),
        ):
            self._load(missing_toml)

    def test_unresolved_declared_device_credentials_file_fails_before_empty_return(self):
        """F3-1: a declared root file cannot collapse into no credentials."""
        missing_toml = "/srv/operator-staging/device-credentials.toml"
        with (
            patch("freq.modules.init_cmd.os.path.isfile", return_value=False),
            self.assertRaisesRegex(ValueError, "/freq-init-inputs/<relative-path>"),
        ):
            self._load(missing_toml)

    def test_teaching_surfaces_never_emit_host_side_init_input_paths(self):
        """F3-1: docs/help/templates teach only runner-visible container paths."""
        repo = Path(__file__).parents[1]
        host_prefix = "/root/" + "freq-init-inputs"
        violations = []
        roots = (repo / "docs", repo / "freq" / "data")
        scanned = 0
        portable_contract = "/freq-init-inputs/<relative-path>"
        portable_teaching = []
        for root in roots:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                scanned += 1
                text = path.read_text(errors="ignore")
                if host_prefix in text:
                    violations.append(path.relative_to(repo).as_posix())
                if portable_contract in text:
                    portable_teaching.append(path.relative_to(repo).as_posix())
        self.assertGreater(scanned, 20, "teaching inventory unexpectedly empty")
        compose = (repo / "docker-compose.yml").read_text()
        self.assertNotIn("reference the same absolute paths from the setup UI", compose)
        self.assertEqual(violations, [])
        self.assertTrue(
            portable_teaching or portable_contract in compose,
            "no shipped help/documentation teaches the portable container TOML path",
        )

    def test_idrac_scoped_password_rejects_overlong_value(self):
        """iDRAC rejects long RACADM password values; init should fail early."""
        from freq.modules.init_cmd import _validate_device_scoped_service_password

        self.assertFalse(
            _validate_device_scoped_service_password(
                {"idrac": {"user": "freq-ops", "password": "bootstrap"}},
                "abcdefghijklmnopqrstuvwxyz123456",
            )
        )
        self.assertTrue(
            _validate_device_scoped_service_password(
                {"idrac": {"user": "freq-ops", "password": "bootstrap"}},
                "Abcdefghij1234567890",
            )
        )


class TestPfSenseUninstall(unittest.TestCase):
    """pfSense uninstall must distinguish full removal from key-only fallback."""

    @patch("freq.modules.init_cmd._uninstall_auth_ssh")
    def test_remove_pfsense_uses_admin_auth_for_full_removal(self, mock_auth_ssh):
        from freq.modules.init_cmd import _remove_pfsense

        ssh = MagicMock(side_effect=[
            (0, "OK\n", ""),
            (0, "ACCOUNT_REMOVED\n", ""),
        ])
        mock_auth_ssh.return_value = ssh

        ok, reason = _remove_pfsense(
            "10.0.0.1",
            "svc-test",
            "/tmp/freq_id_ed25519",
            admin_auth={"user": "admin", "password": "secret", "key_path": ""},
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        mock_auth_ssh.assert_called_once_with(
            "10.0.0.1", "admin", auth_key="", auth_pass="secret"
        )
        remove_cmd = ssh.call_args_list[1].args[0]
        self.assertIn("sudo -n sh -c", remove_cmd)
        self.assertIn("pw userdel svc-test", remove_cmd)

    @patch("freq.modules.init_cmd._uninstall_ssh")
    def test_remove_pfsense_without_admin_auth_is_key_only(self, mock_uninstall_ssh):
        from freq.modules.init_cmd import _remove_pfsense

        ssh = MagicMock(side_effect=[
            (0, "OK\n", ""),
            (0, "KEY_REMOVED\n", ""),
        ])
        mock_uninstall_ssh.return_value = ssh

        ok, reason = _remove_pfsense("10.0.0.1", "svc-test", "/tmp/freq_id_ed25519")

        self.assertTrue(ok)
        self.assertEqual(reason, "key_only")

    @patch("freq.modules.init_cmd._remove_pfsense")
    def test_dispatch_uses_bootstrap_when_pfsense_creds_are_not_usable(self, mock_remove_pfsense):
        from freq.modules.init_cmd import _remove_from_host_dispatch

        mock_remove_pfsense.return_value = (True, "")
        bootstrap_auth = {"user": "freq-ops", "password": "", "key_path": "/tmp/fleet_key"}

        ok, reason = _remove_from_host_dispatch(
            "10.25.255.1",
            "pfsense",
            "freq-admin",
            "/tmp/freq_id_ed25519",
            "/tmp/freq_id_rsa",
            device_creds={"pfsense": {"user": "admin"}},
            bootstrap_auth=bootstrap_auth,
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        mock_remove_pfsense.assert_called_once_with(
            "10.25.255.1",
            "freq-admin",
            "/tmp/freq_id_ed25519",
            admin_auth=bootstrap_auth,
        )


class TestUninstallSSH(unittest.TestCase):
    """Uninstall SSH helper must honor per-call extra SSH options."""

    @patch("freq.modules.init_cmd._run")
    def test_uninstall_ssh_accepts_call_time_extra_opts(self, mock_run):
        from freq.modules.init_cmd import _uninstall_ssh

        mock_run.return_value = (0, "OK\n", "")
        ssh = _uninstall_ssh("10.0.0.10", "svc-test", "/tmp/freq_id_rsa")
        ssh("echo OK", extra_opts=["-o", "KexAlgorithms=+diffie-hellman-group1-sha1"])

        cmd = mock_run.call_args.args[0]
        self.assertIn("-i", cmd)
        self.assertIn("/tmp/freq_id_rsa", cmd)
        self.assertIn("svc-test@10.0.0.10", cmd)
        self.assertIn("KexAlgorithms=+diffie-hellman-group1-sha1", cmd)
        self.assertIn("UserKnownHostsFile=/dev/null", cmd)
        self.assertIn("GlobalKnownHostsFile=/dev/null", cmd)

    @patch("freq.modules.init_cmd.os.path.isfile", return_value=True)
    @patch("freq.modules.init_cmd._run")
    def test_uninstall_auth_ssh_accepts_call_time_extra_opts(self, mock_run, _mock_isfile):
        from freq.modules.init_cmd import _uninstall_auth_ssh

        mock_run.return_value = (0, "OK\n", "")
        ssh = _uninstall_auth_ssh("10.0.0.10", "freq-ops", auth_key="/tmp/bootstrap")
        ssh("racadm getsysinfo", extra_opts=["-o", "KexAlgorithms=+diffie-hellman-group1-sha1"])

        cmd = mock_run.call_args.args[0]
        self.assertIn("-i", cmd)
        self.assertIn("/tmp/bootstrap", cmd)
        self.assertIn("freq-ops@10.0.0.10", cmd)
        self.assertIn("KexAlgorithms=+diffie-hellman-group1-sha1", cmd)
        self.assertIn("UserKnownHostsFile=/dev/null", cmd)
        self.assertIn("GlobalKnownHostsFile=/dev/null", cmd)

    def test_uninstall_direct_switch_paths_do_not_write_known_hosts(self):
        src = Path(__file__).resolve().parents[1] / "freq" / "modules" / "init_cmd.py"
        text = src.read_text()
        switch_window = text.split("def _remove_switch(", 1)[1].split("def _remove_switch_with_auth", 1)[0]
        switch_auth_window = text.split("def _remove_switch_with_auth", 1)[1].split("def _remove_with_bootstrap_auth", 1)[0]
        self.assertIn("UNINSTALL_SSH_KNOWN_HOSTS_OPTS", switch_window)
        self.assertIn("UNINSTALL_SSH_KNOWN_HOSTS_OPTS", switch_auth_window)


class TestPveUninstall(unittest.TestCase):
    """PVE uninstall must remove cluster auth, not just the Linux user."""

    @patch("freq.modules.init_cmd._uninstall_ssh")
    def _case_remove_pve_deletes_token_user_and_agent_residue(self, mock_uninstall_ssh):
        from freq.modules.init_cmd import _remove_pve

        ssh = MagicMock(side_effect=[
            (0, "OK\n", ""),
            (0, "PVE_REMOVE_OK\n", ""),
        ])
        mock_uninstall_ssh.return_value = ssh

        ok, reason = _remove_pve("10.25.255.26", "freq-admin", "/tmp/freq_id_ed25519")

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        cleanup_cmd = ssh.call_args_list[1].args[0]
        self.assertIn("pveum user token remove freq-admin@pam freq-rw", cleanup_cmd)
        self.assertIn("pveum user delete freq-admin@pam", cleanup_cmd)
        self.assertIn("freq-agent.service", cleanup_cmd)
        self.assertIn("/opt/freq-agent", cleanup_cmd)
        self.assertIn("userdel -r freq-admin", cleanup_cmd)
        self.assertLess(
            cleanup_cmd.index("echo PVE_REMOVE_OK"),
            cleanup_cmd.index("userdel -r freq-admin"),
            "PVE uninstall must emit success before scheduling self-deletion",
        )

    @patch("freq.modules.init_cmd._remove_pve_with_auth")
    @patch("freq.modules.init_cmd._remove_pve")
    def _case_dispatch_falls_back_to_bootstrap_auth_when_service_account_fails(
        self,
        mock_remove_pve,
        mock_remove_pve_with_auth,
    ):
        from freq.modules.init_cmd import _remove_from_host_dispatch

        mock_remove_pve.return_value = (False, "Permission denied (publickey)")
        mock_remove_pve_with_auth.return_value = (True, "not_found")

        ok, reason = _remove_from_host_dispatch(
            "10.25.255.26",
            "pve",
            "freq-admin",
            "/tmp/freq_id_ed25519",
            "/tmp/freq_id_rsa",
            bootstrap_auth={"user": "freq-ops", "key_path": "/tmp/bootstrap", "password": ""},
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "not_found")
        mock_remove_pve_with_auth.assert_called_once_with(
            "10.25.255.26",
            "freq-admin",
            {"user": "freq-ops", "key_path": "/tmp/bootstrap", "password": ""},
        )

    @patch("freq.modules.init_cmd._uninstall_auth_ssh")
    def _case_linux_bootstrap_cleanup_treats_missing_account_as_clean(self, mock_auth_ssh):
        from freq.modules.init_cmd import _remove_unix_with_auth

        ssh = MagicMock(side_effect=[
            (0, "OK\n", ""),
            (0, "NOT_FOUND\nPOSTCHECK_OK\n", ""),
        ])
        mock_auth_ssh.return_value = ssh

        ok, reason = _remove_unix_with_auth(
            "10.25.255.55",
            "freq-admin",
            {"user": "freq-ops", "key_path": "/tmp/bootstrap", "password": ""},
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "not_found")
        cleanup_cmd = ssh.call_args_list[1].args[0]
        self.assertIn("sudo -n sh -c", cleanup_cmd)
        self.assertEqual(ssh.call_args_list[1].kwargs["timeout"], 120)
        self.assertIn(
            "systemctl disable --now freq-serve.service freq-watchdog.service",
            cleanup_cmd,
        )
        self.assertIn("systemctl disable --now freq-agent.service", cleanup_cmd)
        self.assertLess(
            cleanup_cmd.index("systemctl disable --now freq-serve.service"),
            cleanup_cmd.index("find / -xdev -uid"),
        )
        self.assertIn("systemctl is-active --quiet freq-agent.service", cleanup_cmd)
        self.assertIn("systemctl is-enabled --quiet freq-agent.service", cleanup_cmd)
        self.assertIn("POSTCHECK_DASHBOARD_ACTIVE", cleanup_cmd)
        self.assertIn("POSTCHECK_DASHBOARD_ENABLED", cleanup_cmd)
        self.assertIn("POSTCHECK_WATCHDOG_ACTIVE", cleanup_cmd)
        self.assertIn("POSTCHECK_WATCHDOG_ENABLED", cleanup_cmd)
        self.assertIn("find / -xdev -uid", cleanup_cmd)
        self.assertIn("POSTCHECK_OK", cleanup_cmd)

    @patch("freq.modules.init_cmd._uninstall_auth_ssh")
    def _case_linux_bootstrap_cleanup_rejects_false_green_residue(self, mock_auth_ssh):
        from freq.modules.init_cmd import _remove_unix_with_auth

        ssh = MagicMock(side_effect=[
            (0, "OK\n", ""),
            (6, "POSTCHECK_ACCOUNT_PRESENT\nPOSTCHECK_AGENT_ACTIVE\n", ""),
        ])
        mock_auth_ssh.return_value = ssh

        ok, reason = _remove_unix_with_auth(
            "10.25.255.40",
            "freq-admin",
            {"user": "freq-ops", "key_path": "/tmp/bootstrap", "password": ""},
        )

        self.assertFalse(ok)
        self.assertIn("POSTCHECK_ACCOUNT_PRESENT", reason)
        self.assertIn("POSTCHECK_AGENT_ACTIVE", reason)

    @patch("freq.modules.init_cmd._uninstall_auth_ssh")
    def _case_truenas_bootstrap_cleanup_keeps_appliance_not_found_contract(self, mock_auth_ssh):
        from freq.modules.init_cmd import _remove_unix_with_auth

        ssh = MagicMock(side_effect=[
            (0, "OK\n", ""),
            (0, "NOT_FOUND\n", ""),
        ])
        mock_auth_ssh.return_value = ssh

        ok, reason = _remove_unix_with_auth(
            "10.25.10.201",
            "freq-admin",
            {"user": "freq-ops", "key_path": "/tmp/bootstrap", "password": ""},
            htype="truenas",
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "not_found")
        self.assertEqual(ssh.call_args_list[1].kwargs["timeout"], 30)

    @patch("freq.modules.init_cmd._remove_unix_with_auth")
    @patch("freq.modules.init_cmd._remove_linux")
    def _case_linux_dispatch_prefers_keeper_auth_for_verified_cleanup(
        self, mock_remove_linux, mock_remove_unix_with_auth
    ):
        from freq.modules.init_cmd import _remove_from_host_dispatch

        bootstrap_auth = {
            "user": "freq-ops",
            "key_path": "/tmp/bootstrap",
            "password": "",
        }
        mock_remove_unix_with_auth.return_value = (True, "")

        with patch("freq.modules.init_cmd.os.path.isfile", return_value=True):
            ok, reason = _remove_from_host_dispatch(
                "10.25.255.40",
                "linux",
                "freq-admin",
                "/tmp/freq_id_ed25519",
                "/tmp/freq_id_rsa",
                bootstrap_auth=bootstrap_auth,
            )

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        mock_remove_unix_with_auth.assert_called_once_with(
            "10.25.255.40", "freq-admin", bootstrap_auth, htype="linux"
        )
        mock_remove_linux.assert_not_called()

    @patch("freq.modules.init_cmd._remove_switch_with_auth")
    @patch("freq.deployers.get_deployer")
    def _case_switch_uninstall_prefers_switch_device_credentials(
        self,
        mock_get_deployer,
        mock_remove_switch_with_auth,
    ):
        from freq.modules.init_cmd import _remove_from_host_dispatch

        deployer = MagicMock()
        deployer.remove.return_value = (False, "Permission denied (publickey)")
        mock_get_deployer.return_value = deployer
        mock_remove_switch_with_auth.return_value = (True, "")
        switch_auth = {"user": "freq-ops", "password": "switch-pass", "key_path": ""}

        ok, reason = _remove_from_host_dispatch(
            "10.25.255.5",
            "switch",
            "freq-admin",
            "/tmp/freq_id_ed25519",
            "/tmp/freq_id_rsa",
            device_creds={"switch": switch_auth},
            bootstrap_auth={"user": "freq-ops", "password": "", "key_path": "/tmp/fleet_key"},
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        deployer.remove.assert_not_called()
        mock_remove_switch_with_auth.assert_called_once_with(
            "10.25.255.5",
            "freq-admin",
            switch_auth,
        )

    @patch("freq.modules.init_cmd._remove_with_bootstrap_auth")
    @patch("freq.deployers.get_deployer")
    def _case_deployer_remove_exception_falls_back_to_bootstrap_auth(
        self,
        mock_get_deployer,
        mock_remove_with_bootstrap_auth,
    ):
        from freq.modules.init_cmd import _remove_from_host_dispatch

        deployer = MagicMock()
        deployer.remove.side_effect = OSError("Read-only file system: '/root/.ssh'")
        mock_get_deployer.return_value = deployer
        bootstrap_auth = {"user": "freq-ops", "password": "", "key_path": "/tmp/fleet_key"}
        mock_remove_with_bootstrap_auth.return_value = (True, "")

        ok, reason = _remove_from_host_dispatch(
            "10.25.10.201",
            "truenas",
            "freq-admin",
            "/tmp/freq_id_ed25519",
            "/tmp/freq_id_rsa",
            device_creds={},
            bootstrap_auth=bootstrap_auth,
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        mock_remove_with_bootstrap_auth.assert_called_once_with(
            "10.25.10.201",
            "truenas",
            "freq-admin",
            bootstrap_auth,
        )

    @patch("freq.modules.init_cmd._ssh_with_pass")
    def _case_switch_bootstrap_cleanup_answers_confirm_and_verifies_absence(self, mock_ssh_with_pass):
        from freq.modules.init_cmd import _remove_switch_with_auth

        mock_ssh_with_pass.side_effect = [
            (0, "switch#show running-config | include username freq-admin\nusername freq-admin privilege 15 secret 5 hash\n", ""),
            (0, "switch(config)#no username freq-admin\nDo you want to continue? [confirm]\nswitch#write memory\n", ""),
            (0, "switch#show running-config | include username freq-admin\nswitch#show running-config | section ip ssh pubkey-chain\nip ssh pubkey-chain\n  username freq-ops\n", ""),
        ]

        ok, reason = _remove_switch_with_auth(
            "10.25.255.5",
            "freq-admin",
            {"user": "freq-ops", "password": "secret", "key_path": ""},
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        cleanup_script = mock_ssh_with_pass.call_args_list[1].kwargs["input_text"]
        self.assertIn("ip ssh pubkey-chain\nno username freq-admin\nexit", cleanup_script)
        self.assertIn("exit\nno username freq-admin\n\nend\nwrite memory", cleanup_script)

    @patch("freq.modules.init_cmd._ssh_with_pass")
    def _case_switch_bootstrap_cleanup_fails_when_verification_still_shows_user(self, mock_ssh_with_pass):
        from freq.modules.init_cmd import _remove_switch_with_auth

        mock_ssh_with_pass.side_effect = [
            (0, "switch#show running-config | include username freq-admin\nusername freq-admin privilege 15 secret 5 hash\n", ""),
            (0, "switch(config)#no username freq-admin\nDo you want to continue? [confirm]\n", ""),
            (0, "switch#show running-config | include username freq-admin\nusername freq-admin privilege 15 secret 5 hash\n", ""),
        ]

        ok, reason = _remove_switch_with_auth(
            "10.25.255.5",
            "freq-admin",
            {"user": "freq-ops", "password": "secret", "key_path": ""},
        )

        self.assertFalse(ok)
        self.assertIn("no username freq-admin", reason)

    @patch("freq.modules.init_cmd._ssh_with_pass")
    def _case_switch_bootstrap_cleanup_treats_absent_user_as_clean(self, mock_ssh_with_pass):
        from freq.modules.init_cmd import _remove_switch_with_auth

        mock_ssh_with_pass.return_value = (
            0,
            "switch#show running-config | include username freq-admin\nswitch#show running-config | section ip ssh pubkey-chain\nip ssh pubkey-chain\n  username freq-ops\n",
            "",
        )

        ok, reason = _remove_switch_with_auth(
            "10.25.255.5",
            "freq-admin",
            {"user": "freq-ops", "password": "secret", "key_path": ""},
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "not_found")
        self.assertEqual(mock_ssh_with_pass.call_count, 1)

    @patch("freq.modules.init_cmd._remove_idrac_with_auth")
    @patch("freq.deployers.get_deployer")
    def _case_idrac_uninstall_prefers_device_credentials(self, mock_get_deployer, mock_remove_idrac_with_auth):
        from freq.modules.init_cmd import _remove_from_host_dispatch

        deployer = MagicMock()
        deployer.remove.return_value = (False, "Permission denied")
        mock_get_deployer.return_value = deployer
        idrac_auth = {"user": "freq-ops", "password": "idrac-pass", "key_path": ""}
        mock_remove_idrac_with_auth.return_value = (True, "")

        ok, reason = _remove_from_host_dispatch(
            "10.25.255.10",
            "idrac",
            "freq-admin",
            "/tmp/freq_id_ed25519",
            "/tmp/freq_id_rsa",
            device_creds={"idrac": idrac_auth},
            bootstrap_auth={"user": "freq-ops", "password": "", "key_path": "/tmp/fleet_key"},
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        deployer.remove.assert_not_called()
        mock_remove_idrac_with_auth.assert_called_once_with(
            "10.25.255.10",
            "freq-admin",
            idrac_auth,
        )

    @patch("freq.modules.init_cmd._run_idrac_command")
    @patch("freq.modules.init_cmd._query_idrac_slots")
    @patch("freq.modules.init_cmd._uninstall_auth_ssh")
    def _case_idrac_uninstall_treats_empty_key_slot_as_clean(
        self,
        mock_auth_ssh,
        mock_query_slots,
        mock_run_idrac,
    ):
        from freq.modules.init_cmd import _remove_idrac_with_auth

        ssh = MagicMock(return_value=(0, "OK\n", ""))
        mock_auth_ssh.return_value = ssh
        mock_query_slots.return_value = ({8: "freq-admin"}, 8)
        mock_run_idrac.side_effect = [
            (False, 'racadm sshpkauth -i 8 -k 1 -t "": ERROR: Key not present'),
            (True, "Object value modified successfully"),
            (True, "Object value modified successfully"),
        ]

        ok, reason = _remove_idrac_with_auth(
            "10.25.255.10",
            "freq-admin",
            {"user": "freq-ops", "password": "", "key_path": "/tmp/fleet_key"},
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertEqual(mock_run_idrac.call_count, 3)


PVE_UNINSTALL_CASES = (
    "_case_remove_pve_deletes_token_user_and_agent_residue",
    "_case_dispatch_falls_back_to_bootstrap_auth_when_service_account_fails",
    "_case_linux_bootstrap_cleanup_treats_missing_account_as_clean",
    "_case_linux_bootstrap_cleanup_rejects_false_green_residue",
    "_case_truenas_bootstrap_cleanup_keeps_appliance_not_found_contract",
    "_case_linux_dispatch_prefers_keeper_auth_for_verified_cleanup",
    "_case_switch_uninstall_prefers_switch_device_credentials",
    "_case_deployer_remove_exception_falls_back_to_bootstrap_auth",
    "_case_switch_bootstrap_cleanup_answers_confirm_and_verifies_absence",
    "_case_switch_bootstrap_cleanup_fails_when_verification_still_shows_user",
    "_case_switch_bootstrap_cleanup_treats_absent_user_as_clean",
    "_case_idrac_uninstall_prefers_device_credentials",
    "_case_idrac_uninstall_treats_empty_key_slot_as_clean",
)


class TestPveUninstallMatrix(unittest.TestCase):
    def test_pve_uninstall_matrix(self):
        self.assertEqual(len(PVE_UNINSTALL_CASES), 13)
        run_case_matrix(self, TestPveUninstall, PVE_UNINSTALL_CASES)

class TestUninstallTargetMap(unittest.TestCase):
    """Uninstall must support explicit re-zero target contracts."""

    def test_loads_explicit_markdown_target_map(self):
        from freq.modules.init_cmd import _load_uninstall_target_map

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(
                """# Re-Zero Target Map
## VMs
| VMID | IP | name | node | access / notes |
|------|----|------|------|----------------|
| 106 | 10.25.255.38 | dc01-proxy | pve01 | freq-ops |
| 5000 | 10.25.10.200 | pfsense-lab | pve01 | dev pfSense |
## Core devices
| device | IP | access |
|--------|----|--------|
| switch (gigecolo) | 10.25.255.5 | Cisco IOS |
## Out of re-zero scope
| 900 | 10.0.0.9 | do-not-touch |
"""
            )
            path = f.name

        try:
            targets = _load_uninstall_target_map(path)
        finally:
            os.unlink(path)

        self.assertIn(("10.25.255.38", "linux", "VM106 dc01-proxy"), targets)
        self.assertIn(("10.25.10.200", "pfsense", "VM5000 pfsense-lab"), targets)
        self.assertIn(("10.25.255.5", "switch", "switch (gigecolo)"), targets)
        self.assertFalse(any(t[0] == "10.0.0.9" for t in targets))

    def test_uninstall_targets_use_explicit_map_and_cli_pve_nodes(self):
        from freq.modules.init_cmd import _uninstall_targets_from_config

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(
                """## VMs
| VMID | IP | name | node | access / notes |
|------|----|------|------|----------------|
| 106 | 10.25.255.38 | dc01-proxy | pve01 | freq-ops |
"""
            )
            path = f.name

        try:
            cfg = types.SimpleNamespace(pve_nodes=["10.25.255.99"], hosts=[])
            args = types.SimpleNamespace(target_map=path, pve_nodes="10.25.255.26,10.25.255.27")
            targets = _uninstall_targets_from_config(cfg, args)
        finally:
            os.unlink(path)

        self.assertEqual(targets[0], ("10.25.255.26", "pve", "PVE 10.25.255.26"))
        self.assertEqual(targets[1], ("10.25.255.27", "pve", "PVE 10.25.255.27"))
        self.assertIn(("10.25.255.38", "linux", "VM106 dc01-proxy"), targets)
        self.assertFalse(any(t[0] == "10.25.255.99" for t in targets))

    def test_uninstall_targets_skip_inventory_only_hosts_from_live_config(self):
        from freq.modules.init_cmd import _uninstall_targets_from_config

        cfg = types.SimpleNamespace(
            pve_nodes=["10.25.255.26"],
            hosts=[
                types.SimpleNamespace(ip="10.25.255.26", htype="pve", label="pve01", managed=True),
                types.SimpleNamespace(ip="10.25.255.30", htype="docker", label="plex", managed=True),
                types.SimpleNamespace(ip="10.25.255.50", htype="pve", label="pve-freq", managed=False),
                types.SimpleNamespace(ip="10.25.255.8", htype="linux", label="nexus", managed=False),
            ],
        )
        args = types.SimpleNamespace(target_map=None, pve_nodes=None)

        targets = _uninstall_targets_from_config(cfg, args)

        self.assertIn(("10.25.255.26", "pve", "PVE 10.25.255.26"), targets)
        self.assertIn(("10.25.255.30", "docker", "plex (10.25.255.30)"), targets)
        self.assertFalse(any(t[0] == "10.25.255.50" for t in targets))
        self.assertFalse(any(t[0] == "10.25.255.8" for t in targets))

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.init_cmd.shutil.which", return_value="/usr/bin/docker")
    @patch("freq.modules.init_cmd._run")
    def test_purge_local_docker_volumes_is_explicit_compose_down_v(self, mock_run, _mock_which, _mock_fmt):
        from freq.modules.init_cmd import _purge_local_docker_volumes

        mock_run.return_value = (0, "removed\n", "")
        with tempfile.TemporaryDirectory() as td:
            Path(td, "docker-compose.yml").write_text("services: {}\n")
            cfg = types.SimpleNamespace(install_dir=td)
            args = types.SimpleNamespace(compose_dir="")

            self.assertTrue(_purge_local_docker_volumes(cfg, args))

        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[:2], ["sh", "-lc"])
        self.assertIn("docker compose down -v", cmd[2])

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.init_cmd.shutil.which", return_value="/usr/bin/docker")
    @patch("freq.modules.init_cmd._run")
    def test_borrows_uninstall_keys_from_running_container(self, mock_run, _mock_which, _mock_fmt):
        from freq.modules.init_cmd import _borrow_container_uninstall_keys

        def fake_run(cmd, timeout=None):
            if cmd[:2] == ["docker", "cp"]:
                Path(cmd[3]).write_text("key material\n")
                return (0, "", "")
            return (1, "", "unexpected")

        mock_run.side_effect = fake_run
        cfg = types.SimpleNamespace(key_dir="/opt/pve-freq/data/keys")

        ed_key, rsa_key, tmp_dir = _borrow_container_uninstall_keys(cfg)
        try:
            self.assertTrue(ed_key.endswith("freq_id_ed25519"))
            self.assertTrue(rsa_key.endswith("freq_id_rsa"))
            self.assertTrue(os.path.isfile(ed_key))
            self.assertTrue(os.path.isfile(rsa_key))
            first_cp = mock_run.call_args_list[0].args[0]
            self.assertEqual(first_cp[:2], ["docker", "cp"])
            self.assertIn("pve-freq:/opt/pve-freq/data/keys/freq_id_ed25519", first_cp[2])
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)


class TestUninstallLocalCleanup(unittest.TestCase):
    """Local uninstall must stop the dashboard service before userdel."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-uninstall-local-")
        self.key_dir = os.path.join(self.tmpdir, "keys")
        self.conf_dir = os.path.join(self.tmpdir, "conf")
        os.makedirs(self.key_dir, exist_ok=True)
        os.makedirs(self.conf_dir, exist_ok=True)
        self.vault_file = os.path.join(self.tmpdir, "vault.enc")
        self.ed_key = os.path.join(self.key_dir, "freq_id_ed25519")
        self.rsa_key = os.path.join(self.key_dir, "freq_id_rsa")
        for path in [
            self.ed_key,
            f"{self.ed_key}.pub",
            self.rsa_key,
            f"{self.rsa_key}.pub",
            self.vault_file,
            os.path.join(self.conf_dir, "roles.conf"),
            os.path.join(self.conf_dir, ".initialized"),
        ]:
            with open(path, "w") as f:
                f.write("x")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("freq.modules.init_cmd.logger")
    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.os.unlink")
    @patch("freq.modules.init_cmd.os.path.isfile")
    def test_uninstall_stops_service_before_userdel(self, mock_isfile, mock_unlink, mock_run, _mock_fmt, _mock_logger):
        from freq.modules.init_cmd import _uninstall_execute

        calls = []

        def fake_isfile(path):
            if path == "/etc/sudoers.d/freq-freq-admin":
                return False
            return os.path.exists(path)

        def fake_run(cmd, *args, **kwargs):
            calls.append(cmd)
            if cmd[:3] == ["systemctl", "is-enabled", "freq-serve"]:
                return (0, "enabled\n", "")
            if cmd[:3] == ["systemctl", "is-active", "freq-serve"]:
                return (0, "active\n", "")
            if cmd[:3] == ["systemctl", "disable", "--now"]:
                return (0, "", "")
            if cmd[:2] == ["id", "freq-admin"]:
                return (0, "uid=123\n", "")
            if cmd[:2] == ["pkill", "-u"] or cmd[:3] == ["pkill", "-9", "-u"]:
                return (0, "", "")
            if cmd[:2] == ["userdel", "-r"]:
                return (0, "", "")
            if cmd[:3] == ["getent", "group", "freq-admin"]:
                return (1, "", "")
            return (1, "", "")

        mock_run.side_effect = fake_run
        mock_isfile.side_effect = fake_isfile

        cfg = MagicMock()
        cfg.key_dir = self.key_dir
        cfg.vault_file = self.vault_file
        cfg.conf_dir = self.conf_dir

        rc = _uninstall_execute(cfg, "freq-admin", self.ed_key, self.rsa_key, [])

        self.assertEqual(rc, 0)
        disable_idx = next(i for i, cmd in enumerate(calls) if cmd[:3] == ["systemctl", "disable", "--now"])
        userdel_idx = next(i for i, cmd in enumerate(calls) if cmd[:2] == ["userdel", "-r"])
        self.assertLess(disable_idx, userdel_idx, "freq-serve must be stopped before userdel")

    @patch("freq.modules.init_cmd.logger")
    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.init_cmd._remove_from_host_dispatch", return_value=(True, "not_found"))
    @patch("freq.modules.init_cmd._borrow_container_uninstall_keys", return_value=("", "", None))
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.os.unlink")
    @patch("freq.modules.init_cmd.os.path.isfile")
    def test_uninstall_uses_bootstrap_when_generated_keys_are_missing(
        self,
        mock_isfile,
        mock_unlink,
        mock_run,
        _mock_borrow,
        mock_remove,
        _mock_fmt,
        _mock_logger,
    ):
        from freq.modules.init_cmd import _uninstall_execute

        def fake_isfile(path):
            if path in {self.ed_key, self.rsa_key}:
                return False
            if path == "/etc/sudoers.d/freq-freq-admin":
                return False
            return os.path.exists(path)

        def fake_run(cmd, *args, **kwargs):
            if cmd[:3] == ["systemctl", "is-enabled", "freq-serve"]:
                return (1, "", "")
            if cmd[:3] == ["systemctl", "is-active", "freq-serve"]:
                return (1, "", "")
            if cmd[:2] == ["id", "freq-admin"]:
                return (1, "", "")
            if cmd[:3] == ["getent", "group", "freq-admin"]:
                return (1, "", "")
            return (0, "", "")

        mock_isfile.side_effect = fake_isfile
        mock_run.side_effect = fake_run

        cfg = MagicMock()
        cfg.key_dir = self.key_dir
        cfg.vault_file = self.vault_file
        cfg.conf_dir = self.conf_dir
        args = types.SimpleNamespace(
            device_credentials=None,
            bootstrap_user="freq-ops",
            bootstrap_key="/home/freq-ops/.ssh/fleet_key",
            bootstrap_password_file=None,
            purge_docker_volumes=False,
        )

        rc = _uninstall_execute(
            cfg,
            "freq-admin",
            self.ed_key,
            self.rsa_key,
            [("10.25.255.55", "linux", "VM5005 freq-test")],
            args,
        )

        self.assertEqual(rc, 0)
        mock_remove.assert_called_once()
        self.assertEqual(
            mock_remove.call_args.kwargs["bootstrap_auth"],
            {"user": "freq-ops", "password": "", "key_path": "/home/freq-ops/.ssh/fleet_key"},
        )

    @patch("freq.modules.init_cmd.logger")
    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.init_cmd._remove_from_host_dispatch", return_value=(False, "boom"))
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.os.unlink")
    @patch("freq.modules.init_cmd.os.path.isfile")
    def test_uninstall_preserves_local_state_when_remote_teardown_fails(
        self,
        mock_isfile,
        mock_unlink,
        mock_run,
        _mock_remove,
        _mock_fmt,
        _mock_logger,
    ):
        from freq.modules.init_cmd import _uninstall_execute

        def fake_isfile(path):
            if path == "/etc/sudoers.d/freq-freq-admin":
                return False
            return os.path.exists(path)

        mock_isfile.side_effect = fake_isfile
        mock_run.return_value = (1, "", "")
        cfg = MagicMock()
        cfg.key_dir = self.key_dir
        cfg.vault_file = self.vault_file
        cfg.conf_dir = self.conf_dir

        rc = _uninstall_execute(
            cfg,
            "freq-admin",
            self.ed_key,
            self.rsa_key,
            [("10.25.255.30", "linux", "plex")],
        )

        self.assertEqual(rc, 1)
        mock_unlink.assert_not_called()
        self.assertTrue(os.path.exists(os.path.join(self.conf_dir, ".initialized")))

    @patch("freq.modules.init_cmd.logger")
    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.init_cmd._remove_from_host_dispatch", return_value=(False, "connection timed out"))
    @patch("freq.modules.init_cmd._reset_local_init_state")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.os.path.isfile")
    def test_uninstall_preserves_local_state_when_host_is_skipped_by_default(
        self,
        mock_isfile,
        mock_run,
        mock_reset,
        _mock_remove,
        _mock_fmt,
        _mock_logger,
    ):
        from freq.modules.init_cmd import _uninstall_execute

        mock_isfile.side_effect = lambda path: path in {self.ed_key, self.rsa_key}
        mock_run.return_value = (1, "", "")
        cfg = MagicMock()
        cfg.key_dir = self.key_dir
        cfg.vault_file = self.vault_file
        cfg.conf_dir = self.conf_dir
        args = types.SimpleNamespace(device_credentials=None, force_local_reset=False)

        rc = _uninstall_execute(
            cfg,
            "freq-admin",
            self.ed_key,
            self.rsa_key,
            [("10.25.66.69", "linux", "runescapebotvm")],
            args,
        )

        self.assertEqual(rc, 1)
        mock_reset.assert_not_called()

    @patch("freq.modules.init_cmd.logger")
    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.init_cmd._remove_from_host_dispatch", return_value=(False, "connection timed out"))
    @patch("freq.modules.init_cmd._credentials_dir", return_value="/tmp/freq-test-missing-creds")
    @patch("freq.modules.init_cmd._reset_local_init_state")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.os.path.isfile")
    def test_uninstall_force_local_reset_allows_skipped_unreachable_hosts(
        self,
        mock_isfile,
        mock_run,
        mock_reset,
        _mock_credential_dir,
        _mock_remove,
        mock_fmt,
        _mock_logger,
    ):
        from freq.modules.init_cmd import _uninstall_execute

        mock_isfile.side_effect = lambda path: path in {self.ed_key, self.rsa_key}
        mock_run.return_value = (1, "", "")
        cfg = MagicMock()
        cfg.key_dir = self.key_dir
        cfg.vault_file = self.vault_file
        cfg.conf_dir = self.conf_dir
        args = types.SimpleNamespace(
            device_credentials=None,
            force_local_reset=True,
            purge_docker_volumes=False,
        )

        rc = _uninstall_execute(
            cfg,
            "freq-admin",
            self.ed_key,
            self.rsa_key,
            [("10.25.66.69", "linux", "runescapebotvm")],
            args,
        )

        self.assertEqual(rc, 0)
        mock_reset.assert_called_once_with(cfg, remove_live_config=True)
        warnings = [call.args[0] for call in mock_fmt.step_warn.call_args_list]
        self.assertTrue(any("--force-local-reset" in warning for warning in warnings))


# ═══════════════════════════════════════════════════════════════════
# _update_toml_value() tests
# ═══════════════════════════════════════════════════════════════════

class TestUpdateTomlValue(unittest.TestCase):
    """Test the TOML content updater used by _phase_configure."""

    def _update(self, content, key, value):
        from freq.modules.init_cmd import _update_toml_value
        return _update_toml_value(content, key, value)

    def test_updates_string_value(self):
        """Simple string key gets updated."""
        content = 'gateway = "10.0.0.1"\n'
        result = self._update(content, "gateway", "192.168.1.1")
        self.assertIn('gateway = "192.168.1.1"', result)
        self.assertNotIn("10.0.0.1", result)

    def test_updates_list_value(self):
        """List value is formatted as TOML array."""
        content = 'nodes = ["old1"]\n'
        result = self._update(content, "nodes", ["10.0.0.1", "10.0.0.2"])
        self.assertIn('nodes = ["10.0.0.1", "10.0.0.2"]', result)

    def test_updates_bool_value(self):
        """Boolean value is formatted as TOML true/false."""
        content = 'debug = false\n'
        result = self._update(content, "debug", True)
        self.assertIn("debug = true", result)

    def test_uncomments_commented_key(self):
        """Commented-out key is uncommented and set."""
        content = '# nodes = []\n'
        result = self._update(content, "nodes", ["1.2.3.4"])
        self.assertIn('nodes = ["1.2.3.4"]', result)
        self.assertNotIn("#", result.split("\n")[0])

    def test_preserves_inline_comment(self):
        """Inline comment after value is preserved."""
        content = 'mode = "root"  # SSH as root directly\n'
        result = self._update(content, "mode", "sudo")
        self.assertIn('mode = "sudo"', result)
        self.assertIn("# SSH as root directly", result)

    def test_no_match_inserts_key(self):
        """Missing keys are inserted so init can populate minimal configs."""
        content = 'something_else = "value"\n'
        result = self._update(content, "nonexistent", "test")
        self.assertIn(content, result)
        self.assertIn('nonexistent = "test"', result)


# ═══════════════════════════════════════════════════════════════════
# _phase_configure() tests
# ═══════════════════════════════════════════════════════════════════

class TestPhaseConfigure(unittest.TestCase):
    """Test Phase 2: interactive cluster configuration."""

    def setUp(self):
        """Create temp directory with a minimal freq.toml."""
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-configure-")
        self.toml_path = os.path.join(self.tmpdir, "freq.toml")
        self.base_toml = (
            "[freq]\n"
            'version = "2.0.0"\n'
            "\n"
            "[ssh]\n"
            'mode = "sudo"\n'
            "\n"
            "[pve]\n"
            "# nodes = []\n"
            "# node_names = []\n"
            "\n"
            "[vm.defaults]\n"
            '# gateway = ""\n'
            '# nameserver = "1.1.1.1"\n'
            "\n"
            "[infrastructure]\n"
            '# cluster_name = ""\n'
        )
        with open(self.toml_path, "w") as f:
            f.write(self.base_toml)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cfg(self, **overrides):
        """Build a mock cfg object with defaults for _phase_configure."""
        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.pve_nodes = overrides.get("pve_nodes", [])
        cfg.pve_node_names = overrides.get("pve_node_names", [])
        cfg.vm_gateway = overrides.get("vm_gateway", "")
        cfg.vm_nameserver = overrides.get("vm_nameserver", "")
        cfg.cluster_name = overrides.get("cluster_name", "")
        cfg.ssh_mode = overrides.get("ssh_mode", "sudo")
        cfg.pve_storage = overrides.get("pve_storage", {})
        return cfg

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def _case_phase_configure_writes_pve_nodes(self, mock_fmt, mock_input, mock_lc):
        """PVE node IPs and names are written to freq.toml via interactive prompt."""
        cfg = self._make_cfg()
        # _input calls in order: node IPs, node names, storage×3, gateway, nameserver, cluster, ssh mode
        mock_input.side_effect = [
            "10.0.0.1 10.0.0.2 10.0.0.3",  # PVE node IPs
            "pve01 pve02 pve03",             # Node names
            "local-lvm",                      # Storage pve01
            "local-lvm",                      # Storage pve02
            "local-lvm",                      # Storage pve03
            "10.0.0.1",                       # Gateway
            "1.1.1.1",                        # Nameserver
            "testlab",                        # Cluster name
            "sudo",                           # SSH mode
        ]
        mock_lc.return_value = cfg  # Reload returns same cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg)

        with open(self.toml_path) as f:
            content = f.read()

        self.assertIn("10.0.0.1", content)
        self.assertIn("10.0.0.2", content)
        self.assertIn("10.0.0.3", content)
        self.assertIn("pve01", content)
        self.assertIn("pve02", content)
        self.assertIn("pve03", content)

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def _case_phase_configure_writes_gateway(self, mock_fmt, mock_input, mock_lc):
        """Gateway and nameserver are written to freq.toml via interactive prompt."""
        cfg = self._make_cfg()
        mock_input.side_effect = [
            "10.0.0.1",       # PVE node IPs (single node)
            "pve01",           # Node name
            "local-lvm",       # Storage
            "192.168.1.1",     # Gateway
            "8.8.8.8",         # Nameserver
            "homelab",         # Cluster name
            "sudo",            # SSH mode
        ]
        mock_lc.return_value = cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg)

        with open(self.toml_path) as f:
            content = f.read()

        self.assertIn('gateway = "192.168.1.1"', content)

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def _case_phase_configure_cli_pve_nodes(self, mock_fmt, mock_input, mock_lc):
        """--pve-nodes CLI arg writes nodes to freq.toml without interactive prompt."""
        cfg = self._make_cfg()
        args = MagicMock()
        args.pve_nodes = "10.0.0.1 10.0.0.2"
        args.pve_node_names = "pve01 pve02"
        args.gateway = None
        args.nameserver = None
        args.hosts_file = None
        args.yes = False

        # Only interactive prompts that remain: gateway, nameserver, cluster, ssh mode
        mock_input.side_effect = [
            "10.0.0.1",   # Gateway
            "1.1.1.1",    # Nameserver (default)
            "",            # Cluster name (skip)
            "sudo",        # SSH mode
        ]
        mock_lc.return_value = cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg, args)

        with open(self.toml_path) as f:
            content = f.read()

        self.assertIn("10.0.0.1", content)
        self.assertIn("10.0.0.2", content)
        self.assertIn("pve01", content)
        self.assertIn("pve02", content)
        # Verify cfg was updated
        self.assertEqual(cfg.pve_nodes, ["10.0.0.1", "10.0.0.2"])

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def _case_phase_configure_cli_gateway(self, mock_fmt, mock_input, mock_lc):
        """--gateway CLI arg writes gateway without interactive prompt."""
        cfg = self._make_cfg()
        args = MagicMock()
        args.pve_nodes = "10.0.0.1"
        args.pve_node_names = "pve01"
        args.gateway = "192.168.1.1"
        args.nameserver = "8.8.4.4"
        args.hosts_file = None
        args.yes = False

        # Only cluster name and SSH mode remain interactive
        mock_input.side_effect = [
            "mylab",   # Cluster name
            "sudo",    # SSH mode
        ]
        mock_lc.return_value = cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg, args)

        with open(self.toml_path) as f:
            content = f.read()

        self.assertIn('gateway = "192.168.1.1"', content)
        self.assertIn('nameserver = "8.8.4.4"', content)
        self.assertEqual(cfg.vm_gateway, "192.168.1.1")
        self.assertEqual(cfg.vm_nameserver, "8.8.4.4")

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def _case_phase_configure_rejects_invalid_cli_pve_nodes(self, mock_fmt, mock_input, mock_lc):
        cfg = self._make_cfg()
        args = MagicMock()
        args.pve_nodes = "10.0.0.1 bad-ip"
        args.pve_node_names = "pve01 pve02"
        args.gateway = None
        args.nameserver = None
        args.hosts_file = None
        args.yes = False

        mock_input.side_effect = [
            "10.0.0.1",
            "1.1.1.1",
            "",
            "sudo",
        ]
        mock_lc.return_value = cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg, args)

        with open(self.toml_path) as f:
            content = f.read()

        self.assertNotIn("bad-ip", content)
        self.assertEqual(cfg.pve_nodes, [])
        mock_fmt.step_fail.assert_any_call("Invalid PVE node IP(s) from CLI: bad-ip")

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def _case_phase_configure_rejects_invalid_cli_gateway(self, mock_fmt, mock_input, mock_lc):
        cfg = self._make_cfg()
        args = MagicMock()
        args.pve_nodes = "10.0.0.1"
        args.pve_node_names = "pve01"
        args.gateway = "not-an-ip"
        args.nameserver = "8.8.4.4"
        args.hosts_file = None
        args.yes = False

        mock_input.side_effect = [
            "mylab",
            "sudo",
        ]
        mock_lc.return_value = cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg, args)

        with open(self.toml_path) as f:
            content = f.read()

        self.assertNotIn('gateway = "not-an-ip"', content)
        self.assertEqual(cfg.vm_gateway, "")
        mock_fmt.step_fail.assert_any_call("Invalid gateway IP from CLI: not-an-ip")

    @patch("freq.modules.init_cmd._confirm")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def _case_phase_configure_skips_if_populated(self, mock_fmt, mock_input, mock_confirm):
        """Already-configured values are shown but not re-prompted (unless user opts in)."""
        cfg = self._make_cfg(
            pve_nodes=["10.0.0.1"],
            pve_node_names=["pve01"],
            vm_gateway="10.0.0.1",
            vm_nameserver="8.8.8.8",
            cluster_name="homelab",
            ssh_mode="sudo",
        )
        # User declines to reconfigure nodes
        mock_confirm.return_value = False
        # Only nameserver and SSH mode prompts will fire (they always prompt)
        # Nameserver: already set and != 1.1.1.1, so skipped
        # SSH mode: prompted but same as current
        mock_input.side_effect = [
            "sudo",  # SSH mode — same as current
        ]

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg)

        # freq.toml should be unchanged (no write happened)
        with open(self.toml_path) as f:
            content = f.read()

        self.assertEqual(content, self.base_toml)


PHASE_CONFIGURE_CASES = (
    "_case_phase_configure_writes_pve_nodes",
    "_case_phase_configure_writes_gateway",
    "_case_phase_configure_cli_pve_nodes",
    "_case_phase_configure_cli_gateway",
    "_case_phase_configure_rejects_invalid_cli_pve_nodes",
    "_case_phase_configure_rejects_invalid_cli_gateway",
    "_case_phase_configure_skips_if_populated",
)


class TestPhaseConfigureMatrix(unittest.TestCase):
    def test_phase_configure_matrix(self):
        run_case_matrix(self, TestPhaseConfigure, PHASE_CONFIGURE_CASES)


# ═══════════════════════════════════════════════════════════════════
# Bootstrap key tests — _phase_pve_deploy + _phase_fleet_deploy
# ═══════════════════════════════════════════════════════════════════

class TestBootstrapKey(unittest.TestCase):
    """Test that --bootstrap-key skips interactive prompts in deploy phases."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-bootstrap-")
        # Create a fake SSH key file
        self.key_path = os.path.join(self.tmpdir, "id_ed25519")
        with open(self.key_path, "w") as f:
            f.write("fake-ssh-key-for-testing")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_args(self, bootstrap_key=None, bootstrap_user=None):
        args = MagicMock()
        args.bootstrap_key = bootstrap_key
        args.bootstrap_user = bootstrap_user
        args.device_credentials = None
        return args

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_pve_deploy_uses_bootstrap_key(self, mock_fmt, mock_input, mock_dispatch):
        """When bootstrap_key is set, PVE deploy skips interactive auth prompts."""
        cfg = MagicMock()
        cfg.pve_nodes = ["10.0.0.1"]
        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}
        args = self._make_args(bootstrap_key=self.key_path, bootstrap_user="root")

        mock_dispatch.return_value = True

        from freq.modules.init_cmd import _phase_pve_deploy
        _phase_pve_deploy(cfg, ctx, args)

        # _input should NOT have been called for auth method selection
        # (bootstrap mode skips the A/B choice prompt)
        for call in mock_input.call_args_list:
            prompt = call[0][0] if call[0] else ""
            self.assertNotIn("Deploy as user", prompt,
                             "Bootstrap mode should skip interactive user prompt")
            self.assertNotIn("Choice", prompt,
                             "Bootstrap mode should skip A/B auth choice")

        # Verify dispatch was called with the bootstrap key
        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args[0]
        # call_args: (ip, htype, ctx, auth_pass, auth_key, pve_user)
        self.assertEqual(call_args[4], self.key_path)  # auth_key = bootstrap key path
        self.assertEqual(call_args[5], "root")          # pve_user = bootstrap_user

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_fleet_deploy_uses_bootstrap_key(self, mock_fmt, mock_input, mock_dispatch):
        """When bootstrap_key is set, fleet deploy skips interactive auth prompts for linux hosts."""
        cfg = MagicMock()
        host = MagicMock(ip="10.0.0.10", label="testhost", htype="linux")
        host.category = "server"
        cfg.hosts = [host]
        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}
        args = self._make_args(bootstrap_key=self.key_path, bootstrap_user="root")

        mock_dispatch.return_value = True

        from freq.modules.init_cmd import _phase_fleet_deploy
        _phase_fleet_deploy(cfg, ctx, args)

        # _input should NOT have been called for auth method selection
        for call in mock_input.call_args_list:
            prompt = call[0][0] if call[0] else ""
            self.assertNotIn("Password", prompt,
                             "Bootstrap mode should skip password prompt")

        # Verify dispatch was called with the bootstrap key
        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args[0]
        self.assertEqual(call_args[4], self.key_path)  # auth_key = bootstrap key path
        self.assertEqual(call_args[5], "root")          # auth_user = bootstrap_user


# ═══════════════════════════════════════════════════════════════════
# Device credentials in interactive fleet deploy
# ═══════════════════════════════════════════════════════════════════

class TestDeviceCredsInteractive(unittest.TestCase):
    """Test --device-credentials in interactive _phase_fleet_deploy."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-devcreds-")
        self.key_path = os.path.join(self.tmpdir, "id_ed25519")
        with open(self.key_path, "w") as f:
            f.write("fake-key")
        # _phase_fleet_deploy records before/after audit snapshots around the
        # dispatch boundary.  These credential-routing unit tests do not own
        # transport behavior, so a real snapshot would leak SSH and add ten
        # seconds of timeout to each case.
        self._snapshot_patcher = patch(
            "freq.modules.init_cmd.audit.snapshot_host", return_value={}
        )
        self._snapshot_patcher.start()
        self.addCleanup(self._snapshot_patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cfg(self, hosts):
        """Use a real config with every writable path scoped to this test."""
        from freq.core.config import FreqConfig

        cfg = FreqConfig()
        cfg.hosts = hosts
        cfg.conf_dir = os.path.join(self.tmpdir, "conf")
        cfg.data_dir = os.path.join(self.tmpdir, "data")
        cfg.credentials_dir = os.path.join(self.tmpdir, "credentials")
        cfg.key_dir = os.path.join(self.tmpdir, "keys")
        cfg.ssh_key_path = self.key_path
        cfg.ssh_rsa_key_path = self.key_path
        for path in (cfg.conf_dir, cfg.data_dir, cfg.credentials_dir, cfg.key_dir):
            os.makedirs(path, exist_ok=True)
        Path(cfg.conf_dir, "freq.toml").write_text('[ssh]\nlegacy_password_file = ""\n')
        return cfg

    def _make_args(self, device_credentials=None, bootstrap_key=None, bootstrap_user=None, hosts_file=None):
        args = MagicMock()
        args.device_credentials = device_credentials
        args.bootstrap_key = bootstrap_key
        args.bootstrap_user = bootstrap_user
        args.hosts_file = hosts_file
        return args

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._load_device_credentials")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_fleet_deploy_uses_device_creds_for_pfsense(self, mock_fmt, mock_input, mock_load_dc, mock_dispatch):
        """pfSense host uses credentials from --device-credentials, skipping interactive prompt."""
        host = MagicMock(ip="10.0.0.1", label="fw01", htype="pfsense")
        host.category = "firewall"
        cfg = self._make_cfg([host])

        mock_load_dc.return_value = {
            "pfsense": {"user": "admin", "password": "fw-secret"},
        }
        mock_dispatch.return_value = True

        args = self._make_args(device_credentials="/fake/creds.toml")
        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        from freq.modules.init_cmd import _phase_fleet_deploy
        _phase_fleet_deploy(cfg, ctx, args)

        # Dispatch called with password from device creds, not interactive
        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args[0]
        self.assertEqual(call_args[0], "10.0.0.1")       # ip
        self.assertEqual(call_args[1], "pfsense")         # htype
        self.assertEqual(call_args[3], "fw-secret")       # auth_pass from device creds
        self.assertEqual(call_args[4], "")                 # auth_key empty (password mode)
        self.assertEqual(call_args[5], "admin")            # auth_user from device creds

        # No interactive auth prompts for pfSense
        for call in mock_input.call_args_list:
            prompt = call[0][0] if call[0] else ""
            self.assertNotIn("pfSense", prompt)
            self.assertNotIn("Choice", prompt)

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._load_device_credentials")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_fleet_deploy_uses_device_key_for_pfsense(self, mock_fmt, mock_input, mock_load_dc, mock_dispatch):
        """pfSense device credentials may provide key auth from ssh_key_file."""
        host = MagicMock(ip="10.0.0.1", label="fw01", htype="pfsense")
        host.category = "firewall"
        cfg = self._make_cfg([host])

        mock_load_dc.return_value = {
            "pfsense": {"user": "freq-ops", "password": "", "key_path": "/home/freq-ops/.ssh/fleet_key"},
        }
        mock_dispatch.return_value = True

        args = self._make_args(device_credentials="/fake/creds.toml")
        ctx = {"svc_name": "dc01-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        from freq.modules.init_cmd import _phase_fleet_deploy
        _phase_fleet_deploy(cfg, ctx, args)

        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args[0]
        self.assertEqual(call_args[0], "10.0.0.1")
        self.assertEqual(call_args[1], "pfsense")
        self.assertEqual(call_args[3], "")
        self.assertEqual(call_args[4], "/home/freq-ops/.ssh/fleet_key")
        self.assertEqual(call_args[5], "freq-ops")

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._load_device_credentials")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_fleet_deploy_uses_device_creds_per_htype(self, mock_fmt, mock_input, mock_load_dc, mock_dispatch):
        """iDRAC and switch get different credentials from device_creds dict."""
        idrac_host = MagicMock(ip="10.0.0.2", label="idrac01", htype="idrac")
        idrac_host.category = "bmc"
        switch_host = MagicMock(ip="10.0.0.3", label="sw01", htype="switch")
        switch_host.category = "switch"
        cfg = self._make_cfg([idrac_host, switch_host])

        mock_load_dc.return_value = {
            "idrac": {"user": "root", "password": "idrac-pass"},
            "switch": {"user": "gigecolo", "password": "switch-pass"},
        }
        mock_dispatch.return_value = True

        args = self._make_args(device_credentials="/fake/creds.toml")
        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        from freq.modules.init_cmd import _phase_fleet_deploy
        _phase_fleet_deploy(cfg, ctx, args)

        # Both dispatched with their own creds
        self.assertEqual(mock_dispatch.call_count, 2)
        calls = mock_dispatch.call_args_list

        # iDRAC call
        idrac_call = [c for c in calls if c[0][1] == "idrac"][0]
        self.assertEqual(idrac_call[0][3], "idrac-pass")   # password
        self.assertEqual(idrac_call[0][5], "root")          # user

        # Switch call
        switch_call = [c for c in calls if c[0][1] == "switch"][0]
        self.assertEqual(switch_call[0][3], "switch-pass")  # password
        self.assertEqual(switch_call[0][5], "gigecolo")      # user

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._load_device_credentials")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_fleet_deploy_device_creds_over_bootstrap(self, mock_fmt, mock_input, mock_load_dc, mock_dispatch):
        """--device-credentials takes priority over --bootstrap-key for devices."""
        host = MagicMock(ip="10.0.0.1", label="fw01", htype="pfsense")
        host.category = "firewall"
        cfg = self._make_cfg([host])

        mock_load_dc.return_value = {
            "pfsense": {"user": "admin", "password": "creds-password"},
        }
        mock_dispatch.return_value = True

        # Both device creds AND bootstrap key provided
        args = self._make_args(
            device_credentials="/fake/creds.toml",
            bootstrap_key=self.key_path,
            bootstrap_user="root",
        )
        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        from freq.modules.init_cmd import _phase_fleet_deploy
        _phase_fleet_deploy(cfg, ctx, args)

        # Device creds win — password auth used, not bootstrap key
        call_args = mock_dispatch.call_args[0]
        self.assertEqual(call_args[3], "creds-password")  # password from device creds
        self.assertEqual(call_args[4], "")                 # NOT the bootstrap key
        self.assertEqual(call_args[5], "admin")            # user from device creds

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._load_device_credentials")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_fleet_deploy_mixed_creds(self, mock_fmt, mock_input, mock_load_dc, mock_dispatch):
        """Devices with creds use them; devices without fall back to bootstrap key."""
        idrac_host = MagicMock(ip="10.0.0.2", label="idrac01", htype="idrac")
        idrac_host.category = "bmc"
        switch_host = MagicMock(ip="10.0.0.3", label="sw01", htype="switch")
        switch_host.category = "switch"
        cfg = self._make_cfg([idrac_host, switch_host])

        # Only iDRAC has device creds — switch does not
        mock_load_dc.return_value = {
            "idrac": {"user": "root", "password": "idrac-pass"},
        }
        mock_dispatch.return_value = True

        args = self._make_args(
            device_credentials="/fake/creds.toml",
            bootstrap_key=self.key_path,
            bootstrap_user="root",
        )
        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        from freq.modules.init_cmd import _phase_fleet_deploy
        _phase_fleet_deploy(cfg, ctx, args)

        self.assertEqual(mock_dispatch.call_count, 2)
        calls = mock_dispatch.call_args_list

        # iDRAC: uses device creds (password)
        idrac_call = [c for c in calls if c[0][1] == "idrac"][0]
        self.assertEqual(idrac_call[0][3], "idrac-pass")  # password from creds
        self.assertEqual(idrac_call[0][4], "")              # no key

        # Switch: falls back to bootstrap key
        switch_call = [c for c in calls if c[0][1] == "switch"][0]
        self.assertEqual(switch_call[0][3], "")              # no password
        self.assertEqual(switch_call[0][4], self.key_path)   # bootstrap key
        self.assertEqual(switch_call[0][5], "root")          # bootstrap user


# ═══════════════════════════════════════════════════════════════════
# --hosts-file import tests
# ═══════════════════════════════════════════════════════════════════

class TestHostsFileImport(unittest.TestCase):
    """Test that --hosts-file imports fleet hosts into cfg before deployment."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-hostsfile-")
        # Create a hosts.conf with test entries
        self.hosts_file = os.path.join(self.tmpdir, "hosts.conf")
        with open(self.hosts_file, "w") as f:
            f.write("10.0.0.10  testhost  linux\n")
            f.write("10.0.0.11  docker01  docker\n")
        # Create the target hosts_file location cfg will point to
        self.cfg_hosts_file = os.path.join(self.tmpdir, "hosts-target.conf")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("freq.modules.init_cmd.getpass")
    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_hosts_file_imports_hosts(self, mock_fmt, mock_input, mock_dispatch, mock_getpass):
        """--hosts-file copies hosts.conf and loads hosts into cfg."""
        cfg = MagicMock()
        cfg.hosts = []  # Empty — no hosts registered yet
        cfg.hosts_file = self.cfg_hosts_file

        args = MagicMock()
        args.hosts_file = self.hosts_file
        args.bootstrap_key = None
        args.bootstrap_user = None
        args.device_credentials = None

        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        # Mock load_hosts to return parsed host objects
        host1 = MagicMock(ip="10.0.0.10", label="testhost", htype="linux")
        host1.category = "server"
        host2 = MagicMock(ip="10.0.0.11", label="docker01", htype="docker")
        host2.category = "server"

        mock_getpass.getpass.return_value = "testpass"
        mock_dispatch.return_value = True

        with patch("freq.core.config.load_hosts", return_value=[host1, host2]):
            # Auth prompts: deploy user, auth choice, then getpass handles password
            mock_input.side_effect = [
                "root",    # Deploy as user
                "A",       # Auth choice (password)
            ]

            from freq.modules.init_cmd import _phase_fleet_deploy
            try:
                _phase_fleet_deploy(cfg, ctx, args)
            except StopIteration:
                pass  # Input exhaustion is fine — we're testing the import

        # Verify hosts.conf was copied to cfg's hosts_file location
        self.assertTrue(os.path.isfile(self.cfg_hosts_file))
        with open(self.cfg_hosts_file) as f:
            content = f.read()
        self.assertIn("testhost", content)
        self.assertIn("docker01", content)

    @patch("freq.modules.init_cmd.getpass")
    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_hosts_file_skips_if_hosts_already_registered(self, mock_fmt, mock_input, mock_dispatch, mock_getpass):
        """--hosts-file does NOT overwrite if cfg.hosts is already populated."""
        cfg = MagicMock()
        cfg.hosts = [MagicMock(ip="10.0.0.99", label="existing", htype="linux")]
        cfg.hosts_file = self.cfg_hosts_file

        args = MagicMock()
        args.hosts_file = self.hosts_file
        args.bootstrap_key = None
        args.bootstrap_user = None
        args.device_credentials = None

        ctx = {"svc_name": "freq-admin", "svc_pass": "test", "ed25519_pub": "ssh-ed25519 AAAA"}

        mock_getpass.getpass.return_value = "testpass"
        mock_dispatch.return_value = True
        mock_input.side_effect = [
            "root",  # Deploy as user
            "A",     # Auth choice
        ]

        from freq.modules.init_cmd import _phase_fleet_deploy
        try:
            _phase_fleet_deploy(cfg, ctx, args)
        except StopIteration:
            pass

        # hosts-target.conf should NOT have been created (import skipped)
        self.assertFalse(os.path.isfile(self.cfg_hosts_file))


class TestPhaseDiscoverScopedHosts(unittest.TestCase):
    """Discovery must not pollute a curated --hosts-file run."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-discover-scope-")
        self.hosts_file = os.path.join(self.tmpdir, "hosts.toml")
        with open(self.hosts_file, "w") as f:
            f.write('[[host]]\n')
            f.write('ip = "10.25.255.25"\n')
            f.write('label = "truenas"\n')
            f.write('type = "truenas"\n')
            f.write('groups = "infrastructure"\n')
        self.cfg_hosts_file = os.path.join(self.tmpdir, "hosts-target.toml")
        self.freq_toml = os.path.join(self.tmpdir, "freq.toml")
        self.boundaries = os.path.join(self.tmpdir, "fleet-boundaries.toml")
        with open(self.freq_toml, "w") as f:
            f.write("[freq]\nversion = \"test\"\n\n[ssh]\nlegacy_password_file = \"\"\n\n[infrastructure]\n")
        with open(self.boundaries, "w") as f:
            f.write("")
        # MagicMock config attributes are truthy by default.  Without an
        # explicit transport boundary these SSH-fallback tests accidentally
        # attempt PVE HTTPS with a fake MagicMock token before exercising the
        # mocked command path.
        self._pve_api_patcher = patch(
            "freq.modules.pve._pve_api_call", return_value=("", False)
        )
        self._pve_api_patcher.start()
        self.addCleanup(self._pve_api_patcher.stop)
        self._scan_patcher = patch(
            "freq.modules.discover.scan_and_identify", return_value=([], [])
        )
        self._scan_patcher.start()
        self.addCleanup(self._scan_patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.core.config.append_host_toml")
    def _case_hosts_file_prevents_headless_auto_registration(self, mock_append, mock_run, mock_fmt):
        from freq.modules.init_cmd import _phase_fleet_discover

        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.hosts_file = self.cfg_hosts_file
        cfg.hosts = []
        cfg.pve_nodes = ["10.25.255.26"]
        cfg.pve_node_names = ["pve01"]
        cfg.vlans = []
        cfg.vm_gateway = ""
        cfg.pfsense_ip = ""
        cfg.truenas_ip = ""
        cfg.switch_ip = ""
        cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})

        ctx = {"key_path": "/tmp/fake", "svc_name": "freq-admin"}
        args = MagicMock(headless=True, hosts_file=self.hosts_file)
        args.device_credentials = None

        vm_list = '[{"vmid":5001,"name":"truenas-lab","status":"running","type":"qemu","node":"pve01"}]'
        agent_ips = '{"result":[{"name":"eth0","ip-addresses":[{"ip-address-type":"ipv4","ip-address":"192.168.255.25"}]}]}'

        def run_side_effect(cmd, timeout=30):
            cmd_str = " ".join(cmd)
            if "/cluster/resources --type vm" in cmd_str:
                return 0, vm_list, ""
            if "qm agent 5001 network-get-interfaces" in cmd_str:
                return 0, agent_ips, ""
            return 1, "", "not mocked"

        mock_run.side_effect = run_side_effect

        _phase_fleet_discover(cfg, ctx, args)

        mock_append.assert_not_called()

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.discover.scan_and_identify")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.hosts._auto_populate_fleet_boundaries")
    def _case_pve_guest_name_remains_unknown_inventory_only(
        self, mock_auto_boundaries, mock_run, mock_scan, mock_fmt
    ):
        from freq.modules.init_cmd import _phase_fleet_discover

        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.hosts_file = self.cfg_hosts_file
        cfg.hosts = []
        cfg.pve_nodes = ["10.25.255.26"]
        cfg.pve_node_names = ["pve01"]
        cfg.vlans = []
        cfg.vm_gateway = ""
        cfg.pfsense_ip = ""
        cfg.truenas_ip = ""
        cfg.switch_ip = ""
        cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})

        ctx = {"key_path": "/tmp/fake", "svc_name": "freq-admin"}
        args = types.SimpleNamespace(headless=True, hosts_file=None, device_credentials=None)

        vm_list = '[{"vmid":102,"name":"arr-stack","status":"running","type":"qemu","node":"pve01"}]'
        agent_ips = '{"result":[{"name":"eth0","ip-addresses":[{"ip-address-type":"ipv4","ip-address":"192.168.255.31"}]}]}'

        def run_side_effect(cmd, timeout=30):
            cmd_str = " ".join(cmd)
            if "/cluster/resources --type vm" in cmd_str:
                return 0, vm_list, ""
            if "qm agent 102 network-get-interfaces" in cmd_str:
                return 0, agent_ips, ""
            return 1, "", "not mocked"

        mock_run.side_effect = run_side_effect
        mock_scan.return_value = ([], [])

        _phase_fleet_discover(cfg, ctx, args)

        self.assertFalse(any(h.label == "arr-stack" for h in cfg.hosts))
        self.assertTrue(any(h.label == "pve01" and h.htype == "pve" for h in cfg.hosts))
        discovered = mock_auto_boundaries.call_args.args[1]
        self.assertEqual(
            discovered["192.168.255.31"],
            {
                "label": "arr-stack",
                "htype": "unknown",
                "groups": "",
                "vmid": 102,
                "pve_node": "pve01",
                "pve_node_ip": "10.25.255.26",
                "source": "pve-api",
                "managed": False,
                "all_ips": ["192.168.255.31"],
            },
        )
        self.assertEqual(cfg.truenas_ip, "")
        with open(self.freq_toml) as f:
            self.assertNotIn('truenas_ip = "192.168.255.31"', f.read())

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.discover.scan_and_identify")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.hosts._auto_populate_fleet_boundaries")
    def _case_vlan_scan_observation_remains_unknown_inventory_only(
        self, mock_auto_boundaries, mock_run, mock_scan, mock_fmt
    ):
        from freq.modules.init_cmd import _phase_fleet_discover

        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.hosts_file = self.cfg_hosts_file
        cfg.hosts = []
        cfg.pve_nodes = []
        cfg.pve_node_names = []
        cfg.vlans = [types.SimpleNamespace(id=10, name="Lab/Dev", prefix="10.25.10")]
        cfg.vm_gateway = ""
        cfg.pfsense_ip = ""
        cfg.truenas_ip = ""
        cfg.switch_ip = ""
        cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})

        ctx = {"key_path": "/tmp/fake", "svc_name": "freq-admin"}
        args = types.SimpleNamespace(
            headless=True, hosts_file=None, device_credentials=None
        )
        mock_run.return_value = (1, "", "not mocked")
        mock_scan.return_value = (
            ["10.25.10.5"],
            [{
                "ip": "10.25.10.5",
                "reachable": True,
                "hostname": "switch-lab",
                "type": "switch",
            }],
        )

        _phase_fleet_discover(cfg, ctx, args)

        self.assertEqual(cfg.hosts, [])
        discovered = mock_auto_boundaries.call_args.args[1]
        self.assertEqual(
            discovered,
            {
                "10.25.10.5": {
                    "label": "switch-lab",
                    "htype": "unknown",
                    "groups": "",
                    "vmid": 0,
                    "source": "vlan-scan",
                    "managed": False,
                    "all_ips": ["10.25.10.5"],
                }
            },
        )

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.discover.scan_and_identify")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.hosts._auto_populate_fleet_boundaries")
    def _case_configured_gateway_credentials_override_unknown_vlan_row(
        self, mock_auto_boundaries, mock_run, mock_scan, mock_fmt
    ):
        from freq.modules.init_cmd import _phase_fleet_discover

        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.hosts_file = self.cfg_hosts_file
        cfg.hosts = []
        cfg.pve_nodes = []
        cfg.pve_node_names = []
        cfg.vlans = [types.SimpleNamespace(id=10, name="Management", prefix="10.25.10")]
        cfg.vm_gateway = "10.25.10.1"
        cfg.pfsense_ip = ""
        cfg.truenas_ip = ""
        cfg.switch_ip = ""
        cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})

        ctx = {
            "key_path": "/tmp/fake",
            "svc_name": "freq-admin",
            "device_creds": {
                "pfsense": {
                    "user": "admin",
                    "password": "secret",
                    "host": "10.25.10.1",
                    "label": "firewall",
                }
            },
        }
        args = types.SimpleNamespace(
            headless=True, hosts_file=None, device_credentials=None
        )
        mock_run.return_value = (1, "", "not mocked")
        mock_scan.return_value = (
            ["10.25.10.1"],
            [{
                "ip": "10.25.10.1",
                "reachable": True,
                "hostname": "firewall",
                "type": "pfsense",
            }],
        )

        _phase_fleet_discover(cfg, ctx, args)

        self.assertEqual(
            [(h.ip, h.label, h.htype, h.groups, h.managed) for h in cfg.hosts],
            [("10.25.10.1", "firewall", "pfsense", "management,infrastructure", True)],
        )
        self.assertEqual(cfg.pfsense_ip, "10.25.10.1")
        self.assertEqual(
            mock_auto_boundaries.call_args.args[1]["10.25.10.1"],
            {
                "label": "firewall",
                "htype": "pfsense",
                "groups": "management,infrastructure",
                "vmid": 0,
                "source": "vlan-scan",
                "managed": True,
                "all_ips": ["10.25.10.1"],
                "scope": "core",
            },
        )

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.discover.scan_and_identify")
    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.hosts._auto_populate_fleet_boundaries")
    def _case_well_known_address_probes_remain_unknown_inventory_only(
        self, mock_auto_boundaries, mock_run, mock_scan, mock_fmt
    ):
        from freq.modules.init_cmd import _phase_fleet_discover

        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.hosts_file = self.cfg_hosts_file
        cfg.hosts = []
        cfg.pve_nodes = ["10.25.255.26"]
        cfg.pve_node_names = ["pve01"]
        cfg.vlans = []
        cfg.vm_gateway = ""
        cfg.pfsense_ip = ""
        cfg.truenas_ip = ""
        cfg.switch_ip = ""
        cfg.pve_api_token_id = ""
        cfg.pve_api_token_secret = ""
        cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})

        ctx = {"key_path": "/tmp/fake", "svc_name": "freq-admin"}
        args = types.SimpleNamespace(
            headless=True, hosts_file=None, device_credentials=None
        )
        mock_scan.return_value = ([], [])

        def run_side_effect(cmd, timeout=30):
            cmd_str = " ".join(cmd)
            if "pvesh get /cluster/resources" in cmd_str:
                return 1, "", "not mocked"
            if cmd[:2] == ["ping", "-c"]:
                target = cmd[-1]
                if target in {"10.25.255.5", "10.25.255.10", "10.25.255.11", "10.25.255.25"}:
                    return 0, "", ""
                return 1, "", "unreachable"
            if "racadm getversion" in cmd_str:
                if "root@10.25.255.10" in cmd_str:
                    return 0, "iDRAC version 7.00", ""
                return 1, "", "not racadm"
            return 1, "", "not mocked"

        mock_run.side_effect = run_side_effect

        _phase_fleet_discover(cfg, ctx, args)

        self.assertEqual(
            [(host.ip, host.label, host.htype, host.managed) for host in cfg.hosts],
            [("10.25.255.26", "pve01", "pve", True)],
        )
        discovered = mock_auto_boundaries.call_args.args[1]
        self.assertEqual(
            discovered,
            {
                "10.25.255.26": {
                    "label": "pve01",
                    "htype": "pve",
                    "groups": "cluster",
                    "vmid": 0,
                    "source": "configured-pve",
                    "managed": True,
                    "all_ips": ["10.25.255.26"],
                },
                "10.25.255.10": {
                    "label": "host-10",
                    "htype": "unknown",
                    "groups": "",
                    "vmid": 0,
                    "source": "infra-probe",
                    "managed": False,
                    "all_ips": ["10.25.255.10"],
                    "observed_type": "idrac",
                },
                "10.25.255.11": {
                    "label": "host-11",
                    "htype": "unknown",
                    "groups": "",
                    "vmid": 0,
                    "source": "infra-probe-ping",
                    "managed": False,
                    "all_ips": ["10.25.255.11"],
                },
                "10.25.255.5": {
                    "label": "host-5",
                    "htype": "unknown",
                    "groups": "",
                    "vmid": 0,
                    "source": "infra-probe-ping",
                    "managed": False,
                    "all_ips": ["10.25.255.5"],
                },
                "10.25.255.25": {
                    "label": "host-25",
                    "htype": "unknown",
                    "groups": "",
                    "vmid": 0,
                    "source": "infra-probe-ping",
                    "managed": False,
                    "all_ips": ["10.25.255.25"],
                },
            },
        )
        self.assertEqual(cfg.switch_ip, "")
        self.assertEqual(cfg.truenas_ip, "")

    def _case_device_credentials_parse_physical_scope(self):
        from freq.modules.init_cmd import _load_device_credentials

        cred_path = os.path.join(self.tmpdir, "device-credentials.toml")
        pw_path = os.path.join(self.tmpdir, "pw")
        with open(pw_path, "w") as f:
            f.write("secret")
        with open(cred_path, "w") as f:
            f.write("[pfsense]\n")
            f.write('host = "10.25.10.1"\n')
            f.write('user = "admin"\n')
            f.write(f'password_file = "{pw_path}"\n')
            f.write('scope = "lab"\n')
            f.write('label = "lab-firewall"\n')

        creds = _load_device_credentials(cred_path)

        self.assertEqual(creds["pfsense"]["scope"], "lab")
        self.assertEqual(creds["pfsense"]["label"], "lab-firewall")

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.discover.scan_and_identify")
    @patch("freq.modules.init_cmd._run")
    def _case_lab_scoped_physical_credentials_do_not_write_core_infra(self, mock_run, mock_scan, mock_fmt):
        from freq.modules.init_cmd import _phase_fleet_discover

        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.hosts_file = self.cfg_hosts_file
        cfg.hosts = []
        cfg.pve_nodes = ["10.25.255.26"]
        cfg.pve_node_names = ["pve01"]
        cfg.vlans = []
        cfg.vm_gateway = ""
        cfg.pfsense_ip = ""
        cfg.truenas_ip = ""
        cfg.switch_ip = ""
        cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})
        cfg.pve_api_token_id = ""
        cfg.pve_api_token_secret = ""

        ctx = {
            "key_path": "/tmp/fake",
            "svc_name": "freq-admin",
            "device_creds": {
                "pfsense": {
                    "user": "admin",
                    "password": "secret",
                    "host": "10.25.10.1",
                    "scope": "lab",
                    "label": "lab-firewall",
                },
                "truenas": {
                    "user": "root",
                    "password": "secret",
                    "host": "10.25.10.201",
                    "scope": "lab",
                    "label": "lab-truenas",
                },
            },
        }
        args = types.SimpleNamespace(
            headless=True,
            hosts_file=None,
            device_credentials=None,
            core_devices=None,
            lab_devices=None,
        )

        mock_run.return_value = (1, "", "not mocked")
        mock_scan.return_value = ([], [])

        _phase_fleet_discover(cfg, ctx, args)

        self.assertEqual(cfg.pfsense_ip, "")
        self.assertEqual(cfg.truenas_ip, "")
        self.assertTrue(any(h.label == "lab-firewall" and "lab" in h.groups for h in cfg.hosts))
        self.assertTrue(any(h.label == "lab-truenas" and "lab" in h.groups for h in cfg.hosts))

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.discover.scan_and_identify")
    @patch("freq.modules.init_cmd._run")
    def _case_device_credential_host_merges_pve_multinic_discovery(self, mock_run, mock_scan, mock_fmt):
        from freq.modules.init_cmd import _phase_fleet_discover

        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.hosts_file = self.cfg_hosts_file
        cfg.hosts = []
        cfg.pve_nodes = ["10.25.255.26"]
        cfg.pve_node_names = ["pve01"]
        cfg.vlans = []
        cfg.vm_gateway = ""
        cfg.pfsense_ip = ""
        cfg.truenas_ip = ""
        cfg.switch_ip = ""
        cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})
        cfg.pve_api_token_id = ""
        cfg.pve_api_token_secret = ""

        ctx = {
            "key_path": "/tmp/fake",
            "svc_name": "freq-admin",
            "device_creds": {
                "truenas-lab": {"user": "root", "password": "secret", "host": "10.25.10.201"},
            },
        }
        args = types.SimpleNamespace(headless=True, hosts_file=None, device_credentials=None)

        vm_list = '[{"vmid":5001,"name":"truenas-lab","status":"running","type":"qemu","node":"pve01"}]'
        agent_ips = (
            '{"result":[{"name":"eth0","ip-addresses":['
            '{"ip-address-type":"ipv4","ip-address":"192.168.255.25"},'
            '{"ip-address-type":"ipv4","ip-address":"192.168.25.25"},'
            '{"ip-address-type":"ipv4","ip-address":"10.25.10.201"}]}]}'
        )

        def run_side_effect(cmd, timeout=30):
            cmd_str = " ".join(cmd)
            if "/cluster/resources --type vm" in cmd_str:
                return 0, vm_list, ""
            if "qm agent 5001 network-get-interfaces" in cmd_str:
                return 0, agent_ips, ""
            return 1, "", "not mocked"

        mock_run.side_effect = run_side_effect
        mock_scan.return_value = ([], [])

        _phase_fleet_discover(cfg, ctx, args)

        lab_hosts = [h for h in cfg.hosts if h.label == "truenas-lab"]
        self.assertEqual(len(lab_hosts), 1)
        self.assertEqual(lab_hosts[0].ip, "10.25.10.201")
        self.assertEqual(lab_hosts[0].vmid, 5001)
        self.assertTrue(lab_hosts[0].managed)
        self.assertIn("192.168.255.25", lab_hosts[0].all_ips)
        self.assertIn("192.168.25.25", lab_hosts[0].all_ips)
        self.assertIn("10.25.10.201", lab_hosts[0].all_ips)
        self.assertFalse(any(h.ip == "192.168.255.25" for h in cfg.hosts))

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.discover.scan_and_identify")
    @patch("freq.modules.init_cmd._run")
    def _case_staged_core_devices_override_unknown_physical_probes(self, mock_run, mock_scan, mock_fmt):
        from freq.modules.init_cmd import _phase_fleet_discover

        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.hosts_file = self.cfg_hosts_file
        cfg.hosts = []
        cfg.pve_nodes = ["10.25.255.26"]
        cfg.pve_node_names = ["pve01"]
        cfg.vlans = []
        cfg.vm_gateway = ""
        cfg.pfsense_ip = ""
        cfg.truenas_ip = ""
        cfg.switch_ip = ""
        cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})

        ctx = {
            "key_path": "/tmp/fake",
            "svc_name": "freq-admin",
            "device_creds": {
                "pfsense-a1": {"type": "pfsense", "user": "freq-ops", "password": "", "key_path": "/tmp/fake", "host": "10.25.255.1", "label": "firewall"},
                "switch-b1": {"type": "switch", "user": "freq-ops", "password": "secret", "host": "10.25.255.5", "label": "switch"},
                "idrac": {"user": "freq-ops", "password": "secret", "hosts": ["10.25.255.10", "10.25.255.11"]},
                "truenas": {"api_key": "secret", "api_key_only": True, "host": "10.25.255.25"},
                "truenas-lab": {"api_key": "secret", "api_key_only": True, "host": "10.25.10.201"},
            },
        }
        args = types.SimpleNamespace(headless=True, hosts_file=None, device_credentials=None)

        def run_side_effect(cmd, timeout=30):
            cmd_str = " ".join(cmd)
            if cmd[:2] == ["ping", "-c"] and cmd[-1] in {
                "10.25.255.5", "10.25.255.10", "10.25.255.11",
            }:
                return 0, "", ""
            if "racadm getversion" in cmd_str and "root@10.25.255.10" in cmd_str:
                return 0, "iDRAC version 7.00", ""
            return 1, "", "not mocked"

        mock_run.side_effect = run_side_effect
        mock_scan.return_value = ([], [])

        _phase_fleet_discover(cfg, ctx, args)

        by_label = {h.label: h for h in cfg.hosts}
        self.assertIn("switch", by_label)
        self.assertIn("bmc-10", by_label)
        self.assertIn("bmc-11", by_label)
        self.assertIn("truenas", by_label)
        self.assertIn("truenas-lab", by_label)
        self.assertIn("firewall", by_label)
        self.assertTrue(by_label["firewall"].managed)
        self.assertTrue(by_label["truenas"].managed)
        self.assertTrue(by_label["truenas-lab"].managed)
        self.assertEqual(cfg.pfsense_ip, "10.25.255.1")
        self.assertEqual(cfg.switch_ip, "10.25.255.5")
        self.assertEqual(cfg.truenas_ip, "10.25.255.25")
        with open(self.freq_toml) as f:
            content = f.read()
        self.assertIn('pfsense_ip = "10.25.255.1"', content)
        self.assertIn('switch_ip = "10.25.255.5"', content)
        self.assertIn('truenas_ip = "10.25.255.25"', content)

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.discover.scan_and_identify")
    @patch("freq.modules.init_cmd._run")
    def _case_truenas_credentials_override_nexus_storage_vlan_discovery(self, mock_run, mock_scan, mock_fmt):
        from freq.modules.init_cmd import _phase_fleet_discover

        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.hosts_file = self.cfg_hosts_file
        cfg.hosts = []
        cfg.pve_nodes = ["10.25.255.26"]
        cfg.pve_node_names = ["pve01"]
        cfg.vlans = []
        cfg.vm_gateway = ""
        cfg.pfsense_ip = ""
        cfg.truenas_ip = ""
        cfg.switch_ip = ""
        cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})

        ctx = {
            "key_path": "/tmp/fake",
            "svc_name": "freq-admin",
            "device_creds": {
                "truenas": {"api_key": "secret", "api_key_only": True, "host": "10.25.255.25"},
            },
        }
        args = types.SimpleNamespace(headless=True, hosts_file=None, device_credentials=None)

        vm_list = '[{"vmid":108,"name":"nexus","status":"running","type":"qemu","node":"pve01"}]'
        agent_ips = '{"result":[{"name":"eth0","ip-addresses":[{"ip-address-type":"ipv4","ip-address":"10.25.255.8"},{"ip-address-type":"ipv4","ip-address":"10.25.25.8"}]}]}'

        def run_side_effect(cmd, timeout=30):
            cmd_str = " ".join(cmd)
            if "/cluster/resources --type vm" in cmd_str:
                return 0, vm_list, ""
            if "qm agent 108 network-get-interfaces" in cmd_str:
                return 0, agent_ips, ""
            return 1, "", "not mocked"

        mock_run.side_effect = run_side_effect
        mock_scan.return_value = ([], [])

        _phase_fleet_discover(cfg, ctx, args)

        by_label = {h.label: h for h in cfg.hosts}
        self.assertIn("truenas", by_label)
        self.assertEqual(by_label["truenas"].ip, "10.25.255.25")
        self.assertTrue(by_label["truenas"].managed)
        self.assertNotIn("nexus", by_label)
        self.assertEqual(cfg.truenas_ip, "10.25.255.25")
        with open(self.freq_toml) as f:
            content = f.read()
        self.assertIn('truenas_ip = "10.25.255.25"', content)
        self.assertNotIn('truenas_ip = "10.25.255.8"', content)

    @patch("freq.modules.init_cmd.fmt")
    @patch("freq.modules.discover.scan_and_identify")
    @patch("freq.modules.init_cmd._run")
    def _case_existing_pfsense_with_bootstrap_creds_stays_managed(self, mock_run, mock_scan, mock_fmt):
        from freq.core.config import Host, save_hosts_toml
        from freq.modules.init_cmd import _phase_fleet_discover

        firewall = Host(
            ip="10.25.255.1",
            label="firewall",
            htype="pfsense",
            groups="infrastructure",
            managed=True,
        )
        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.hosts_file = self.cfg_hosts_file
        cfg.hosts = [firewall]
        save_hosts_toml(cfg.hosts_file, cfg.hosts)
        cfg.pve_nodes = ["10.25.255.26"]
        cfg.pve_node_names = ["pve01"]
        cfg.vlans = []
        cfg.vm_gateway = "10.25.255.1"
        cfg.pfsense_ip = ""
        cfg.truenas_ip = ""
        cfg.switch_ip = ""
        cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})

        ctx = {
            "key_path": "/tmp/fake",
            "svc_name": "freq-admin",
            "device_creds": {
                "pfsense": {"user": "freq-ops", "password": "", "key_path": "/tmp/fake", "host": "10.25.255.1"},
            },
        }
        args = types.SimpleNamespace(headless=True, hosts_file=None, device_credentials=None)

        mock_run.return_value = (1, "", "not mocked")
        mock_scan.return_value = ([], [])

        _phase_fleet_discover(cfg, ctx, args)

        self.assertTrue(cfg.hosts[0].managed)
        with open(cfg.hosts_file) as f:
            self.assertNotIn("managed = false", f.read())

    @patch("freq.modules.vault._vault_key", return_value="0" * 64)
    def _case_truenas_vault_seeding_preserves_core_and_lab_namespaces(self, _mock_key):
        from freq.modules.init_cmd import _seed_truenas_api_key_from_device_creds
        from freq.modules.vault import vault_get

        cfg = types.SimpleNamespace(
            vault_dir=os.path.join(self.tmpdir, "vault"),
            vault_file=os.path.join(self.tmpdir, "vault", "vault.enc"),
            truenas_ip="10.25.255.25",
            fleet_boundaries=types.SimpleNamespace(physical={}),
        )
        _seed_truenas_api_key_from_device_creds(
            cfg,
            {
                "truenas": {"api_key": "prod-secret"},
                "truenas-lab": {"api_key": "lab-secret"},
            },
        )

        self.assertEqual(vault_get(cfg, "truenas", "api_key"), "prod-secret")
        self.assertEqual(vault_get(cfg, "truenas-lab", "api_key"), "lab-secret")


PHASE_DISCOVER_SCOPED_HOSTS_CASES = (
    "_case_hosts_file_prevents_headless_auto_registration",
    "_case_pve_guest_name_remains_unknown_inventory_only",
    "_case_vlan_scan_observation_remains_unknown_inventory_only",
    "_case_configured_gateway_credentials_override_unknown_vlan_row",
    "_case_well_known_address_probes_remain_unknown_inventory_only",
    "_case_device_credentials_parse_physical_scope",
    "_case_lab_scoped_physical_credentials_do_not_write_core_infra",
    "_case_device_credential_host_merges_pve_multinic_discovery",
    "_case_staged_core_devices_override_unknown_physical_probes",
    "_case_truenas_credentials_override_nexus_storage_vlan_discovery",
    "_case_existing_pfsense_with_bootstrap_creds_stays_managed",
    "_case_truenas_vault_seeding_preserves_core_and_lab_namespaces",
)


class TestPhaseDiscoverScopedHostsMatrix(unittest.TestCase):
    def test_phase_discover_scoped_hosts_matrix(self):
        run_case_matrix(self, TestPhaseDiscoverScopedHosts, PHASE_DISCOVER_SCOPED_HOSTS_CASES)


# ═══════════════════════════════════════════════════════════════════
# Config reload fix — load_config() instead of FreqConfig()
# ═══════════════════════════════════════════════════════════════════

class TestConfigReload(unittest.TestCase):
    """Test that _phase_configure reloads config via load_config() after writing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-reload-")
        self.toml_path = os.path.join(self.tmpdir, "freq.toml")
        with open(self.toml_path, "w") as f:
            f.write(
                "[freq]\n"
                'version = "2.0.0"\n'
                "\n"
                "[ssh]\n"
                'mode = "sudo"\n'
                "\n"
                "[pve]\n"
                "# nodes = []\n"
                "\n"
                "[vm.defaults]\n"
                '# gateway = ""\n'
                '# nameserver = "1.1.1.1"\n'
                "\n"
                "[infrastructure]\n"
                '# cluster_name = ""\n'
            )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("freq.core.config.load_config")
    @patch("freq.modules.init_cmd._input")
    @patch("freq.modules.init_cmd.fmt")
    def test_reload_uses_load_config(self, mock_fmt, mock_input, mock_lc):
        """After writing freq.toml, reload calls load_config(install_dir)."""
        cfg = MagicMock()
        cfg.conf_dir = self.tmpdir
        cfg.install_dir = "/opt/freq"
        cfg.pve_nodes = []
        cfg.pve_node_names = []
        cfg.vm_gateway = ""
        cfg.vm_nameserver = ""
        cfg.cluster_name = ""
        cfg.ssh_mode = "sudo"
        cfg.pve_storage = {}

        mock_input.side_effect = [
            "10.0.0.1",   # PVE node IP
            "pve01",       # Node name
            "local-lvm",   # Storage
            "10.0.0.1",   # Gateway
            "1.1.1.1",    # Nameserver
            "test",        # Cluster name
            "sudo",        # SSH mode
        ]

        reloaded_cfg = MagicMock()
        reloaded_cfg.pve_nodes = ["10.0.0.1"]
        reloaded_cfg.pve_node_names = ["pve01"]
        reloaded_cfg.vm_gateway = "10.0.0.1"
        reloaded_cfg.vm_nameserver = "1.1.1.1"
        reloaded_cfg.cluster_name = "test"
        reloaded_cfg.ssh_mode = "sudo"
        reloaded_cfg.pve_storage = {}
        mock_lc.return_value = reloaded_cfg

        from freq.modules.init_cmd import _phase_configure
        _phase_configure(cfg)

        # Verify load_config was called (not FreqConfig constructor)
        mock_lc.assert_called_once_with(cfg.install_dir)


if __name__ == "__main__":
    unittest.main()
