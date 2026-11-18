import ast
import inspect
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from freq.core.types import Host


def _cfg(tmpdir, hosts):
    conf_dir = os.path.join(tmpdir, "conf")
    data_dir = os.path.join(tmpdir, "data")
    os.makedirs(conf_dir, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)
    key_path = os.path.join(tmpdir, "freq_id_ed25519")
    with open(key_path, "w") as f:
        f.write("not-a-real-key")
    os.chmod(key_path, 0o600)
    auth_file = os.path.join(tmpdir, "snmp-auth")
    priv_file = os.path.join(tmpdir, "snmp-priv")
    with open(auth_file, "w") as f:
        f.write("auth-secret")
    with open(priv_file, "w") as f:
        f.write("priv-secret")
    with open(os.path.join(conf_dir, "device-credentials.toml"), "w") as f:
        f.write(
            "\n".join(
                [
                    "[snmp]",
                    'user = "freqsnmp"',
                    'version = "3"',
                    'auth_protocol = "SHA"',
                    'priv_protocol = "AES"',
                    f'auth_password_file = "{auth_file}"',
                    f'priv_password_file = "{priv_file}"',
                ]
            )
        )
    return types.SimpleNamespace(
        conf_dir=conf_dir,
        data_dir=data_dir,
        install_dir="",
        hosts=hosts,
        ssh_service_account="freq-admin",
        ssh_key_path=key_path,
        ssh_rsa_key_path=key_path,
        legacy_password_file="",
        ssh_connect_timeout=3,
        snmp_community="public",
    )


class TestSNMPSetupContract(unittest.TestCase):
    def test_plan_models_supported_classes_without_mutation(self):
        from freq.modules.snmp import build_snmp_setup_plan

        cfg = _cfg(
            tempfile.mkdtemp(),
            [
                Host("10.0.0.11", "pve01", "pve"),
                Host("10.0.0.12", "docker01", "docker"),
                Host("10.0.0.1", "fw", "pfsense"),
                Host("10.0.0.10", "idrac", "idrac"),
                Host("10.0.0.99", "unknown", "printer"),
            ],
        )
        plan = build_snmp_setup_plan(cfg)
        by_label = {t["label"]: t for t in plan["targets"]}
        self.assertEqual(plan["schema_version"], 1)
        self.assertTrue(plan["credential_ready"])
        self.assertEqual(by_label["pve01"]["setup_class"], "linux_snmpd")
        self.assertEqual(by_label["docker01"]["setup_class"], "linux_snmpd")
        self.assertEqual(by_label["fw"]["setup_class"], "pfsense_net_snmp_package")
        self.assertIn("operator decision", " ".join(by_label["fw"]["caveats"]))
        self.assertEqual(by_label["idrac"]["setup_class"], "redfish_bmc_snmp")
        self.assertNotIn("unknown", by_label)

    @patch("subprocess.run")
    def test_linux_apply_is_bounded_noninteractive_and_keeps_secrets_out_of_argv(self, run_mock):
        from freq.modules.snmp import run_snmp_setup

        run_mock.return_value = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        cfg = _cfg(tempfile.mkdtemp(), [Host("10.0.0.11", "pve01", "pve")])
        result = run_snmp_setup(cfg, targets=["pve01"], dry_run=False)
        self.assertEqual(result["summary"]["changed"], 1)
        cmd = run_mock.call_args.kwargs.get("args") or run_mock.call_args.args[0]
        script = run_mock.call_args.kwargs["input"]
        joined_cmd = " ".join(cmd)
        self.assertIn("timeout -s KILL", joined_cmd)
        self.assertIn("BatchMode=yes", joined_cmd)
        self.assertIn("sudo -n sh -s", joined_cmd)
        self.assertNotIn("auth-secret", joined_cmd)
        self.assertNotIn("priv-secret", joined_cmd)
        self.assertIn("createUser freqsnmp SHA", script)
        self.assertIn("auth-secret", script)
        self.assertIn("priv-secret", script)

    @patch("subprocess.run")
    def test_per_host_failure_does_not_abort_next_target(self, run_mock):
        from freq.modules.snmp import run_snmp_setup

        run_mock.side_effect = [
            types.SimpleNamespace(returncode=100, stdout="", stderr="apt proxy failed"),
            types.SimpleNamespace(returncode=0, stdout="", stderr=""),
        ]
        cfg = _cfg(
            tempfile.mkdtemp(),
            [
                Host("10.0.0.40", "pdm-manager", "linux"),
                Host("10.0.0.25", "truenas", "truenas"),
            ],
        )
        result = run_snmp_setup(cfg, dry_run=False)
        states = {r["label"]: r["state"] for r in result["results"]}
        self.assertEqual(states["pdm-manager"], "failed")
        self.assertEqual(states["truenas"], "changed")
        self.assertEqual(result["summary"]["failed"], 1)
        self.assertEqual(result["summary"]["changed"], 1)

    @patch("freq.modules.snmp.get_snmp_identity")
    def test_pfsense_and_idrac_are_explicit_non_failure_states(self, identity_mock):
        from freq.modules.snmp import run_snmp_setup

        identity_mock.return_value = {"reachable": True, "sys_name": "idrac-B065ND2"}
        cfg = _cfg(
            tempfile.mkdtemp(),
            [
                Host("10.0.0.1", "pfsense", "pfsense"),
                Host("10.0.0.10", "idrac", "idrac"),
            ],
        )
        result = run_snmp_setup(cfg, dry_run=False)
        states = {r["label"]: r["state"] for r in result["results"]}
        self.assertEqual(states["pfsense"], "requires_decision")
        self.assertEqual(states["idrac"], "adopted")
        self.assertEqual(result["summary"]["failed"], 0)
        self.assertEqual(result["summary"]["requires_decision"], 1)

    def test_api_routes_registered(self):
        from freq.api import build_routes
        from freq.api import snmp as snmp_api
        from freq.modules import snmp as legacy_snmp
        from freq.services import snmp

        routes = build_routes()
        self.assertIn("/api/v1/net/snmp/setup/plan", routes)
        self.assertIn("/api/v1/net/snmp/setup/apply", routes)
        self.assertIn("/api/v1/net/snmp/setup/status", routes)
        self.assertIn("/api/v1/net/snmp/setup/credentials", routes)
        self.assertIn("/api/snmp/setup/plan", routes)

        repo = Path(__file__).resolve().parents[1]
        api_tree = ast.parse((repo / "freq" / "api" / "snmp.py").read_text())
        service_tree = ast.parse((repo / "freq" / "services" / "snmp.py").read_text())
        imports = [
            node
            for node in api_tree.body
            if isinstance(node, ast.ImportFrom) and node.module.endswith(".snmp")
        ]
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0].module, "freq.services.snmp")
        self.assertEqual(
            {alias.name for alias in imports[0].names},
            {
                "build_snmp_setup_plan",
                "read_last_snmp_setup_status",
                "run_snmp_setup",
                "store_snmp_credentials",
            },
        )
        upward = []
        for node in ast.walk(service_tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "freq.api" or node.module.startswith("freq.api."):
                    upward.append(node.module)
                if node.module == "freq.modules" or node.module.startswith("freq.modules."):
                    upward.append(node.module)
            elif isinstance(node, ast.Import):
                upward.extend(
                    alias.name
                    for alias in node.names
                    if alias.name == "freq.api"
                    or alias.name.startswith("freq.api.")
                    or alias.name == "freq.modules"
                    or alias.name.startswith("freq.modules.")
                )
        self.assertEqual(upward, [])
        self.assertIs(legacy_snmp, snmp)
        expected_signatures = {
            "build_snmp_setup_plan": "(cfg, targets=None, include_probe=False)",
            "read_last_snmp_setup_status": "(cfg)",
            "run_snmp_setup": "(cfg, targets=None, dry_run=True, include_probe=False)",
            "store_snmp_credentials": (
                "(cfg, user, auth_password, priv_password, auth_protocol='SHA', "
                "priv_protocol='AES', dry_run=True)"
            ),
        }
        for name, signature in expected_signatures.items():
            self.assertIs(getattr(snmp_api, name), getattr(snmp, name))
            self.assertEqual(str(inspect.signature(getattr(snmp, name))), signature)

    def test_store_snmp_credentials_uses_managed_files_not_inline_toml(self):
        from freq.modules.snmp import store_snmp_credentials

        tmpdir = tempfile.mkdtemp()
        cfg = _cfg(tmpdir, [])
        cfg.credentials_dir = os.path.join(tmpdir, "credentials")
        result = store_snmp_credentials(
            cfg,
            "freqsnmp",
            "auth-secret-2026",
            "priv-secret-2026",
            dry_run=False,
        )
        self.assertTrue(result["stored"])
        with open(result["credentials_path"]) as f:
            text = f.read()
        self.assertIn("[snmp]", text)
        self.assertIn('auth_password_file = "', text)
        self.assertIn('priv_password_file = "', text)
        self.assertNotIn("auth-secret-2026", text)
        self.assertNotIn("priv-secret-2026", text)
        with open(result["auth_password_file"]) as f:
            self.assertEqual(f.read().strip(), "auth-secret-2026")
        with open(result["priv_password_file"]) as f:
            self.assertEqual(f.read().strip(), "priv-secret-2026")


if __name__ == "__main__":
    unittest.main()
