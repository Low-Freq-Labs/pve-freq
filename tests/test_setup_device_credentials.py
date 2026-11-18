"""Runtime contracts for setup device credential storage."""

import os
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch


class TestSetupDeviceCredentialWriter(unittest.TestCase):
    """Web setup inline device credentials must become init-readable TOML."""

    def _assert_setup_init_command_contract(self, serve_mod):
        import ast
        import inspect

        serve_tree = ast.parse(inspect.getsource(serve_mod))
        from freq.services import setup_inputs

        service_tree = ast.parse(inspect.getsource(setup_inputs))
        self.assertFalse(
            any(
                isinstance(node, ast.FunctionDef) and node.name == "_setup_init_command"
                for node in serve_tree.body
            )
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.FunctionDef) and node.name == "setup_init_command"
                for node in service_tree.body
            ),
            1,
        )
        self.assertIs(serve_mod._setup_init_command, setup_inputs.setup_init_command)
        self.assertFalse(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_setup_init_command"
                for node in ast.walk(serve_tree)
            )
        )

        with tempfile.TemporaryDirectory() as td:
            cfg = SimpleNamespace(
                data_dir=os.path.join(td, "data"),
                install_dir="/opt/pve-freq-owner",
                pve_nodes=["cfg-node"],
                pve_node_names=["cfg-name"],
            )
            vm_contract = os.path.join(td, "vm-contract.toml")
            with open(vm_contract, "w") as handle:
                handle.write("[fleet]\n")
            body = {
                "service_account_password": "service-password-123",
                "dashboard_user": "dashboard-admin",
                "dashboard_password": "dashboard-password-123",
                "bootstrap_user": "root",
                "bootstrap_key": "~/bootstrap-key",
                "service_account": "freq-ops",
                "pve_nodes": "pve-a,pve-b  pve-c",
                "pve_node_names": [" node-a ", "node-b"],
                "gateway": "10.0.0.1",
                "nameserver": "10.0.0.2",
                "cluster_name": "owner-cluster",
                "ssh_mode": "sudo",
                "hosts_file": "/tmp/hosts.toml",
                "owned_vmids": "100,101",
                "template_vmids": "9000",
                "acknowledged_out_of_contract_vmids": "199",
                "core_devices": "pfsense,truenas",
                "lab_devices": "switch-a",
                "pdm_remote_name": "pdm-owner",
                "vm_contract": vm_contract,
                "device_credentials": {
                    "pfsense": {
                        "type": "pfsense",
                        "host": "10.0.0.3",
                        "user": "owner",
                        "password": "device-secret",
                    }
                },
                "install_pdm": True,
                "pdm_password": "pdm-password-123",
            }
            with patch.object(serve_mod.os, "geteuid", return_value=0):
                cmd, env, secret_dir = serve_mod._setup_init_command(
                    cfg,
                    body,
                    "owner-job",
                )

            self.assertEqual(secret_dir, os.path.join(cfg.data_dir, "secrets", "setup-init", "owner-job"))
            self.assertEqual(stat.S_IMODE(os.stat(secret_dir).st_mode), 0o700)
            self.assertEqual(
                cmd[:7],
                [
                    serve_mod.sys.executable,
                    "-c",
                    "import sys; from freq.cli import main; raise SystemExit(main(sys.argv[1:]))",
                    "--yes",
                    "init",
                    "--headless",
                    "--password-file",
                ],
            )
            self.assertEqual(env["FREQ_DIR"], cfg.install_dir)
            self.assertEqual(env["FREQ_WEB_INIT"], "1")
            self.assertEqual(env["PYTHONUNBUFFERED"], "1")
            expected_values = {
                "--bootstrap-user": "root",
                "--bootstrap-key": os.path.expanduser("~/bootstrap-key"),
                "--service-account": "freq-ops",
                "--dashboard-user": "dashboard-admin",
                "--pve-nodes": "pve-a,pve-b,pve-c",
                "--pve-node-names": "node-a,node-b",
                "--gateway": "10.0.0.1",
                "--nameserver": "10.0.0.2",
                "--cluster-name": "owner-cluster",
                "--ssh-mode": "sudo",
                "--hosts-file": "/tmp/hosts.toml",
                "--owned-vmids": "100,101",
                "--template-vmids": "9000",
                "--acknowledged-out-of-contract-vmids": "199",
                "--core-devices": "pfsense,truenas",
                "--lab-devices": "switch-a",
                "--pdm-remote-name": "pdm-owner",
                "--vm-contract": vm_contract,
            }
            for flag, expected in expected_values.items():
                with self.subTest(command_flag=flag):
                    self.assertEqual(cmd[cmd.index(flag) + 1], expected)
            for flag in ("--dashboard-password-file", "--device-credentials", "--pdm-pass"):
                value = cmd[cmd.index(flag) + 1]
                self.assertTrue(os.path.isfile(value))
                self.assertEqual(stat.S_IMODE(os.stat(value).st_mode), 0o600)
            self.assertIn("--install-pdm", cmd)
            self.assertNotIn("--skip-pdm", cmd)

            service_file = os.path.join(td, "service-password")
            with open(service_file, "w") as handle:
                handle.write("service-password-123\n")
            with patch.object(serve_mod.os, "geteuid", return_value=1000):
                fallback_cmd, fallback_env, _ = serve_mod._setup_init_command(
                    cfg,
                    {
                        "service_account_password_file": service_file,
                        "skip_pdm": True,
                    },
                    "fallback-job",
                )
            self.assertEqual(
                fallback_cmd[:6],
                [
                    "sudo",
                    "-n",
                    "env",
                    f"FREQ_DIR={cfg.install_dir}",
                    "FREQ_WEB_INIT=1",
                    "PYTHONUNBUFFERED=1",
                ],
            )
            self.assertEqual(fallback_env["FREQ_DIR"], cfg.install_dir)
            self.assertIn("--skip-pdm", fallback_cmd)
            self.assertNotIn("--install-pdm", fallback_cmd)
            self.assertEqual(fallback_cmd[fallback_cmd.index("--pve-nodes") + 1], "cfg-node")
            self.assertEqual(fallback_cmd[fallback_cmd.index("--pve-node-names") + 1], "cfg-name")

            bootstrap_password_file = os.path.join(td, "bootstrap-password")
            bootstrap_key_file = os.path.join(td, "bootstrap-key")
            for path, value in (
                (bootstrap_password_file, "bootstrap-password-123\n"),
                (bootstrap_key_file, "not-a-real-key\n"),
            ):
                with open(path, "w") as handle:
                    handle.write(value)
            precedence_cmd, _, _ = serve_mod._setup_init_command(
                cfg,
                {
                    "service_account_password_file": service_file,
                    "bootstrap_user": "root",
                    "bootstrap_password_file": bootstrap_password_file,
                    "bootstrap_key_path": bootstrap_key_file,
                    "bootstrap_key": "~/ignored-inline-key",
                },
                "precedence-job",
            )
            self.assertEqual(
                precedence_cmd[precedence_cmd.index("--bootstrap-password-file") + 1],
                bootstrap_password_file,
            )
            self.assertNotIn("--bootstrap-key", precedence_cmd)

            for invalid, message in (
                ({}, "service_account_password is required and must be at least 8 characters"),
                (
                    {
                        "service_account_password_file": service_file,
                        "dashboard_user": "admin",
                        "dashboard_password": "short",
                    },
                    "dashboard_password is required when dashboard_user is set",
                ),
            ):
                with self.subTest(invalid_command=message):
                    with self.assertRaisesRegex(ValueError, message):
                        serve_mod._setup_init_command(cfg, invalid, "invalid-job")

    def test_secret_paths_resolve_alias_and_sudo_read_fallbacks(self):
        import ast
        import inspect

        from freq.api import auth
        from freq.modules import serve as serve_mod
        from freq.services import setup_inputs

        self._assert_setup_init_command_contract(serve_mod)

        serve_tree = ast.parse(inspect.getsource(serve_mod))
        auth_tree = ast.parse(inspect.getsource(auth))
        service_tree = ast.parse(inspect.getsource(setup_inputs))
        self.assertFalse(
            any(
                isinstance(node, ast.FunctionDef) and node.name == "_list_value"
                for node in serve_tree.body
            )
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.FunctionDef) and node.name == "list_value"
                for node in service_tree.body
            ),
            1,
        )
        self.assertIs(serve_mod._list_value, setup_inputs.list_value)
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_list_value"
                for node in ast.walk(serve_tree)
            ),
            0,
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "list_value"
                for node in ast.walk(service_tree)
            ),
            2,
        )
        list_cases = (
            (None, []),
            ("", []),
            (" , \t\n ", []),
            ("pve-1,pve-2  pve-3\npve-4", ["pve-1", "pve-2", "pve-3", "pve-4"]),
            (7, ["7"]),
            ([" pve-1 ", "", "  ", "pve-2", 0, None], ["pve-1", "pve-2", "0", "None"]),
        )
        for value, expected in list_cases:
            with self.subTest(list_value=value):
                self.assertEqual(serve_mod._list_value(value), expected)

        self.assertFalse(
            any(
                isinstance(node, ast.FunctionDef) and node.name == "_toml_scalar"
                for node in serve_tree.body
            )
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.FunctionDef) and node.name == "toml_scalar"
                for node in service_tree.body
            ),
            1,
        )
        self.assertIs(serve_mod._toml_scalar, setup_inputs.toml_scalar)
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_toml_scalar"
                for node in ast.walk(serve_tree)
            ),
            0,
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "toml_scalar"
                for node in ast.walk(auth_tree)
            ),
            7,
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "toml_scalar"
                for node in ast.walk(service_tree)
            ),
            8,
        )
        scalar_cases = (
            (True, "true"),
            (False, "false"),
            (7, "7"),
            (-3, "-3"),
            ([True, 2, 'a"b'], '[true, 2, "a\\\"b"]'),
            (("x",), '["x"]'),
            ("slash\\quote\"\b\t\n\f\r", '"slash\\\\quote\\\"\\b\\t\\n\\f\\r"'),
            (None, '"None"'),
            (1.5, '"1.5"'),
        )
        for value, expected in scalar_cases:
            with self.subTest(toml_scalar=value):
                self.assertEqual(serve_mod._toml_scalar(value), expected)

        self.assertIs(
            serve_mod._setup_existing_secret_file,
            setup_inputs.resolve_existing_secret_file,
        )
        self.assertIs(
            serve_mod._read_setup_secret_file,
            setup_inputs.read_existing_secret_file,
        )
        self.assertEqual(
            {
                alias.name
                for node in ast.walk(service_tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            },
            {"os", "re", "subprocess", "sys", "uuid"},
        )
        self.assertEqual(
            {
                (node.module, tuple(alias.name for alias in node.names))
                for node in ast.walk(service_tree)
                if isinstance(node, ast.ImportFrom)
            },
            {
                ("freq.core.config", ("is_managed_service_account_name",)),
                ("freq.core.device_credentials", ("device_credentials_section_header",)),
                ("freq.core.setup_contract", ("SetupContractError",)),
                ("freq.core.setup_paths", ("legacy_init_input_candidate",)),
                ("freq.core.setup_state", ("SCHEMA",)),
            },
        )

        with (
            patch.object(setup_inputs.os.path, "expanduser", return_value="") as expanduser,
            patch.object(setup_inputs.os.path, "isfile") as isfile,
            patch.object(setup_inputs.subprocess, "run") as run,
            patch("builtins.open") as open_file,
        ):
            self.assertEqual(
                serve_mod._setup_existing_secret_file(" \t ", "optional_secret"),
                "",
            )
            self.assertEqual(
                serve_mod._read_setup_secret_file(" \t ", "optional_secret"),
                "",
            )
        self.assertEqual(expanduser.call_args_list, [call(""), call("")])
        isfile.assert_not_called()
        run.assert_not_called()
        open_file.assert_not_called()

        with (
            patch.object(
                setup_inputs.os.path,
                "expanduser",
                return_value="/expanded/direct-secret",
            ) as expanduser,
            patch.object(setup_inputs.os.path, "isfile", return_value=True),
            patch.object(setup_inputs.subprocess, "run") as run,
        ):
            self.assertEqual(
                serve_mod._setup_existing_secret_file(
                    "  ~/direct-secret  ",
                    "direct_secret",
                ),
                "/expanded/direct-secret",
            )
        expanduser.assert_called_once_with("~/direct-secret")
        run.assert_not_called()

        with tempfile.TemporaryDirectory() as td:
            direct_path = os.path.join(td, "direct-secret")
            with open(direct_path, "w") as f:
                f.write("  direct-value  \n")
            self.assertEqual(
                serve_mod._setup_existing_secret_file(direct_path, "direct_secret"),
                direct_path,
            )
            self.assertEqual(
                serve_mod._read_setup_secret_file(direct_path, "direct_secret"),
                "direct-value",
            )

        self.assertEqual(serve_mod._setup_existing_secret_file("", "optional_secret"), "")

        root_path = "/root/freq-init-inputs/alias-secret"
        alias_path = "/freq-init-inputs/alias-secret"
        with (
            patch.object(setup_inputs.os.path, "isfile", side_effect=lambda path: path == alias_path),
            patch.object(setup_inputs.subprocess, "run") as run,
        ):
            self.assertEqual(
                serve_mod._setup_existing_secret_file(root_path, "alias_secret"),
                alias_path,
            )
            run.assert_not_called()

        with (
            patch.object(setup_inputs.os.path, "isfile", return_value=False),
            patch.object(
                setup_inputs.subprocess,
                "run",
                return_value=MagicMock(returncode=0),
            ) as run,
        ):
            self.assertEqual(
                serve_mod._setup_existing_secret_file(root_path, "alias_secret"),
                alias_path,
            )
        expected_alias_check = call(
            ["sudo", "-n", "test", "-f", alias_path],
            stdout=setup_inputs.subprocess.DEVNULL,
            stderr=setup_inputs.subprocess.DEVNULL,
            timeout=5,
        )
        self.assertEqual(run.call_args_list, [expected_alias_check, expected_alias_check])

        sudo_path = "/restricted/sudo-secret"
        with (
            patch.object(setup_inputs.os.path, "isfile", return_value=False),
            patch.object(
                setup_inputs.subprocess,
                "run",
                return_value=MagicMock(returncode=0),
            ) as run,
        ):
            self.assertEqual(
                serve_mod._setup_existing_secret_file(sudo_path, "sudo_secret"),
                sudo_path,
            )
            run.assert_called_once_with(
                ["sudo", "-n", "test", "-f", sudo_path],
                stdout=setup_inputs.subprocess.DEVNULL,
                stderr=setup_inputs.subprocess.DEVNULL,
                timeout=5,
            )

        missing_path = "/missing/secret"
        with (
            patch.object(setup_inputs.os.path, "isfile", return_value=False),
            patch.object(
                setup_inputs.subprocess,
                "run",
                return_value=MagicMock(returncode=1),
            ),
        ):
            with self.assertRaises(ValueError) as exc:
                serve_mod._setup_existing_secret_file(missing_path, "missing_secret")
            self.assertEqual(
                str(exc.exception),
                f"missing_secret file not found: {missing_path}",
            )

        for failure in (OSError("unavailable"), serve_mod.subprocess.SubprocessError("failed")):
            with (
                self.subTest(existence_failure=type(failure).__name__),
                patch.object(setup_inputs.os.path, "isfile", return_value=False),
                patch.object(setup_inputs.subprocess, "run", side_effect=failure),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    f"missing_secret file not found: {missing_path}",
                ):
                    serve_mod._setup_existing_secret_file(missing_path, "missing_secret")

        protected_path = "/restricted/protected-secret"
        with (
            patch.object(setup_inputs.os.path, "isfile", return_value=True),
            patch("builtins.open", side_effect=PermissionError),
            patch.object(
                setup_inputs.subprocess,
                "run",
                return_value=MagicMock(returncode=0, stdout="  sudo-value  \n"),
            ) as run,
        ):
            self.assertEqual(
                serve_mod._read_setup_secret_file(protected_path, "protected_secret"),
                "sudo-value",
            )
            run.assert_called_once_with(
                ["sudo", "-n", "cat", protected_path],
                capture_output=True,
                text=True,
                timeout=5,
            )

        with (
            patch.object(setup_inputs.os.path, "isfile", return_value=True),
            patch("builtins.open", side_effect=PermissionError),
            patch.object(
                setup_inputs.subprocess,
                "run",
                return_value=MagicMock(returncode=1, stdout=""),
            ),
        ):
            with self.assertRaises(PermissionError) as exc:
                serve_mod._read_setup_secret_file(protected_path, "protected_secret")
            self.assertEqual(
                str(exc.exception),
                f"protected_secret file is not readable: {protected_path}",
            )

        with (
            patch.object(setup_inputs.os.path, "isfile", return_value=True),
            patch("builtins.open", side_effect=OSError("read failed")),
            patch.object(setup_inputs.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(OSError, "read failed"):
                serve_mod._read_setup_secret_file(protected_path, "protected_secret")
        run.assert_not_called()

    def test_device_writer_keeps_canonical_sections_and_secret_files(self):
        import ast
        import inspect
        import tomllib

        from freq.modules import serve as serve_mod
        from freq.services import setup_inputs

        serve_tree = ast.parse(inspect.getsource(serve_mod))
        service_tree = ast.parse(inspect.getsource(setup_inputs))
        self.assertFalse(
            any(
                isinstance(node, ast.FunctionDef)
                and node.name == "_write_setup_device_credentials"
                for node in serve_tree.body
            )
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.FunctionDef)
                and node.name == "write_setup_device_credentials"
                for node in service_tree.body
            ),
            1,
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_write_setup_device_credentials"
                for node in ast.walk(serve_tree)
            ),
            0,
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "write_setup_device_credentials"
                for node in ast.walk(service_tree)
            ),
            1,
        )
        self.assertIs(
            serve_mod._write_setup_device_credentials,
            setup_inputs.write_setup_device_credentials,
        )
        writer = setup_inputs.write_setup_device_credentials

        with tempfile.TemporaryDirectory() as td:
            for empty in (None, "", [], [{"user": "ignored"}], {}):
                with self.subTest(empty=type(empty).__name__):
                    self.assertEqual(writer(td, empty), "")
            self.assertEqual(
                writer(td, {"!!!": {"user": "ignored"}, "not-a-row": []}),
                "",
            )
            self.assertEqual(os.listdir(td), [])

            path = writer(
                td,
                {
                    "switch_1": {
                        "type": "switch",
                        "target": "10.25.255.5",
                        "username": "switch-user",
                        "secret": "switch-secret",
                    },
                    "bmc_1": {
                        "type": "bmc",
                        "target": "bmc-10",
                        "username": "idrac-user",
                        "secret": "idrac-secret",
                    },
                    "firewall:pfsense": {
                        "target": "ignored-by-explicit-values",
                        "username": "ignored-alias-user",
                        "user": "firewall-user",
                        "secret": "ignored-alias-secret",
                        "password": "firewall-secret",
                        "host": "10.25.255.1",
                        "label": "edge-firewall",
                        "scope": "core",
                    },
                    "storage_1": {
                        "type": "truenas",
                        "host": "10.25.255.20",
                        "hosts": ["10.25.255.20", "10.25.255.21"],
                        "url": "https://10.25.255.20/api/v2.0",
                        "api_key": "truenas-api-secret",
                        "api_key_only": True,
                    },
                    "custom-section": {
                        "user": "custom-user",
                        "ssh_key_file": "/run/freq/custom-key",
                        "api_key_file": "/run/freq/custom-api-key",
                        "password_file": "/run/freq/custom-password",
                        "sudo_password_file": "/run/freq/custom-sudo-password",
                        "unknown": "must-not-be-projected",
                        "label": "",
                    },
                    "!!!": {"user": "empty-section-must-be-skipped"},
                    "not-a-row": ["must", "be", "skipped"],
                },
            )
            with open(path) as f:
                content = f.read()
            parsed = tomllib.loads(content)

            switch_secret = os.path.join(td, "switch-password")
            idrac_secret = os.path.join(td, "idrac-password")
            firewall_secret = os.path.join(td, "firewall:pfsense-password")
            truenas_api_key = os.path.join(td, "truenas-api-key")
            self.assertIn("[switch]", content)
            self.assertIn("[idrac]", content)
            self.assertIn('["firewall:pfsense"]', content)
            self.assertIn("[truenas]", content)
            self.assertIn("[custom-section]", content)
            self.assertNotIn("[switch_1]", content)
            self.assertNotIn("[bmc_1]", content)
            self.assertNotIn("[!!!]", content)
            self.assertNotIn("[not-a-row]", content)
            self.assertIn('host = "10.25.255.5"', content)
            self.assertIn('label = "bmc-10"', content)
            self.assertIn('user = "switch-user"', content)
            self.assertIn('user = "idrac-user"', content)
            self.assertIn(f'password_file = "{switch_secret}"', content)
            self.assertIn(f'password_file = "{idrac_secret}"', content)
            self.assertTrue(content.endswith("\n"))
            for secret in (
                "switch-secret",
                "idrac-secret",
                "firewall-secret",
                "ignored-alias-secret",
                "truenas-api-secret",
            ):
                self.assertNotIn(secret, content)
            self.assertNotIn("must-not-be-projected", content)
            self.assertEqual(
                parsed["firewall:pfsense"],
                {
                    "user": "firewall-user",
                    "password_file": firewall_secret,
                    "host": "10.25.255.1",
                    "label": "edge-firewall",
                    "scope": "core",
                },
            )
            self.assertEqual(
                parsed["truenas"],
                {
                    "host": "10.25.255.20",
                    "hosts": ["10.25.255.20", "10.25.255.21"],
                    "url": "https://10.25.255.20/api/v2.0",
                    "api_key_file": truenas_api_key,
                    "api_key_only": True,
                },
            )
            self.assertEqual(
                parsed["custom-section"],
                {
                    "user": "custom-user",
                    "ssh_key_file": "/run/freq/custom-key",
                    "api_key_file": "/run/freq/custom-api-key",
                    "password_file": "/run/freq/custom-password",
                    "sudo_password_file": "/run/freq/custom-sudo-password",
                },
            )

            for secret_path, expected in (
                (switch_secret, "switch-secret\n"),
                (idrac_secret, "idrac-secret\n"),
                (firewall_secret, "firewall-secret\n"),
                (truenas_api_key, "truenas-api-secret\n"),
            ):
                with open(secret_path) as f:
                    self.assertEqual(f.read(), expected)
            for secret_path in (
                path,
                switch_secret,
                idrac_secret,
                firewall_secret,
                truenas_api_key,
            ):
                self.assertEqual(stat.S_IMODE(os.stat(secret_path).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
