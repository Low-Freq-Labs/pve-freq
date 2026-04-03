"""FREQ Module Tests — Tests for vault, users, engine, learn, risk, agent, notify.

Tests that all modules load, produce correct output types, and handle edge cases.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        from freq.modules.users import _save_users, _load_users
        users = [
            {"username": "admin", "role": "admin", "groups": ""},
            {"username": "operator", "role": "operator", "groups": "fleet"},
        ]
        _save_users(self.cfg, users)
        loaded = _load_users(self.cfg)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["username"], "admin")

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


class TestLearnKnowledgeBase(unittest.TestCase):
    """Test the knowledge base."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from freq.core.config import FreqConfig
        self.cfg = FreqConfig()
        self.cfg.data_dir = self.tmpdir
        # Seed knowledge from package data so tests work in CI
        try:
            from freq.data import get_data_path
            knowledge_src = get_data_path() / "knowledge"
            if knowledge_src.is_dir():
                import shutil
                knowledge_dst = os.path.join(self.tmpdir, "knowledge")
                os.makedirs(knowledge_dst, exist_ok=True)
                for src in knowledge_src.glob("*.toml"):
                    shutil.copy2(str(src), os.path.join(knowledge_dst, src.name))
        except ImportError:
            pass

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_and_seed(self):
        from freq.jarvis.learn import _init_db, _seed_db, _load_knowledge
        self.cfg.data_dir = self.tmpdir
        lessons, gotchas = _load_knowledge(self.cfg)
        if not lessons and not gotchas:
            self.skipTest("No knowledge data available")
        db_path = os.path.join(self.tmpdir, "jarvis", "knowledge.db")
        conn = _init_db(db_path)
        _seed_db(conn, lessons, gotchas)
        count = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        self.assertGreater(count, 0)
        conn.close()

    def test_search(self):
        from freq.jarvis.learn import _init_db, _seed_db, _search, _load_knowledge
        self.cfg.data_dir = self.tmpdir
        lessons, gotchas = _load_knowledge(self.cfg)
        if not lessons and not gotchas:
            self.skipTest("No knowledge data available")
        db_path = os.path.join(self.tmpdir, "jarvis", "knowledge.db")
        conn = _init_db(db_path)
        _seed_db(conn, lessons, gotchas)
        lessons_r, gotchas_r = _search(conn, "NFS stale")
        self.assertGreater(len(lessons_r) + len(gotchas_r), 0)
        conn.close()

    def test_search_no_results(self):
        from freq.jarvis.learn import _init_db, _seed_db, _search, _load_knowledge
        self.cfg.data_dir = self.tmpdir
        lessons, gotchas = _load_knowledge(self.cfg)
        if not lessons and not gotchas:
            self.skipTest("No knowledge data available")
        db_path = os.path.join(self.tmpdir, "jarvis", "knowledge.db")
        conn = _init_db(db_path)
        _seed_db(conn, lessons, gotchas)
        lessons_r, gotchas_r = _search(conn, "xyznonexistent123")
        self.assertEqual(len(lessons_r), 0)
        self.assertEqual(len(gotchas_r), 0)
        conn.close()


class TestRisk(unittest.TestCase):
    """Test the risk analysis module."""

    def test_dependencies_map(self):
        from freq.jarvis.risk import _load_risk_map
        from freq.core.config import load_config
        cfg = load_config()
        deps = _load_risk_map(cfg)
        if not deps:
            self.skipTest("No risk.toml configured — risk map empty")
        self.assertIn("firewall", deps)
        self.assertIn("storage", deps)
        self.assertEqual(deps["firewall"]["risk"], "CRITICAL")

    def test_all_have_impact(self):
        from freq.jarvis.risk import _load_risk_map
        from freq.core.config import load_config
        cfg = load_config()
        deps = _load_risk_map(cfg)
        if not deps:
            self.skipTest("No risk.toml configured — risk map empty")
        for key, info in deps.items():
            self.assertGreater(len(info["impact"]), 0, f"{key} has no impact listed")
            self.assertIn(info["risk"], ["CRITICAL", "HIGH", "MEDIUM", "LOW"])


class TestAgentTemplates(unittest.TestCase):
    """Test agent template system."""

    def test_templates_exist(self):
        from freq.jarvis.agent import TEMPLATES
        self.assertIn("infra-manager", TEMPLATES)
        self.assertIn("security-ops", TEMPLATES)
        self.assertIn("dev", TEMPLATES)
        self.assertIn("blank", TEMPLATES)

    def test_template_structure(self):
        from freq.jarvis.agent import TEMPLATES
        for name, tmpl in TEMPLATES.items():
            self.assertIn("name", tmpl, f"{name} missing 'name'")
            self.assertIn("cores", tmpl, f"{name} missing 'cores'")
            self.assertIn("ram", tmpl, f"{name} missing 'ram'")
            self.assertIn("disk", tmpl, f"{name} missing 'disk'")
            self.assertIn("claude_md", tmpl, f"{name} missing 'claude_md'")
            self.assertGreater(tmpl["cores"], 0)
            self.assertGreater(tmpl["ram"], 0)

    def test_agent_registry(self):
        from freq.jarvis.agent import _load_agents, _save_agents
        from freq.core.config import FreqConfig
        tmpdir = tempfile.mkdtemp()
        cfg = FreqConfig()
        cfg.data_dir = tmpdir

        agents = _load_agents(cfg)
        self.assertEqual(agents, {})

        agents["test-agent"] = {"name": "test-agent", "vmid": 5001, "status": "created"}
        _save_agents(cfg, agents)

        loaded = _load_agents(cfg)
        self.assertEqual(loaded["test-agent"]["vmid"], 5001)

        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestNotify(unittest.TestCase):
    """Test notification system."""

    def test_send_discord_no_webhook(self):
        from freq.jarvis.notify import send_discord
        from freq.core.config import FreqConfig
        cfg = FreqConfig()  # discord_webhook defaults to ""
        result = send_discord(cfg, "test message")
        self.assertFalse(result)

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
        from freq.core.config import load_config, Host
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
