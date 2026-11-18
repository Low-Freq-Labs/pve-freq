"""Behavior contract for scope-safe pfSense/OPNsense target resolution."""

from ast import Assign, FunctionDef, Name, literal_eval, parse, walk
from hashlib import sha256
from inspect import getsource
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

from freq.core.types import PhysicalDevice


def _cfg(*, physical=None, hosts=None, pfsense_ip="", pve_nodes=None):
    return SimpleNamespace(
        conf_dir="/etc/freq",
        fleet_boundaries=SimpleNamespace(
            physical=physical or {},
            pve_nodes=pve_nodes or {},
        ),
        hosts=hosts or [],
        pfsense_ip=pfsense_ip,
    )


def _assert_pfsense_execution_contract(case):
    """Pin pfSense action execution and secret-safe result projection."""
    from freq.modules import serve
    from freq.services import device_command

    with case.subTest(case="execution ownership is lower, frozen, and directly bound"):
        case.assertTrue(device_command.PfSenseExecutionRuntime.__dataclass_params__.frozen)
        case.assertTrue(device_command.PfSenseExecutionResult.__dataclass_params__.frozen)
        case.assertIs(
            serve._resolve_pfsense_execution.func,
            device_command.resolve_pfsense_execution,
        )
        service_source = getsource(device_command)
        handler_source = getsource(serve.FreqHandler._serve_pfsense)
        case.assertNotIn("freq.modules", service_source)
        case.assertEqual(handler_source.count("_resolve_pfsense_execution("), 1)
        case.assertNotIn("resolve_staged_device_ssh_auth", handler_source)
        case.assertNotIn("ssh_single(", handler_source)
        case.assertNotIn("=== PF STATUS ===", handler_source)
        execution_function = next(
            node
            for node in walk(parse(service_source))
            if isinstance(node, FunctionDef) and node.name == "resolve_pfsense_execution"
        )
        actions_assignment = next(
            node
            for node in walk(execution_function)
            if isinstance(node, Assign)
            and any(isinstance(target, Name) and target.id == "actions" for target in node.targets)
        )
        actions = literal_eval(actions_assignment.value)
        action_payload = "\n".join(
            f"{name}\0{actions[name]}" for name in sorted(actions)
        ).encode()
        case.assertEqual(len(actions), 17)
        case.assertEqual(
            sha256(action_payload).hexdigest(),
            "07b683c191494f700cdfabdcb0df69fcb74635462c6262cf7ab1a95030b05e1b",
        )

    with case.subTest(case="lower failure result is bounded before transport"):
        lower_auth = Mock(
            return_value={
                "key_path": "/keys/pfsense",
                "user": "admin",
                "local_user": None,
                "password_file": None,
            }
        )
        long_error = "connection refused " + "x" * 120
        lower_ssh = Mock(
            return_value=SimpleNamespace(
                returncode=255,
                stdout="must not cross the service boundary",
                stderr=long_error,
            )
        )
        lower_redact = Mock()
        lower_result = device_command.resolve_pfsense_execution(
            SimpleNamespace(ssh_connect_timeout=11),
            "status",
            SimpleNamespace(ip="192.0.2.3", label="", key=""),
            runtime=device_command.PfSenseExecutionRuntime(
                resolve_auth=lower_auth,
                ssh_single=lower_ssh,
                redact_output=lower_redact,
            ),
        )
        case.assertEqual(lower_result.stdout, "")
        case.assertEqual(lower_result.stderr, long_error[:100])
        lower_redact.assert_not_called()

    handler = serve.FreqHandler.__new__(serve.FreqHandler)
    handler._json_response = Mock()
    cfg = SimpleNamespace(ssh_connect_timeout=11)

    with case.subTest(case="missing target performs no auth or SSH"):
        with (
            patch("freq.modules.serve.load_config", return_value=cfg) as load_config,
            patch(
                "freq.modules.serve._parse_query",
                return_value={"action": ["rules"], "target": ["missing-fw"]},
            ) as parse_query,
            patch("freq.modules.serve._resolve_pfsense_target", return_value=None) as resolve_target,
            patch("freq.modules.serve.resolve_staged_device_ssh_auth") as resolve_auth,
            patch("freq.modules.serve.ssh_single") as ssh,
        ):
            handler._serve_pfsense()
        load_config.assert_called_once_with()
        parse_query.assert_called_once_with(handler)
        resolve_target.assert_called_once_with(cfg, "missing-fw")
        resolve_auth.assert_not_called()
        ssh.assert_not_called()
        handler._json_response.assert_called_once_with(
            {
                "error": "pfSense target not configured",
                "data": {},
                "target": "missing-fw",
            },
            400,
        )

    with case.subTest(case="selected action uses exact SSH boundary and redacted success"):
        handler._json_response.reset_mock()
        target = SimpleNamespace(ip="192.0.2.1", label="", key="lab-fw")
        auth = {
            "key_path": "/keys/pfsense",
            "user": "freq-ops",
            "local_user": "svc-freq",
            "password_file": "",
        }
        result = SimpleNamespace(returncode=0, stdout="private command output", stderr="")
        with (
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch(
                "freq.modules.serve._parse_query",
                return_value={
                    "action": ["interfaces", "ignored"],
                    "target": ["lab-fw", "ignored"],
                },
            ),
            patch("freq.modules.serve._resolve_pfsense_target", return_value=target) as resolve_target,
            patch(
                "freq.modules.serve.resolve_staged_device_ssh_auth",
                return_value=auth,
            ) as resolve_auth,
            patch("freq.modules.serve.ssh_single", return_value=result) as ssh,
            patch(
                "freq.modules.serve._redact_device_command_output",
                return_value="safe output",
            ) as redact,
        ):
            handler._serve_pfsense()
        resolve_target.assert_called_once_with(cfg, "lab-fw")
        resolve_auth.assert_called_once_with(cfg, "pfsense")
        ssh.assert_called_once()
        ssh_args = ssh.call_args.kwargs
        case.assertEqual(
            {key: ssh_args[key] for key in ssh_args if key != "command"},
            {
                "host": "192.0.2.1",
                "key_path": "/keys/pfsense",
                "user": "freq-ops",
                "local_user": "svc-freq",
                "password_file": None,
                "sudo_password_file": False,
                "connect_timeout": 11,
                "command_timeout": 15,
                "htype": "pfsense",
                "use_sudo": False,
                "cfg": cfg,
                "failure_log_level": "warn",
            },
        )
        case.assertIn("=== INTERFACES ===", ssh_args["command"])
        case.assertIn("no IP assigned", ssh_args["command"])
        redact.assert_called_once_with("private command output")
        handler._json_response.assert_called_once_with(
            {
                "action": "interfaces",
                "target": "lab-fw",
                "label": "lab-fw",
                "host": "192.0.2.1",
                "ip": "192.0.2.1",
                "reachable": True,
                "auth_failed": False,
                "probe_method": "ssh",
                "output": "safe output",
                "error": "",
            }
        )

    failure_cases = (
        ("Permission Denied for operator", True, "ssh_auth_failed"),
        ("PUBLICKEY rejected", True, "ssh_auth_failed"),
        ("connection refused " + "x" * 120, False, "ssh_failed"),
    )
    for stderr, auth_failed, probe_method in failure_cases:
        with case.subTest(
            case="unknown action defaults command and failure truth",
            stderr=stderr[:20],
        ):
            handler._json_response.reset_mock()
            target = SimpleNamespace(ip="192.0.2.2", label="", key="")
            auth = {
                "key_path": "/keys/pfsense",
                "user": "admin",
                "local_user": None,
                "password_file": "/run/pfsense-password",
                "sudo_password_file": True,
            }
            result = SimpleNamespace(returncode=255, stdout="must not leak", stderr=stderr)
            with (
                patch("freq.modules.serve.load_config", return_value=cfg),
                patch(
                    "freq.modules.serve._parse_query",
                    return_value={"action": ["unknown-action"]},
                ),
                patch("freq.modules.serve._resolve_pfsense_target", return_value=target),
                patch(
                    "freq.modules.serve.resolve_staged_device_ssh_auth",
                    return_value=auth,
                ),
                patch("freq.modules.serve.ssh_single", return_value=result) as ssh,
                patch("freq.modules.serve._redact_device_command_output") as redact,
            ):
                handler._serve_pfsense()
            command = ssh.call_args.kwargs["command"]
            case.assertIn("=== SYSTEM ===", command)
            case.assertIn("=== PF STATUS ===", command)
            redact.assert_not_called()
            handler._json_response.assert_called_once_with(
                {
                    "action": "unknown-action",
                    "target": "firewall",
                    "label": "firewall",
                    "host": "192.0.2.2",
                    "ip": "192.0.2.2",
                    "reachable": False,
                    "auth_failed": auth_failed,
                    "probe_method": probe_method,
                    "output": "",
                    "error": stderr[:100],
                }
            )


class TestPfSenseTargetResolution(TestCase):
    def test_scope_safe_target_resolution_contract(self):
        from freq.modules.serve import _resolve_pfsense_target

        lab = PhysicalDevice(
            key="pfsense-lab",
            ip="10.25.10.200",
            label="Lab firewall",
            device_type="pfsense",
            groups="lab",
            scope="lab",
        )
        core = PhysicalDevice(
            key="",
            ip="10.25.255.1",
            label="Core firewall",
            device_type="pfsense",
            scope="core",
        )
        cfg = _cfg(physical={"lab-fw": lab, "core-fw": core})
        with self.subTest(case="default selects non-lab core and adopts mapping key"), patch(
            "freq.modules.serve.load_toml",
        ) as load_inventory:
            resolved = _resolve_pfsense_target(cfg)
            self.assertIs(resolved, core)
            self.assertEqual(resolved.key, "core-fw")
            self.assertEqual((resolved.ip, resolved.label, resolved.device_type, resolved.scope), (
                "10.25.255.1",
                "Core firewall",
                "pfsense",
                "core",
            ))
            load_inventory.assert_not_called()

        with self.subTest(case="configured core IP synthesizes exact core identity"), patch(
            "freq.modules.serve.load_toml",
        ) as load_inventory:
            resolved = _resolve_pfsense_target(_cfg(pfsense_ip="10.25.255.1"))
            self.assertEqual(
                (resolved.key, resolved.ip, resolved.label, resolved.device_type, resolved.scope),
                ("pfsense", "10.25.255.1", "firewall", "pfsense", "core"),
            )
            load_inventory.assert_not_called()

        lab_host = SimpleNamespace(
            ip="10.25.10.201",
            label="pfsense-host-lab",
            htype="linux",
            groups="lab",
            vmid=5001,
            all_ips=["192.168.201.1", "10.25.10.201"],
            display_name="Lab pfSense host",
            hostname="pfsense-host",
        )
        core_host = SimpleNamespace(
            ip="10.25.255.2",
            label="edge-firewall",
            htype="pfsense",
            groups="core edge",
            vmid="",
            all_ips=["10.25.255.2"],
            display_name="Core host firewall",
            hostname="firewall-core",
        )
        with self.subTest(case="default selects core host after lab host"), patch(
            "freq.modules.serve.load_toml",
        ) as load_inventory:
            resolved = _resolve_pfsense_target(_cfg(hosts=[lab_host, core_host]))
            self.assertEqual(
                (
                    resolved.key,
                    resolved.ip,
                    resolved.label,
                    resolved.device_type,
                    resolved.tier,
                    resolved.detail,
                    resolved.groups,
                    resolved.scope,
                    resolved.hostname,
                    resolved.display_name,
                ),
                (
                    "edge-firewall",
                    "10.25.255.2",
                    "Core host firewall",
                    "pfsense",
                    "probe",
                    "Firewall",
                    "core edge",
                    "core",
                    "firewall-core",
                    "Core host firewall",
                ),
            )
            load_inventory.assert_not_called()

        for label, cfg in (
            ("physical", _cfg(physical={"lab-fw": lab})),
            ("host", _cfg(hosts=[lab_host])),
        ):
            with self.subTest(case="lab-only default is fail-closed", source=label), patch(
                "freq.modules.serve.load_toml",
            ) as load_inventory:
                self.assertIsNone(_resolve_pfsense_target(cfg))
                load_inventory.assert_not_called()

        opnsense_host = SimpleNamespace(
            ip="10.25.10.202",
            label="opnsense-lab",
            htype="linux",
            groups="lab edge",
            vmid=5002,
            all_ips=["192.168.202.1", "10.25.10.202"],
            display_name="Lab OPNsense",
            hostname="opnsense-host",
        )
        for target, host, expected in (
            (
                "pfsense-host-lab",
                lab_host,
                (
                    "pfsense-host-lab",
                    "10.25.10.201",
                    "Lab pfSense host",
                    "pfsense",
                    "probe",
                    "Firewall",
                    "lab",
                    "pfsense-host",
                    "Lab pfSense host",
                ),
            ),
            (
                "opnsense-lab",
                opnsense_host,
                (
                    "opnsense-lab",
                    "10.25.10.202",
                    "Lab OPNsense",
                    "opnsense",
                    "probe",
                    "Firewall",
                    "lab edge",
                    "opnsense-host",
                    "Lab OPNsense",
                ),
            ),
        ):
            with self.subTest(case="explicit host-derived firewall", target=target), patch(
                "freq.modules.serve.load_toml",
            ) as load_inventory:
                resolved = _resolve_pfsense_target(_cfg(hosts=[host]), target)
                self.assertEqual(
                    (
                        resolved.key,
                        resolved.ip,
                        resolved.label,
                        resolved.device_type,
                        resolved.tier,
                        resolved.detail,
                        resolved.groups,
                        resolved.hostname,
                        resolved.display_name,
                    ),
                    expected,
                )
                self.assertEqual(resolved.scope, "lab")
                load_inventory.assert_not_called()

        direct = PhysicalDevice(
            key="branch-fw",
            ip="10.25.10.210",
            label="Branch firewall",
            device_type="pfsense",
            scope="core",
            display_name="Branch edge",
        )
        for target in (direct.key, direct.label, direct.ip, direct.display_name):
            with self.subTest(case="direct identity wins before inventory", target=target), patch(
                "freq.modules.serve.load_toml",
                side_effect=AssertionError("inventory must not be read"),
            ):
                self.assertIs(_resolve_pfsense_target(_cfg(physical={"branch-fw": direct}), target), direct)

        inventory = {
            "resource": [
                "not-a-table",
                {"name": "database", "vmid": 100, "description": "10.25.10.10"},
                {"name": "pfsense-invalid", "vmid": 5000, "description": "WAN 999.25.10.1"},
                {
                    "name": "opnsense-lab",
                    "vmid": 5002,
                    "node": "pve02",
                    "tags": "firewall;lab;opnsense",
                    "description": "fallback WAN 10.25.10.220",
                },
            ]
        }
        inventory_cfg = _cfg(pve_nodes={"pve02": SimpleNamespace(ip="10.25.255.27")})
        pve_call = call(
            inventory_cfg,
            "10.25.255.27",
            api_endpoint="/nodes/pve02/qemu/5002/config",
            ssh_command="pvesh get /nodes/pve02/qemu/5002/config --output-format json",
            timeout=10,
        )
        for target in ("opnsense-lab", "current", "10.25.10.221"):
            with self.subTest(case="inventory identity description and IP matching", target=target), patch(
                "freq.modules.serve.load_toml",
                return_value=inventory,
            ) as load_inventory, patch(
                "freq.modules.pve._pve_call",
                return_value=({"description": "current WAN 10.25.10.221"}, True),
            ) as call_pve:
                resolved = _resolve_pfsense_target(inventory_cfg, target)
                load_inventory.assert_called_once_with("/etc/freq/pve-inventory.toml")
                self.assertEqual(call_pve.call_args, pve_call)
                self.assertEqual(
                    (
                        resolved.key,
                        resolved.ip,
                        resolved.label,
                        resolved.device_type,
                        resolved.tier,
                        resolved.detail,
                        resolved.groups,
                        resolved.scope,
                    ),
                    (
                        "opnsense-lab",
                        "10.25.10.221",
                        "opnsense-lab",
                        "opnsense",
                        "probe",
                        "Firewall",
                        "lab",
                        "lab",
                    ),
                )

        for label, pve_result in (
            ("PVE reports failure", ({}, False)),
            ("PVE raises", RuntimeError("PVE unavailable")),
        ):
            pve_patch = (
                patch("freq.modules.pve._pve_call", side_effect=pve_result)
                if isinstance(pve_result, Exception)
                else patch("freq.modules.pve._pve_call", return_value=pve_result)
            )
            with self.subTest(case="PVE failure keeps inventory description", failure=label), patch(
                "freq.modules.serve.load_toml",
                return_value=inventory,
            ), pve_patch:
                resolved = _resolve_pfsense_target(inventory_cfg, "opnsense-lab")
                self.assertEqual(resolved.ip, "10.25.10.220")

        invalid_only = {
            "resource": [
                {"name": "pfsense-lab", "vmid": 5000, "description": "WAN 999.25.10.1"},
            ]
        }
        with self.subTest(case="invalid inventory IPv4 is rejected"), patch(
            "freq.modules.serve.load_toml",
            return_value=invalid_only,
        ):
            self.assertIsNone(_resolve_pfsense_target(_cfg(), "pfsense-lab"))

        with self.subTest(case="explicit unknown never falls back to core"), patch(
            "freq.modules.serve.load_toml",
            return_value={"resource": []},
        ):
            self.assertIsNone(
                _resolve_pfsense_target(
                    _cfg(physical={"branch-fw": direct}, pfsense_ip="10.25.255.1"),
                    "unknown-firewall",
                )
            )

        _assert_pfsense_execution_contract(self)
