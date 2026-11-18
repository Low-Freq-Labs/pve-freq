"""FREQ Module Tests — Tests for vault, users, engine, risk, and notify.

Tests that all modules load, produce correct output types, and handle edge cases.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestVault(unittest.TestCase):
    """Test encrypted vault operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from freq.core.config import FreqConfig
        self.cfg = FreqConfig()
        self.cfg.vault_dir = self.tmpdir
        self.cfg.vault_file = os.path.join(self.tmpdir, "test-vault.enc")
        self.cfg.data_dir = self.tmpdir
        # Mock _vault_key so tests work on distros without /etc/machine-id
        self._patcher = patch(
            "freq.modules.vault._vault_key",
            return_value="a" * 64,
        )
        self._patcher.start()

    def tearDown(self):
        import shutil
        self._patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_vault_init(self):
        from freq.modules.vault import vault_init
        result = vault_init(self.cfg)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(self.cfg.vault_file))

    def test_vault_set_get(self):
        from freq.modules.vault import vault_init, vault_set, vault_get
        vault_init(self.cfg)
        vault_set(self.cfg, "DEFAULT", "test-key", "test-value")
        result = vault_get(self.cfg, "DEFAULT", "test-key")
        self.assertEqual(result, "test-value")

    def test_vault_get_missing(self):
        from freq.modules.vault import vault_init, vault_get
        vault_init(self.cfg)
        result = vault_get(self.cfg, "DEFAULT", "nonexistent")
        self.assertEqual(result, "")

    def test_vault_delete(self):
        from freq.modules.vault import vault_init, vault_set, vault_delete, vault_get
        vault_init(self.cfg)
        vault_set(self.cfg, "DEFAULT", "del-key", "del-value")
        result = vault_delete(self.cfg, "DEFAULT", "del-key")
        self.assertTrue(result)
        self.assertEqual(vault_get(self.cfg, "DEFAULT", "del-key"), "")

    def test_vault_list(self):
        from freq.modules.vault import vault_init, vault_set, vault_list
        vault_init(self.cfg)
        vault_set(self.cfg, "DEFAULT", "key1", "val1")
        vault_set(self.cfg, "DEFAULT", "key2", "val2")
        entries = vault_list(self.cfg)
        self.assertEqual(len(entries), 2)

    def test_vault_host_fallback(self):
        from freq.modules.vault import vault_init, vault_set, vault_get
        vault_init(self.cfg)
        vault_set(self.cfg, "DEFAULT", "api-key", "default-key")
        vault_set(self.cfg, "pve01", "api-key", "pve01-key")
        self.assertEqual(vault_get(self.cfg, "pve01", "api-key"), "pve01-key")
        self.assertEqual(vault_get(self.cfg, "unknown", "api-key"), "default-key")


class TestUsers(unittest.TestCase):
    """Test user management."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from freq.core.config import FreqConfig
        self.cfg = FreqConfig()
        self.cfg.conf_dir = self.tmpdir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_load_users(self):
        import stat

        from freq.modules.users import _load_users, _save_users, _save_users_error
        from freq.services import user_registry

        users = [
            {"username": "admin", "role": "admin", "groups": ""},
            {"username": "operator", "role": "operator", "groups": "fleet"},
        ]
        _save_users(self.cfg, users)
        loaded = _load_users(self.cfg)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["username"], "admin")
        users_path = Path(self.cfg.conf_dir, "users.conf")
        original = users_path.read_bytes()
        self.assertEqual(stat.S_IMODE(users_path.stat().st_mode), 0o600)

        events = []
        real_fchmod = user_registry.os.fchmod
        real_fsync = user_registry.os.fsync
        real_replace = user_registry.os.replace

        def tracked_fchmod(fd, mode):
            events.append(("fchmod", mode))
            return real_fchmod(fd, mode)

        def tracked_fsync(fd):
            events.append(("fsync", fd))
            return real_fsync(fd)

        def tracked_replace(source, destination):
            events.append(("replace", stat.S_IMODE(os.stat(source).st_mode)))
            return real_replace(source, destination)

        with patch.object(user_registry.os, "fchmod", side_effect=tracked_fchmod), patch.object(
            user_registry.os, "fsync", side_effect=tracked_fsync
        ), patch.object(user_registry.os, "replace", side_effect=tracked_replace):
            self.assertTrue(_save_users(self.cfg, users))
        names = [event[0] for event in events]
        self.assertLess(names.index("fchmod"), names.index("fsync"))
        self.assertLess(names.index("fsync"), names.index("replace"))
        self.assertEqual(next(event[1] for event in events if event[0] == "fchmod"), 0o600)
        self.assertEqual(next(event[1] for event in events if event[0] == "replace"), 0o600)
        self.assertEqual(stat.S_IMODE(users_path.stat().st_mode), 0o600)

        for fault_name, target in (("fchmod", "fchmod"), ("fsync", "fsync"), ("replace", "replace")):
            with self.subTest(fault=fault_name):
                users_path.write_bytes(original)
                os.chmod(users_path, 0o600)
                with patch.object(
                    user_registry.os,
                    target,
                    side_effect=OSError(f"{fault_name} blocked"),
                ):
                    error = _save_users_error(
                        self.cfg,
                        [{"username": "changed", "role": "admin", "groups": ""}],
                    )
                self.assertIn("blocked", error)
                self.assertEqual(users_path.read_bytes(), original)
                self.assertEqual(list(Path(self.cfg.conf_dir).glob(".users.conf.*")), [])

        users_path.write_bytes(original)
        with patch.object(
            user_registry,
            "_serialize_users",
            side_effect=OSError("write blocked"),
        ):
            self.assertIn("write blocked", _save_users_error(self.cfg, users))
        self.assertEqual(users_path.read_bytes(), original)
        self.assertEqual(list(Path(self.cfg.conf_dir).glob(".users.conf.*")), [])

        fsync_calls = 0

        def fail_directory_fsync(fd):
            nonlocal fsync_calls
            fsync_calls += 1
            if fsync_calls == 2:
                raise OSError("directory fsync blocked")
            return real_fsync(fd)

        committed = [{"username": "committed", "role": "admin", "groups": ""}]
        with patch.object(user_registry.os, "fsync", side_effect=fail_directory_fsync), patch.object(
            user_registry.logger, "warn"
        ) as warn:
            self.assertEqual(_save_users_error(self.cfg, committed), "")
        self.assertEqual(_load_users(self.cfg), committed)
        self.assertEqual(stat.S_IMODE(users_path.stat().st_mode), 0o600)
        self.assertEqual(list(Path(self.cfg.conf_dir).glob(".users.conf.*")), [])
        warn.assert_called_once()
        self.assertIn("committed but directory sync failed", warn.call_args.args[0])

    def test_valid_username(self):
        from freq.modules.users import _valid_username
        self.assertTrue(_valid_username("svc-admin"))
        self.assertTrue(_valid_username("user_01"))
        self.assertFalse(_valid_username(""))
        self.assertFalse(_valid_username("User"))  # uppercase
        self.assertFalse(_valid_username("a" * 33))  # too long

    def test_role_hierarchy(self):
        from freq.modules.users import _role_level
        self.assertLess(_role_level("viewer"), _role_level("operator"))
        self.assertLess(_role_level("operator"), _role_level("admin"))
        self.assertLess(_role_level("admin"), _role_level("protected"))


class TestPolicyEngine(unittest.TestCase):
    """Test the declarative policy engine."""

    def test_policy_executor_creation(self):
        from freq.engine.policy import PolicyExecutor
        policy = {
            "name": "test-policy",
            "scope": ["linux", "pve"],
            "resources": [],
        }
        ex = PolicyExecutor(policy)
        self.assertEqual(ex.name, "test-policy")
        self.assertEqual(ex.scope, ["linux", "pve"])

    def test_applies_to(self):
        from freq.engine.policy import PolicyExecutor
        from freq.core.types import Host
        policy = {"name": "test", "scope": ["linux", "docker"], "resources": []}
        ex = PolicyExecutor(policy)
        linux_host = Host(ip="1.1.1.1", label="test", htype="linux")
        pve_host = Host(ip="2.2.2.2", label="test2", htype="pve")
        self.assertTrue(ex.applies_to(linux_host))
        self.assertFalse(ex.applies_to(pve_host))

    def test_desired_state_platform_override(self):
        from freq.engine.policy import PolicyExecutor
        from freq.core.types import Host
        policy = {
            "name": "test",
            "scope": ["linux", "pve"],
            "resources": [{
                "type": "file_line",
                "path": "/etc/test.conf",
                "applies_to": ["linux", "pve"],
                "entries": {
                    "MaxRetries": {"linux": "3", "pve": "5"},
                    "Timeout": "30",
                },
            }],
        }
        ex = PolicyExecutor(policy)
        linux_host = Host(ip="1.1.1.1", label="test", htype="linux")
        pve_host = Host(ip="2.2.2.2", label="test2", htype="pve")

        linux_desired = ex.desired_state(linux_host)
        pve_desired = ex.desired_state(pve_host)

        self.assertEqual(linux_desired["MaxRetries"], "3")
        self.assertEqual(pve_desired["MaxRetries"], "5")
        self.assertEqual(linux_desired["Timeout"], "30")
        self.assertEqual(pve_desired["Timeout"], "30")

    def test_compare_finds_drift(self):
        from freq.engine.policy import PolicyExecutor
        policy = {"name": "test", "scope": ["linux"], "resources": []}
        ex = PolicyExecutor(policy)
        current = {"key1": "old", "key2": "same"}
        desired = {"key1": "new", "key2": "same"}
        findings = ex.compare(current, desired)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].key, "key1")
        self.assertEqual(findings[0].current, "old")
        self.assertEqual(findings[0].desired, "new")

    def test_compare_no_drift(self):
        from freq.engine.policy import PolicyExecutor
        policy = {"name": "test", "scope": ["linux"], "resources": []}
        ex = PolicyExecutor(policy)
        current = {"key1": "same", "key2": "same"}
        desired = {"key1": "same", "key2": "same"}
        findings = ex.compare(current, desired)
        self.assertEqual(len(findings), 0)

    def test_diff_text(self):
        from freq.engine.policy import PolicyExecutor
        policy = {"name": "test", "scope": ["linux"], "resources": []}
        ex = PolicyExecutor(policy)
        diff = ex.diff_text({"a": "1"}, {"a": "2"})
        self.assertIn("-a = 1", diff)
        self.assertIn("+a = 2", diff)

    def test_policy_store(self):
        from freq.engine.policy import PolicyStore
        store = PolicyStore()
        p1 = {"name": "policy-a", "scope": ["linux"], "resources": []}
        p2 = {"name": "policy-b", "scope": ["pve"], "resources": []}
        store.register(p1)
        store.register(p2)
        self.assertEqual(len(store.list()), 2)
        self.assertEqual(store.get("policy-a")["name"], "policy-a")
        self.assertIsNone(store.get("nonexistent"))

    def test_builtin_policies_load(self):
        from freq.engine.policies import ALL_POLICIES
        self.assertGreaterEqual(len(ALL_POLICIES), 3)
        names = [p["name"] for p in ALL_POLICIES]
        self.assertIn("ssh-hardening", names)
        self.assertIn("ntp-sync", names)


class TestRisk(unittest.TestCase):
    """Test the risk analysis module."""

    def setUp(self):
        from freq.core.config import FreqConfig

        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.cfg = FreqConfig()
        self.cfg.conf_dir = self.tmpdir.name
        source = Path(__file__).resolve().parents[1] / "freq/data/conf-templates/risk.toml.example"
        Path(self.tmpdir.name, "risk.toml").write_text(source.read_text())

    def test_dependencies_map(self):
        from freq.jarvis.risk import _load_risk_map

        deps = _load_risk_map(self.cfg)
        self.assertIn("firewall", deps)
        self.assertIn("storage", deps)
        self.assertEqual(deps["firewall"]["risk"], "CRITICAL")

    def test_all_have_impact(self):
        from freq.jarvis.risk import _load_risk_map

        deps = _load_risk_map(self.cfg)
        for key, info in deps.items():
            self.assertGreater(len(info["impact"]), 0, f"{key} has no impact listed")
            self.assertIn(info["risk"], ["CRITICAL", "HIGH", "MEDIUM", "LOW"])


class TestRiskFixtureLifecycle(unittest.TestCase):
    def test_partial_setup_failure_removes_temporary_config(self):
        created = []
        temporary_directory = tempfile.TemporaryDirectory

        def tracked_temporary_directory():
            directory = temporary_directory()
            created.append(directory.name)
            return directory

        case = TestRisk("test_dependencies_map")
        result = unittest.TestResult()
        with patch(
            "tempfile.TemporaryDirectory", side_effect=tracked_temporary_directory
        ), patch.object(Path, "read_text", side_effect=OSError("forced read failure")):
            case.run(result)

        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(created), 1)
        self.assertFalse(Path(created[0]).exists())


def _assert_web_notify_test_projection_contract():
    """Pin notification-test dispatch and secret-free response projection."""
    from ast import FunctionDef, ImportFrom, parse, walk

    from freq.jarvis import notify as notify_module
    from freq.modules import serve

    repo_root = Path(__file__).parent.parent
    serve_tree = parse((repo_root / "freq/modules/serve.py").read_text())
    notify_tree = parse((repo_root / "freq/jarvis/notify.py").read_text())
    assert "_notification_test_results" not in {
        node.name for node in walk(serve_tree) if isinstance(node, FunctionDef)
    }
    assert len([
        node for node in walk(notify_tree)
        if isinstance(node, FunctionDef) and node.name == "_notification_test_results"
    ]) == 1
    assert not any(
        isinstance(node, ImportFrom)
        and node.module is not None
        and node.module.startswith("freq.modules")
        for node in notify_tree.body
    )
    assert serve._notification_test_results is notify_module._notification_test_results
    notify_handler = (repo_root / "freq/modules/serve.py").read_text().split(
        "def _serve_notify_test", 1
    )[1].split("def _serve_", 1)[0]
    assert "results = _notification_test_results(cfg, jarvis_notify)" in notify_handler

    events = []

    class Config:
        @property
        def discord_webhook(self):
            events.append("discord-configured")
            return "discord-secret-value"

        @property
        def slack_webhook(self):
            events.append("slack-configured")
            return ""

    class Results:
        def items(self):
            events.append("results-items")
            return [
                ("discord", True),
                ("slack", False),
                ("custom", None),
            ]

    cfg = Config()
    results = Results()
    handler = serve.FreqHandler.__new__(serve.FreqHandler)
    handler.command = "POST"
    handler._json_response = MagicMock(
        side_effect=lambda payload: events.append(("response", payload)),
    )

    def dispatch(observed_cfg, message, *, severity):
        events.append(("dispatch", observed_cfg, message, severity))
        return results

    with (
        patch.object(serve, "_check_session_role", return_value=("admin", None)),
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "jarvis_notify", side_effect=dispatch) as notify,
    ):
        handler._serve_notify_test()

    expected_results = {"discord": True, "slack": False, "custom": None}
    expected_payload = {
        "results": expected_results,
        "discord_configured": True,
        "slack_configured": False,
    }
    assert [
        event if isinstance(event, str) else event[0]
        for event in events
    ] == [
        "dispatch",
        "results-items",
        "discord-configured",
        "slack-configured",
        "response",
    ]
    notify.assert_called_once_with(
        cfg,
        "Test notification from FREQ Web UI",
        severity="info",
    )
    assert notify.call_args.args[0] is cfg
    handler._json_response.assert_called_once_with(expected_payload)
    projected = handler._json_response.call_args.args[0]
    assert projected["results"] is not results
    assert "discord-secret-value" not in repr(projected)

    for failure in (RuntimeError("dispatch failed"), ValueError("projection failed")):
        failed_events = []
        failed_handler = serve.FreqHandler.__new__(serve.FreqHandler)
        failed_handler.command = "POST"
        failed_handler._json_response = MagicMock()

        if isinstance(failure, RuntimeError):
            failed_notify = MagicMock(side_effect=failure)
        else:
            failed_results = MagicMock()
            failed_results.items.side_effect = failure
            failed_notify = MagicMock(return_value=failed_results)

        with (
            patch.object(serve, "_check_session_role", return_value=("admin", None)),
            patch.object(serve, "load_config", return_value=cfg),
            patch.object(serve, "jarvis_notify", failed_notify),
        ):
            try:
                failed_handler._serve_notify_test()
            except type(failure) as exc:
                assert str(exc) == str(failure)
                failed_events.append("failed-loud")
            else:
                raise AssertionError("notification-test failure was swallowed")

        assert failed_events == ["failed-loud"]
        failed_handler._json_response.assert_not_called()


class TestNotify(unittest.TestCase):
    """Test notification system."""

    def test_send_discord_no_webhook(self):
        from freq.jarvis.notify import send_discord
        from freq.core.config import FreqConfig
        cfg = FreqConfig()  # discord_webhook defaults to ""
        result = send_discord(cfg, "test message")
        self.assertFalse(result)
        _assert_web_notify_test_projection_contract()

    def test_send_slack_no_webhook(self):
        from freq.jarvis.notify import send_slack
        from freq.core.config import FreqConfig
        cfg = FreqConfig()  # slack_webhook defaults to ""
        result = send_slack(cfg, "test message")
        self.assertFalse(result)


class TestConfigCompat(unittest.TestCase):
    """Test config loading compatibility."""

    def test_toml_loading(self):
        from freq.core.config import load_toml
        tmpdir = tempfile.mkdtemp()
        toml_path = os.path.join(tmpdir, "test.toml")
        with open(toml_path, "w") as f:
            f.write('[freq]\nversion = "1.0.0"\ndebug = false\ncount = 42\n')
            f.write('[ssh]\nservice_account = "svc-admin"\ntimeout = 5\n')
        result = load_toml(toml_path)
        self.assertEqual(result["freq"]["version"], "1.0.0")
        self.assertEqual(result["freq"]["debug"], False)
        self.assertEqual(result["freq"]["count"], 42)
        self.assertEqual(result["ssh"]["service_account"], "svc-admin")
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_python_version_check(self):
        from freq.core.compat import check_python
        result = check_python()
        self.assertIsNone(result)  # Should pass on 3.11+


class TestResolver(unittest.TestCase):
    """Test host resolution."""

    def test_by_label(self):
        from freq.core.resolve import by_label
        from freq.core.types import Host
        hosts = [
            Host(ip="1.1.1.1", label="host-a", htype="linux"),
            Host(ip="2.2.2.2", label="host-b", htype="pve"),
        ]
        result = by_label(hosts, "host-a")
        self.assertEqual(result.ip, "1.1.1.1")
        self.assertIsNone(by_label(hosts, "nonexistent"))

    def test_by_label_case_insensitive(self):
        from freq.core.resolve import by_label
        from freq.core.types import Host
        hosts = [Host(ip="1.1.1.1", label="MyHost", htype="linux")]
        result = by_label(hosts, "myhost")
        self.assertIsNotNone(result)

    def test_by_group(self):
        from freq.core.resolve import by_group
        from freq.core.types import Host
        hosts = [
            Host(ip="1.1.1.1", label="a", htype="linux", groups="web,prod"),
            Host(ip="2.2.2.2", label="b", htype="linux", groups="db,prod"),
            Host(ip="3.3.3.3", label="c", htype="linux", groups="web,dev"),
        ]
        result = by_group(hosts, "prod")
        self.assertEqual(len(result), 2)

    def test_by_type(self):
        from freq.core.resolve import by_type
        from freq.core.types import Host
        hosts = [
            Host(ip="1.1.1.1", label="a", htype="linux"),
            Host(ip="2.2.2.2", label="b", htype="pve"),
            Host(ip="3.3.3.3", label="c", htype="linux"),
        ]
        result = by_type(hosts, "linux")
        self.assertEqual(len(result), 2)


class TestCloudImages(unittest.TestCase):
    """Test cloud image registry."""

    def test_images_defined(self):
        from freq.jarvis.provision import CLOUD_IMAGES
        self.assertIn("debian-13", CLOUD_IMAGES)
        self.assertIn("ubuntu-2404", CLOUD_IMAGES)
        self.assertIn("rocky-9", CLOUD_IMAGES)

    def test_images_have_urls(self):
        from freq.jarvis.provision import CLOUD_IMAGES
        for key, image in CLOUD_IMAGES.items():
            self.assertIn("url", image, f"{key} missing url")
            self.assertIn("name", image, f"{key} missing name")
            self.assertTrue(image["url"].startswith("https://"), f"{key} url not https")


class TestDiscover(unittest.TestCase):
    """Test network discovery functions."""

    def test_parse_subnet_3_octet(self):
        from freq.modules.discover import _parse_subnet_input
        prefix, start, end = _parse_subnet_input("192.168.255")
        self.assertEqual(prefix, "192.168.255")
        self.assertEqual(start, 1)
        self.assertEqual(end, 254)

    def test_parse_subnet_cidr(self):
        from freq.modules.discover import _parse_subnet_input
        prefix, start, end = _parse_subnet_input("192.168.1.0/24")
        self.assertEqual(prefix, "192.168.1")
        self.assertEqual(start, 1)
        self.assertEqual(end, 254)

    def test_parse_subnet_4_octet(self):
        from freq.modules.discover import _parse_subnet_input
        prefix, start, end = _parse_subnet_input("10.0.0.1")
        self.assertEqual(prefix, "10.0.0")
        self.assertEqual(start, 1)
        self.assertEqual(end, 254)

    def test_parse_subnet_bad_input(self):
        from freq.modules.discover import _parse_subnet_input
        prefix, _, _ = _parse_subnet_input("bad")
        self.assertIsNone(prefix)

    def test_parse_subnet_out_of_range(self):
        from freq.modules.discover import _parse_subnet_input
        prefix, _, _ = _parse_subnet_input("999.0.0")
        self.assertIsNone(prefix)

    def test_parse_subnet_empty(self):
        from freq.modules.discover import _parse_subnet_input
        prefix, _, _ = _parse_subnet_input("")
        self.assertIsNone(prefix)

    def test_parse_subnet_with_spaces(self):
        from freq.modules.discover import _parse_subnet_input
        prefix, start, end = _parse_subnet_input("  192.168.10  ")
        self.assertEqual(prefix, "192.168.10")
        self.assertEqual(start, 1)
        self.assertEqual(end, 254)

    def test_parse_subnet_negative_octet(self):
        from freq.modules.discover import _parse_subnet_input
        prefix, _, _ = _parse_subnet_input("10.-1.0")
        self.assertIsNone(prefix)


class TestInitFleetRegistration(unittest.TestCase):
    """Test the init Phase 5 fleet registration helpers."""

    def setUp(self):
        import shutil
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, "conf"))
        os.makedirs(os.path.join(self.tmpdir, "data", "log"), exist_ok=True)
        os.makedirs(os.path.join(self.tmpdir, "data", "keys"), exist_ok=True)
        os.makedirs(os.path.join(self.tmpdir, "data", "vault"), exist_ok=True)

        # Copy freq.toml (prefer live config, fall back to .example)
        src_dir = os.path.join(os.path.dirname(__file__), "..", "conf")
        toml_src = os.path.join(src_dir, "freq.toml")
        if not os.path.isfile(toml_src):
            toml_src = os.path.join(src_dir, "freq.toml.example")
        shutil.copy(toml_src, os.path.join(self.tmpdir, "conf", "freq.toml"))
        with open(os.path.join(self.tmpdir, "conf", "hosts.toml"), "w") as f:
            f.write("# Empty\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_hosts_conf_loads_zero(self):
        from freq.core.config import load_config
        cfg = load_config(self.tmpdir)
        self.assertEqual(len(cfg.hosts), 0)

    def test_host_registration_roundtrip(self):
        from freq.core.config import load_config
        cfg = load_config(self.tmpdir)
        # Write a host entry in TOML format
        with open(cfg.hosts_file, "w") as f:
            f.write('[[host]]\nip = "192.168.1.10"\nlabel = "test-host"\ntype = "linux"\ngroups = "test"\n')
        cfg2 = load_config(self.tmpdir)
        self.assertEqual(len(cfg2.hosts), 1)
        self.assertEqual(cfg2.hosts[0].ip, "192.168.1.10")
        self.assertEqual(cfg2.hosts[0].label, "test-host")
        self.assertEqual(cfg2.hosts[0].htype, "linux")
        self.assertEqual(cfg2.hosts[0].groups, "test")

    def test_multiple_host_registration(self):
        from freq.core.config import load_config
        cfg = load_config(self.tmpdir)
        with open(cfg.hosts_file, "w") as f:
            f.write('[[host]]\nip = "10.0.0.1"\nlabel = "host-a"\ntype = "docker"\ngroups = "prod"\n\n')
            f.write('[[host]]\nip = "10.0.0.2"\nlabel = "host-b"\ntype = "pfsense"\n\n')
            f.write('[[host]]\nip = "10.0.0.3"\nlabel = "host-c"\ntype = "idrac"\ngroups = "mgmt"\n')
        cfg2 = load_config(self.tmpdir)
        self.assertEqual(len(cfg2.hosts), 3)
        types = [h.htype for h in cfg2.hosts]
        self.assertEqual(types, ["docker", "pfsense", "idrac"])

    def test_host_grouping_after_registration(self):
        """Verify registered hosts get grouped correctly for deploy."""
        from freq.core.config import load_config
        cfg = load_config(self.tmpdir)
        with open(cfg.hosts_file, "w") as f:
            f.write('[[host]]\nip = "10.0.0.1"\nlabel = "web01"\ntype = "linux"\n\n')
            f.write('[[host]]\nip = "10.0.0.2"\nlabel = "docker01"\ntype = "docker"\n\n')
            f.write('[[host]]\nip = "10.0.0.3"\nlabel = "fw01"\ntype = "pfsense"\n\n')
            f.write('[[host]]\nip = "10.0.0.4"\nlabel = "idrac01"\ntype = "idrac"\n\n')
            f.write('[[host]]\nip = "10.0.0.5"\nlabel = "nas01"\ntype = "truenas"\n')
        cfg2 = load_config(self.tmpdir)
        linux_hosts = [h for h in cfg2.hosts if h.htype in ("linux", "docker", "pve", "truenas")]
        pfsense_hosts = [h for h in cfg2.hosts if h.htype == "pfsense"]
        device_hosts = [h for h in cfg2.hosts if h.htype in ("idrac", "switch")]
        self.assertEqual(len(linux_hosts), 3)  # linux, docker, truenas
        self.assertEqual(len(pfsense_hosts), 1)
        self.assertEqual(len(device_hosts), 1)

    def test_dry_run_with_empty_hosts(self):
        """Dry run should work even with empty hosts.conf."""
        from freq.core.config import load_config
        cfg = load_config(self.tmpdir)
        # The dry run reads cfg.hosts — with 0 hosts it should show no fleet steps
        self.assertEqual(len(cfg.hosts), 0)
        # PVE nodes count depends on config — 0 for .example, 3 for production
        self.assertIsInstance(cfg.pve_nodes, list)


if __name__ == "__main__":
    unittest.main()
