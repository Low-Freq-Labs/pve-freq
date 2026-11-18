"""Infra quick auth parity tests.

Proves:
1. _is_auth_failure detects SSH permission denied errors
2. Infra quick probe marks auth failures with auth_failed=true
3. Infra quick separates network reachability from SSH/API auth failures
4. probe_method field is set for all probe outcomes
5. Unknown device types note that /api/health has authoritative SSH state

Fixes Finn-reported divergence: /api/fleet/overview marked the firewall
network-reachable, then /api/infra/quick overwrote the Core Systems card
as unreachable because SSH metrics auth failed. Infrastructure cards must
show reachable network state and auth/metrics failure separately.
"""

import os
import re
import unittest
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestInfraAuthFailureDetection(unittest.TestCase):
    """The _is_auth_failure helper must catch common SSH auth errors."""

    def _src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            return f.read()

    def test_helper_defined(self):
        src = self._src()
        self.assertIn("def _is_auth_failure", src,
                       "_is_auth_failure helper must exist")

    def test_helper_catches_permission_denied(self):
        """The helper must match 'permission denied' and 'publickey' errors."""
        src = self._src()
        fn = src.split("def _is_auth_failure")[1].split("\n    def ")[0]
        self.assertIn("permission denied", fn.lower())
        self.assertIn("publickey", fn.lower())


class TestInfraProbeMethodField(unittest.TestCase):
    """Every infra probe outcome must set probe_method."""

    def _probe_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _probe_device")[1].split("\n    devices = ")[0]

    def test_initial_probe_method_none(self):
        src = self._probe_src()
        self.assertIn('"probe_method": "none"', src,
                       "Default probe_method must be 'none'")

    def test_ssh_success_sets_method_ssh(self):
        src = self._probe_src()
        # At least one branch sets probe_method = "ssh"
        self.assertIn('d["probe_method"] = "ssh"', src)

    def test_auth_failure_sets_method(self):
        src = self._probe_src()
        self.assertIn('d["probe_method"] = "ssh_auth_failed"', src,
                       "Auth failure must set probe_method='ssh_auth_failed'")

    def test_ping_fallback_sets_method(self):
        src = self._probe_src()
        self.assertIn('"network" if d["reachable"] else "none"', src,
                       "Network fallback must set probe_method='network' or 'none'")

    def test_pfsense_probe_uses_runtime_device_credentials(self):
        src = self._probe_src()
        block = src.split('if dt == "pfsense":')[1].split('\n            elif dt == "truenas":')[0]
        self.assertIn("pfsense_auth", block)
        self.assertIn('user=pfsense_auth["user"]', block)
        self.assertIn('key_path=pfsense_auth["key_path"]', block)
        self.assertNotIn("user=svc_user", block)

    def test_background_health_probe_uses_staged_device_credentials(self):
        """Main health loop must not fall back to service-account auth for devices."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        block = src.split("def _bg_probe_health", 1)[1].split("\ndef _bg_loop", 1)[0]
        self.assertIn("resolve_staged_device_ssh_auth(cfg, htype)", block)
        self.assertIn('if htype in ("pfsense", "idrac", "switch", "truenas")', block)
        self.assertIn("user=probe_user", block)
        self.assertIn("local_user=probe_local_user", block)
        self.assertIn("password_file=probe_password_file", block)

    def test_fleet_connectivity_uses_health_cache_and_staged_device_auth(self):
        from ast import Attribute, Call, FunctionDef, Import, ImportFrom, Name, parse, walk
        from pathlib import Path

        from freq.modules import serve
        from freq.services import fleet_connectivity

        def attribute_path(node):
            if isinstance(node, Name):
                return node.id
            if isinstance(node, Attribute):
                parent = attribute_path(node.value)
                return f"{parent}.{node.attr}" if parent else node.attr
            return ""

        repo_root = Path(__file__).parent.parent
        serve_tree = parse((repo_root / "freq/modules/serve.py").read_text())
        service_tree = parse((repo_root / "freq/services/fleet_connectivity.py").read_text())
        service_imports = set()
        for node in walk(service_tree):
            if isinstance(node, Import):
                service_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ImportFrom) and node.module:
                service_imports.add(node.module)
        self.assertEqual(
            service_imports,
            {"freq.core.device_credentials", "freq.core.health_state", "freq.core.ssh"},
        )
        self.assertIn(
            "probe_fleet_connectivity",
            {node.name for node in walk(service_tree) if isinstance(node, FunctionDef)},
        )
        handler = next(
            node
            for node in walk(serve_tree)
            if isinstance(node, FunctionDef) and node.name == "_serve_fleet_connectivity"
        )
        self.assertEqual(len(handler.body), 5)
        handler_calls = {
            attribute_path(node.func) for node in walk(handler) if isinstance(node, Call)
        }
        self.assertIn("_fleet_connectivity.probe_fleet_connectivity", handler_calls)
        self.assertNotIn("ssh_single", handler_calls)
        self.assertNotIn("resolve_staged_device_ssh_auth", handler_calls)

        hosts = [
            SimpleNamespace(label="cached-auth", ip="10.0.0.1", htype="pfsense"),
            SimpleNamespace(label="cached-down", ip="10.0.0.2", htype="switch"),
            SimpleNamespace(label="cached-ok", ip="10.0.0.3", htype="truenas"),
            SimpleNamespace(label="linux-ok", ip="10.0.0.4"),
            SimpleNamespace(label="pfsense-fail", ip="10.0.0.5", htype="pfsense"),
            SimpleNamespace(label="idrac-error", ip="10.0.0.6", htype="idrac"),
            SimpleNamespace(label="switch-ok", ip="10.0.0.7", htype="switch"),
            SimpleNamespace(label="truenas-ok", ip="10.0.0.8", htype="truenas"),
        ]
        cfg = SimpleNamespace(
            hosts=hosts,
            ssh_key_path="/keys/fleet-ed25519",
            ssh_rsa_key_path="/keys/fleet-rsa",
            ssh_service_account="freq-admin",
        )
        health = {
            "hosts": [
                {"ip": "10.0.0.1", "state": serve.STATE_AUTH_FAILED, "reason": "credential rejected"},
                {"ip": "10.0.0.2", "status": serve.STATE_UNREACHABLE, "reason": "timeout"},
                {"ip": "10.0.0.3", "status": "healthy"},
                {"state": "ignored-without-ip"},
                "ignored-non-dict",
            ]
        }

        class LockProbe:
            entered = 0
            exited = 0

            def __enter__(self):
                self.entered += 1
                return self

            def __exit__(self, exc_type, exc, tb):
                self.exited += 1

        lock = LockProbe()
        auth_calls = []
        auth_by_type = {
            "pfsense": {
                "key_path": "/keys/pfsense",
                "user": "pf-user",
                "local_user": "pf-local",
                "password_file": "/credentials/pfsense",
                "sudo_password_file": True,
            },
            "idrac": {"user": "idrac-user"},
            "switch": {"user": "switch-user", "local_user": "switch-local"},
            "truenas": {"user": "nas-user", "password_file": "/credentials/truenas"},
        }

        def resolve_auth(actual_cfg, htype):
            self.assertIs(actual_cfg, cfg)
            auth_calls.append(htype)
            return auth_by_type[htype]

        ssh_calls = []

        def ssh_run(**kwargs):
            self.assertIs(kwargs["cfg"], cfg)
            ssh_calls.append(kwargs)
            if kwargs["host"] == "10.0.0.5":
                return SimpleNamespace(returncode=17, stdout="must-not-surface\n")
            if kwargs["host"] == "10.0.0.6":
                raise OSError("device unavailable")
            users = {
                "10.0.0.4": "freq-admin\n",
                "10.0.0.7": "switch-admin\n",
                "10.0.0.8": "nas-admin\n",
            }
            return SimpleNamespace(returncode=0, stdout=users[kwargs["host"]])

        captured = []
        response_handler = SimpleNamespace(_json_response=captured.append)
        with (
            mock.patch.object(serve, "load_config", return_value=cfg),
            mock.patch.object(serve, "_bg_lock", lock),
            mock.patch.object(serve, "_bg_cache", {"health": health}),
            mock.patch.object(
                fleet_connectivity,
                "resolve_staged_device_ssh_auth",
                side_effect=resolve_auth,
            ),
            mock.patch.object(fleet_connectivity, "ssh_single", side_effect=ssh_run),
        ):
            serve.FreqHandler._serve_fleet_connectivity(response_handler)

        self.assertEqual((lock.entered, lock.exited), (1, 1))
        self.assertEqual(auth_calls, ["pfsense", "idrac", "switch", "truenas"])
        self.assertEqual(
            ssh_calls,
            [
                {
                    "host": "10.0.0.4", "command": "whoami", "key_path": "/keys/fleet-ed25519",
                    "user": "freq-admin", "local_user": None, "password_file": None,
                    "sudo_password_file": False, "connect_timeout": 3, "command_timeout": 5,
                    "htype": "linux", "cfg": cfg,
                },
                {
                    "host": "10.0.0.5", "command": "echo OK", "key_path": "/keys/pfsense",
                    "user": "pf-user", "local_user": "pf-local", "password_file": "/credentials/pfsense",
                    "sudo_password_file": True, "connect_timeout": 3, "command_timeout": 5,
                    "htype": "pfsense", "cfg": cfg,
                },
                {
                    "host": "10.0.0.6", "command": "racadm getversion", "key_path": "/keys/fleet-rsa",
                    "user": "idrac-user", "local_user": None, "password_file": None,
                    "sudo_password_file": False, "connect_timeout": 3, "command_timeout": 5,
                    "htype": "idrac", "cfg": cfg,
                },
                {
                    "host": "10.0.0.7", "command": "show version | include uptime", "key_path": "/keys/fleet-rsa",
                    "user": "switch-user", "local_user": "switch-local", "password_file": None,
                    "sudo_password_file": False, "connect_timeout": 3, "command_timeout": 5,
                    "htype": "switch", "cfg": cfg,
                },
                {
                    "host": "10.0.0.8", "command": "whoami", "key_path": "/keys/fleet-ed25519",
                    "user": "nas-user", "local_user": None, "password_file": "/credentials/truenas",
                    "sudo_password_file": False, "connect_timeout": 3, "command_timeout": 5,
                    "htype": "truenas", "cfg": cfg,
                },
            ],
        )
        self.assertEqual(
            captured,
            [{
                "hosts": [
                    {"label": "cached-auth", "ip": "10.0.0.1", "type": "pfsense", "reachable": False,
                     "user": serve.STATE_AUTH_FAILED, "state": serve.STATE_AUTH_FAILED,
                     "reason": "credential rejected", "source": "health_cache"},
                    {"label": "cached-down", "ip": "10.0.0.2", "type": "switch", "reachable": False,
                     "user": serve.STATE_UNREACHABLE, "state": serve.STATE_UNREACHABLE,
                     "reason": "timeout", "source": "health_cache"},
                    {"label": "cached-ok", "ip": "10.0.0.3", "type": "truenas", "reachable": True,
                     "user": "healthy", "state": "healthy", "reason": "", "source": "health_cache"},
                    {"label": "linux-ok", "ip": "10.0.0.4", "type": "linux", "reachable": True,
                     "user": "freq-admin"},
                    {"label": "pfsense-fail", "ip": "10.0.0.5", "type": "pfsense", "reachable": False,
                     "user": ""},
                    {"label": "idrac-error", "ip": "10.0.0.6", "type": "idrac", "reachable": False,
                     "user": ""},
                    {"label": "switch-ok", "ip": "10.0.0.7", "type": "switch", "reachable": True,
                     "user": "switch-admin"},
                    {"label": "truenas-ok", "ip": "10.0.0.8", "type": "truenas", "reachable": True,
                     "user": "nas-admin"},
                ],
                "total": 8,
                "reachable": 4,
            }],
        )


class TestInfraAuthFailureKeepsNetworkTruth(unittest.TestCase):
    """SSH auth failure must not erase network reachability."""

    def _probe_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _probe_device")[1].split("\n    devices = ")[0]

    def test_all_ssh_branches_check_auth_failure(self):
        """Every SSH-using branch must have an elif _is_auth_failure check."""
        src = self._probe_src()
        # Should appear at least for pfsense, truenas, switch, idrac
        count = src.count("_is_auth_failure(r.stderr)")
        self.assertGreaterEqual(count, 4,
                                f"Expected ≥4 auth failure checks (pfsense/truenas/switch/idrac), got {count}")

    def test_auth_failed_sets_auth_failed_field(self):
        src = self._probe_src()
        # Each "elif _is_auth_failure" branch must set d["auth_failed"] = True.
        # Skip non-elif occurrences (e.g. idrac's retry gate which triggers
        # a sshpass fallback rather than being the terminal handler).
        pattern = re.compile(r'elif _is_auth_failure\(r\.stderr\):(.*?)(?=\n                (?:else|elif |\Z))', re.DOTALL)
        for m in pattern.finditer(src):
            self.assertIn('d["auth_failed"] = True', m.group(1),
                           "elif _is_auth_failure branch must set auth_failed=True")

    def test_auth_failure_rechecks_network_reachability(self):
        """Auth failure branches must classify network reachability separately."""
        src = self._probe_src()
        pattern = re.compile(r'elif _is_auth_failure\(r\.stderr\):(.*?)(?=\n                (?:else|elif |\Z))', re.DOTALL)
        for m in pattern.finditer(src):
            block = m.group(1)
            self.assertIn('d["reachable"] = _network_reachable(dev)', block,
                          "Auth failure branch must preserve network reachability truth")
            self.assertNotIn('d["reachable"] = False', block,
                             "Auth failure branch must not force network unreachable")

    def test_dashboard_renders_auth_failed_as_warning_not_reachable(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        self.assertIn("statusLabel='AUTH FAILED'", src)
        self.assertIn("dotClass='warn'", src)
        self.assertIn("authFailed?'AUTH FAILED'", src)
        self.assertNotIn("if(dev.reachable&&dev.auth_failed)statusLabel='REACHABLE'", src)


class TestIdracProbeParity(unittest.TestCase):
    """iDRAC probe MUST mirror init._verify_host to stay in parity with
    `freq init --check` and `freq fleet status`. Finn filed a hard-E2E bug
    where infra_quick reported auth_failed on BMCs while init/fleet both
    verified them UP as freq-admin. The root cause: old probe used sshpass
    with SUDO_USER as the SSH user and a hardcoded credential path, then
    fell back to root@ via key. Fix: use cfg.ssh_service_account + RSA key
    first (matching init), then cfg.legacy_password_file as sshpass fallback."""

    def _probe_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _probe_device")[1].split("\n    devices = ")[0]

    def _idrac_block(self):
        src = self._probe_src()
        return src.split('elif dt == "idrac":')[1].split("\n            else:")[0]

    def test_uses_svc_user_not_bootstrap_user(self):
        """iDRAC probe MUST use cfg.ssh_service_account, not SUDO_USER."""
        block = self._idrac_block()
        self.assertIn("cfg.ssh_service_account", block,
                       "iDRAC probe must use cfg.ssh_service_account (freq-admin)")
        # No bootstrap_user reference in the idrac block — that's the operator
        # running the web UI, not the BMC account
        self.assertNotIn("bootstrap_user", block,
                          "iDRAC probe must NOT use bootstrap_user (operator, not BMC account)")

    def test_does_not_use_root_user(self):
        """iDRAC probe must NOT use user=root (init verifies as svc_user)."""
        block = self._idrac_block()
        self.assertNotIn('user="root"', block,
                          "iDRAC probe must not hardcode user=root")
        self.assertNotIn("user='root'", block,
                          "iDRAC probe must not hardcode user=root")

    def test_does_not_hardcode_switch_password_path(self):
        """iDRAC probe must not hardcode credentials/switch-password path.
        Must use cfg.legacy_password_file like init._verify_host does."""
        block = self._idrac_block()
        self.assertNotIn('"credentials"', block,
                          "iDRAC probe must not hardcode credentials/switch-password")
        self.assertNotIn("switch-password", block,
                          "iDRAC probe must not hardcode switch-password filename")

    def test_key_auth_tried_first(self):
        """Key auth must be tried FIRST (matching init), sshpass as fallback."""
        block = self._idrac_block()
        ssh_idx = block.find('"ssh"')
        sshpass_idx = block.find('"sshpass"')
        # Key auth ssh command must appear before sshpass fallback
        self.assertGreaterEqual(ssh_idx, 0, "Key auth ssh command must be present")
        if sshpass_idx >= 0:
            self.assertLess(ssh_idx, sshpass_idx,
                             "Key auth must be attempted BEFORE sshpass fallback (matches init)")

    def test_sshpass_fallback_uses_legacy_password_file(self):
        """Sshpass fallback must read from cfg.legacy_password_file."""
        block = self._idrac_block()
        self.assertIn("legacy_password_file", block,
                       "iDRAC probe must use cfg.legacy_password_file for fallback")

    def test_fallback_is_conditional_on_auth_failure(self):
        """Sshpass fallback must only trigger on auth failure, not every
        failure (avoids wasting sshpass calls against down hosts)."""
        block = self._idrac_block()
        self.assertIn("_is_auth_failure", block,
                       "iDRAC fallback must be gated on _is_auth_failure")

    def test_idrac_cipher_opts_applied(self):
        """Both key and password attempts must pass iDRAC extra_opts so the
        cipher/kex/pubkey negotiation matches what init uses."""
        block = self._idrac_block()
        self.assertIn("idrac_opts", block,
                       "iDRAC probe must apply PLATFORM_SSH idrac extra_opts")
        # idrac_opts must be sourced from PLATFORM_SSH
        self.assertIn("PLATFORM_SSH", block,
                       "idrac_opts must come from PLATFORM_SSH (single source of truth)")


class TestUnknownDeviceTypeNote(unittest.TestCase):
    """The final else branch (unknown device types) must reference /api/health."""

    def test_else_branch_notes_health_is_authoritative(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        probe_src = src.split("def _probe_device")[1].split("\n    devices = ")[0]
        # Find the final else — right before the return d
        # We just check that /api/health is mentioned as a reference
        self.assertIn("/api/health", probe_src,
                       "Unknown device type branch must reference /api/health for SSH probe state")


if __name__ == "__main__":
    unittest.main()
