"""Safety owner for the init phase-orchestrator refactor.

The individual init phases have broad behavioral coverage, but the two public
entry paths historically owned their sequencing only as duplicated inline code.
This matrix pins the observable phase topology, current fail-closed outcomes,
the non-mutating dry-run route, and exact in-memory plus durable PhaseResult
consumption. It also owns pre-Phase-1 interruption preservation, the private
web-child signal consumer, pre-PONR cancellation resource cleanup, bounded
in-memory rollback for authenticated web cancellation, and the backend
cancellation endpoint. It also owns authenticated-web validation and ordinary
failure in-memory plus private-topology rollback before the PONR path, but does
not claim post-PONR rollback. It also owns interactive pre-PONR interruption
rollback before any Phase 1 boundary transition, and non-web headless ordinary
failure rollback before the same durable boundary.
"""

import copy
import hashlib
import json
import os
import stat
import tempfile
import types
import unittest
from contextlib import ExitStack
from unittest import mock

from freq.core.types import INIT_PHASES, PhaseIdentity, PhaseInput, PhaseResult, PhaseStatus
from tests.case_matrix import run_case_matrix

HEADLESS_PHASE_TITLE_OVERRIDES = {
    3: "Local Service Account",
    11: "RBAC Setup",
}

INTERACTIVE_SUCCESS_CALLS = (
    "prerequisites",
    "configure",
    "bootstrap_auth",
    "vlan_discovery",
    "service_account",
    "ssh_keys",
    "pve_deploy",
    "pve_api_token",
    "fleet_discovery",
    "fleet_deployment",
    "fleet_configuration",
    "pdm",
    "reconcile",
    "admin_accounts",
    "verification",
    "summary",
)

HEADLESS_SUCCESS_CALLS = (
    "prerequisites",
    "configure",
    "vlan_discovery",
    "service_account",
    "ssh_keys",
    "admin_accounts",
    "pve_deploy",
    "pve_api_token",
    "fleet_discovery",
    "fleet_deployment",
    "fleet_configuration",
    "pdm",
    "reconcile",
    "admin_accounts",
    "verification",
    "summary",
)


class TestInitOrchestratorContract(unittest.TestCase):
    def _cfg(self, root):
        return types.SimpleNamespace(
            conf_dir=os.path.join(root, "conf"),
            data_dir=os.path.join(root, "data"),
            key_dir=os.path.join(root, "keys"),
            vault_file=os.path.join(root, "vault", "vault.enc"),
            log_dir=os.path.join(root, "log"),
            credentials_dir=os.path.join(root, "credentials"),
            hosts_file=os.path.join(root, "hosts.toml"),
            install_dir=root,
            version="test",
            ssh_service_account="freq-admin",
            pve_nodes=[],
            hosts=[],
            vlans=["configured"],
        )

    @staticmethod
    def _args(**overrides):
        values = {
            "check": False,
            "reset": False,
            "dry_run": False,
            "uninstall": False,
            "fix": False,
            "headless": False,
            "yes": True,
        }
        values.update(overrides)
        return types.SimpleNamespace(**values)

    @staticmethod
    def _run_id(label):
        return hashlib.sha256(label.encode("utf-8")).hexdigest()[:32]

    def _assert_result_ledger(
        self,
        results,
        count,
        *,
        failed_number=None,
        expected_identities=None,
    ):
        self.assertIsInstance(results, tuple)
        self.assertEqual(len(results), count)
        self.assertTrue(all(isinstance(result, PhaseResult) for result in results))
        self.assertEqual(
            [result.identity.number for result in results],
            list(range(1, count + 1)),
        )
        if expected_identities is not None:
            self.assertEqual(len(expected_identities), count)
            self.assertTrue(
                all(
                    result.identity is expected
                    for result, expected in zip(results, expected_identities, strict=True)
                )
            )
        expected_statuses = [PhaseStatus.SUCCEEDED] * count
        if failed_number is not None:
            expected_statuses[failed_number - 1] = PhaseStatus.FAILED
        self.assertEqual([result.status for result in results], expected_statuses)
        for result in results:
            if result.status is PhaseStatus.FAILED:
                self.assertTrue(result.error)
            else:
                self.assertIsNone(result.error)

    def _run_interactive(
        self,
        *,
        welcome=True,
        service_account_rc=0,
        fleet_discovery_failed=False,
        verified=True,
        injected_catalog=None,
    ):
        from freq.modules import init_cmd

        calls = []
        headers = []
        with tempfile.TemporaryDirectory(prefix="freq-init-owner-") as root, ExitStack() as stack:
            cfg = self._cfg(root)
            args = self._args()
            stack.enter_context(mock.patch.object(init_cmd.os, "geteuid", return_value=0))
            stack.enter_context(mock.patch("freq.core.personality.splash"))
            stack.enter_context(mock.patch.object(init_cmd, "_apply_operator_vm_contract_args"))
            finish_phase = stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_finish_init_phase",
                    wraps=init_cmd._finish_init_phase,
                )
            )
            begin_phase = None
            catalog_call_args = None
            if injected_catalog is not None:
                catalog = stack.enter_context(
                    mock.patch.object(init_cmd, "phase_catalog", return_value=injected_catalog)
                )
                begin_phase = stack.enter_context(
                    mock.patch.object(
                        init_cmd,
                        "_begin_init_phase",
                        wraps=init_cmd._begin_init_phase,
                    )
                )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase",
                    side_effect=lambda number, total, title: headers.append((number, total, title)),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase_welcome",
                    side_effect=lambda _cfg: calls.append("prerequisites") or welcome,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase_configure",
                    side_effect=lambda _cfg, _args: calls.append("configure"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_collect_bootstrap_auth",
                    side_effect=lambda _cfg, _ctx, _args: calls.append("bootstrap_auth"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_discover_vlans_from_pve",
                    side_effect=lambda _cfg, _ctx: calls.append("vlan_discovery"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase_service_account",
                    side_effect=lambda _cfg, _ctx, _args: calls.append("service_account")
                    or service_account_rc,
                )
            )
            simple_phases = {
                "_phase_ssh_keys": "ssh_keys",
                "_phase_pve_deploy": "pve_deploy",
                "_phase_pve_api_token": "pve_api_token",
                "_phase_fleet_deploy": "fleet_deployment",
                "_phase_fleet_configure": "fleet_configuration",
                "_phase_pdm": "pdm",
                "_phase_admin_setup": "admin_accounts",
            }
            for name, label in simple_phases.items():
                stack.enter_context(
                    mock.patch.object(
                        init_cmd,
                        name,
                        side_effect=lambda *args, _label=label, **kwargs: calls.append(_label),
                    )
                )

            def record_fleet_discovery(_cfg, ctx, _args):
                calls.append("fleet_discovery")
                if fleet_discovery_failed:
                    ctx["fleet_discovery_failed"] = True

            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase_fleet_discover",
                    side_effect=record_fleet_discovery,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_reconcile_existing_managed_hosts",
                    side_effect=lambda _cfg, _ctx: calls.append("reconcile") or [],
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase_verify",
                    side_effect=lambda _cfg, _ctx: calls.append("verification") or verified,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase_summary",
                    side_effect=lambda _cfg, _ctx, _verified, _pack: calls.append("summary"),
                )
            )
            stack.enter_context(
                mock.patch.object(init_cmd, "_ensure_post_init_runtime_state_ownership", return_value=True)
            )
            stack.enter_context(mock.patch.object(init_cmd, "_chown", return_value=True))
            stack.enter_context(mock.patch.object(init_cmd, "_run", return_value=(1, "", "")))

            rc = init_cmd.cmd_init(cfg, None, args)
            if injected_catalog is not None:
                catalog_call_args = catalog.call_args_list
        started_identities = (
            [] if begin_phase is None else [call.args[0] for call in begin_phase.call_args_list]
        )
        result_context = (
            None if not finish_phase.call_args_list else finish_phase.call_args_list[-1].args[1]
        )
        phase_results = () if result_context is None else result_context.get("_phase_results", ())
        return rc, headers, calls, started_identities, catalog_call_args, phase_results

    def _case_interactive_executes_canonical_order(self):
        rc, headers, calls, _started, _catalog_calls, phase_results = self._run_interactive()
        self.assertEqual(rc, 0)
        self.assertEqual(
            [(number, title) for number, _total, title in headers],
            [(identity.number, identity.title) for identity in INIT_PHASES],
        )
        self.assertTrue(all(total == len(INIT_PHASES) for _number, total, _title in headers))
        self.assertEqual(tuple(calls), INTERACTIVE_SUCCESS_CALLS)
        self._assert_result_ledger(phase_results, len(INIT_PHASES))

    def _run_headless(
        self,
        *,
        welcome=True,
        local_account=True,
        fleet_discovery_failed=False,
        verified=True,
        catalog_override=None,
        prepare=None,
        observe=None,
        bootstrap_auth="key",
        service_account_valid=True,
    ):
        from freq.modules import init_cmd

        calls = []
        headers = []
        injected_catalog = catalog_override or tuple(
            PhaseIdentity(identity.number, f"injected_{identity.key}", identity.title)
            for identity in INIT_PHASES
        )
        with tempfile.TemporaryDirectory(prefix="freq-init-owner-") as root, ExitStack() as stack:
            cfg = self._cfg(root)
            bootstrap_key = os.path.join(root, "bootstrap-key")
            bootstrap_password_file = os.path.join(root, "bootstrap-password")
            password_file = os.path.join(root, "service-password")
            dashboard_password_file = os.path.join(root, "dashboard-password")
            for path, value in (
                (bootstrap_key, "key"),
                (bootstrap_password_file, "bootstrap-password"),
                (password_file, "service-password"),
                (dashboard_password_file, "dashboard-password"),
            ):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(value)
            args = self._args(
                headless=True,
                bootstrap_key=bootstrap_key if bootstrap_auth == "key" else None,
                bootstrap_user="root",
                bootstrap_password_file=(
                    bootstrap_password_file
                    if bootstrap_auth == "password"
                    else None
                ),
                password_file=password_file,
                dashboard_user="operator",
                dashboard_password_file=dashboard_password_file,
                device_credentials=None,
                device_password_file=None,
                device_user="root",
                service_account="freq-admin",
                hosts_file=None,
            )
            if prepare is not None:
                prepare(cfg, args)
            stack.enter_context(mock.patch.object(init_cmd.os, "geteuid", return_value=0))
            stack.enter_context(mock.patch.dict(os.environ, {"FREQ_WEB_INIT": "1"}))
            stack.enter_context(mock.patch.object(init_cmd, "_apply_operator_vm_contract_args"))
            finish_phase = stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_finish_init_phase",
                    wraps=init_cmd._finish_init_phase,
                )
            )
            catalog = stack.enter_context(
                mock.patch.object(init_cmd, "phase_catalog", return_value=injected_catalog)
            )
            begin_phase = stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_begin_init_phase",
                    wraps=init_cmd._begin_init_phase,
                )
            )
            stack.enter_context(mock.patch.object(init_cmd, "_load_device_credentials", return_value={}))
            for name in (
                "_validate_device_scoped_service_password",
                "_validate_truenas_deployment_credentials",
                "_validate_device_credential_scopes",
                "_validate_username",
            ):
                stack.enter_context(mock.patch.object(init_cmd, name, return_value=True))
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_validate_service_account_choice",
                    return_value=service_account_valid,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase",
                    side_effect=lambda number, total, title: headers.append((number, total, title)),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase_welcome",
                    side_effect=lambda _cfg: calls.append("prerequisites") or welcome,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase_configure",
                    side_effect=lambda _cfg, _args: calls.append("configure"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_discover_vlans_from_pve",
                    side_effect=lambda _cfg, _ctx: calls.append("vlan_discovery"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_headless_local_account",
                    side_effect=lambda _cfg, _ctx: calls.append("service_account")
                    or local_account,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase_ssh_keys",
                    side_effect=lambda _cfg, _ctx: calls.append("ssh_keys"),
                )
            )
            deploy_count = 0

            def record_deploy(*args, **kwargs):
                nonlocal deploy_count
                deploy_count += 1
                calls.append("pve_deploy" if kwargs.get("pve_only") else "fleet_deployment")

            stack.enter_context(mock.patch.object(init_cmd, "_headless_fleet_deploy", side_effect=record_deploy))
            for name, label in (
                ("_phase_pve_api_token", "pve_api_token"),
                ("_phase_fleet_configure", "fleet_configuration"),
                ("_phase_pdm", "pdm"),
            ):
                stack.enter_context(
                    mock.patch.object(
                        init_cmd,
                        name,
                        side_effect=lambda *args, _label=label, **kwargs: calls.append(_label),
                    )
                )

            def record_fleet_discovery(_cfg, ctx, _args):
                calls.append("fleet_discovery")
                if fleet_discovery_failed:
                    ctx["fleet_discovery_failed"] = True

            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase_fleet_discover",
                    side_effect=record_fleet_discovery,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_reconcile_existing_managed_hosts",
                    side_effect=lambda _cfg, _ctx: calls.append("reconcile") or [],
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_seed_headless_dashboard_auth",
                    side_effect=lambda *_args, **_kwargs: calls.append("admin_accounts") or True,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase_verify",
                    side_effect=lambda _cfg, _ctx: calls.append("verification") or verified,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    init_cmd,
                    "_phase_summary",
                    side_effect=lambda _cfg, _ctx, _verified, _pack=None: calls.append("summary"),
                )
            )
            for name in (
                "_clear_generated_runtime_truth_state",
                "_persist_runtime_device_credentials_metadata",
                "_seed_truenas_api_key_from_device_creds",
            ):
                stack.enter_context(mock.patch.object(init_cmd, name))
            stack.enter_context(
                mock.patch.object(init_cmd, "_ensure_post_init_runtime_state_ownership", return_value=True)
            )
            stack.enter_context(mock.patch.object(init_cmd, "_chown", return_value=True))

            rc = init_cmd.cmd_init(cfg, None, args)
            if observe is not None:
                observe(cfg)

        started_identities = [call.args[0] for call in begin_phase.call_args_list]
        result_context = (
            None if not finish_phase.call_args_list else finish_phase.call_args_list[-1].args[1]
        )
        phase_results = () if result_context is None else result_context.get("_phase_results", ())
        return (
            rc,
            headers,
            calls,
            started_identities,
            catalog.call_args_list,
            deploy_count,
            injected_catalog,
            phase_results,
        )

    def _case_headless_executes_canonical_order(self):
        rc, headers, calls, started, catalog_calls, deploy_count, injected_catalog, phase_results = (
            self._run_headless()
        )
        self.assertEqual(rc, 0)
        self.assertEqual(deploy_count, 2)
        self.assertEqual(catalog_calls, [mock.call()])
        self.assertTrue(
            all(
                actual is identity
                for actual, identity in zip(
                    started,
                    injected_catalog,
                    strict=True,
                )
            )
        )
        headless_identities = INIT_PHASES
        self.assertEqual(
            [(number, title) for number, _total, title in headers],
            [
                (
                    identity.number,
                    HEADLESS_PHASE_TITLE_OVERRIDES.get(identity.number, identity.title),
                )
                for identity in headless_identities
            ],
        )
        self.assertTrue(
            all(total == len(headless_identities) for _number, total, _title in headers)
        )
        self.assertEqual(tuple(calls), HEADLESS_SUCCESS_CALLS)
        self._assert_result_ledger(
            phase_results,
            len(INIT_PHASES),
            expected_identities=injected_catalog,
        )

    def _case_failure_stops_before_later_mutation(self):
        rc, headers, calls, _started, _catalog_calls, phase_results = self._run_interactive(
            service_account_rc=1
        )
        self.assertEqual(rc, 1)
        self.assertEqual([number for number, _total, _title in headers], [1, 2, 3])
        self.assertEqual(
            calls,
            [
                "prerequisites",
                "configure",
                "bootstrap_auth",
                "vlan_discovery",
                "service_account",
            ],
        )
        self._assert_result_ledger(phase_results, 3, failed_number=3)

        (
            rc,
            headers,
            calls,
            _started,
            _catalog_calls,
            deploy_count,
            _catalog,
            phase_results,
        ) = self._run_headless(local_account=False)
        self.assertEqual(rc, 1)
        self.assertEqual([number for number, _total, _title in headers], [1, 2, 3])
        self.assertEqual(
            calls,
            [
                "prerequisites",
                "configure",
                "vlan_discovery",
                "service_account",
            ],
        )
        self.assertEqual(deploy_count, 0)
        self._assert_result_ledger(phase_results, 3, failed_number=3)

    def _case_welcome_failure_stops_both_paths_at_phase_one(self):
        interactive = self._run_interactive(welcome=False)
        headless = self._run_headless(welcome=False)

        for mode, rc, headers, calls, phase_results in (
            ("interactive", interactive[0], interactive[1], interactive[2], interactive[5]),
            ("headless", headless[0], headless[1], headless[2], headless[7]),
        ):
            with self.subTest(mode=mode):
                self.assertEqual(rc, 1)
                self.assertEqual([number for number, _total, _title in headers], [1])
                self.assertEqual(calls, ["prerequisites"])
                self._assert_result_ledger(phase_results, 1, failed_number=1)

    def _case_fleet_discovery_failure_stops_both_paths_at_phase_seven(self):
        interactive = self._run_interactive(fleet_discovery_failed=True)
        headless = self._run_headless(fleet_discovery_failed=True)

        self.assertEqual(interactive[0], 1)
        self.assertEqual(
            [number for number, _total, _title in interactive[1]],
            list(range(1, 8)),
        )
        self.assertEqual(tuple(interactive[2]), INTERACTIVE_SUCCESS_CALLS[:9])
        self._assert_result_ledger(interactive[5], 7, failed_number=7)

        self.assertEqual(headless[0], 1)
        self.assertEqual(
            [number for number, _total, _title in headless[1]],
            list(range(1, 8)),
        )
        self.assertEqual(tuple(headless[2]), HEADLESS_SUCCESS_CALLS[:9])
        self.assertEqual(headless[5], 1)
        self._assert_result_ledger(headless[7], 7, failed_number=7)

    def _case_verification_failure_completes_current_topology(self):
        interactive = self._run_interactive(verified=False)
        headless = self._run_headless(verified=False)

        self.assertEqual(interactive[0], 1)
        self.assertEqual(
            [number for number, _total, _title in interactive[1]],
            list(range(1, 14)),
        )
        self.assertEqual(tuple(interactive[2]), INTERACTIVE_SUCCESS_CALLS)
        self.assertEqual(interactive[2][-1], "summary")
        self._assert_result_ledger(interactive[5], 13, failed_number=12)

        self.assertEqual(headless[0], 1)
        self.assertEqual(
            [number for number, _total, _title in headless[1]],
            list(range(1, 14)),
        )
        self.assertEqual(tuple(headless[2]), HEADLESS_SUCCESS_CALLS)
        self.assertEqual(headless[5], 2)
        self.assertEqual(headless[2][-1], "summary")
        self._assert_result_ledger(headless[7], 13, failed_number=12)

    def _case_dry_run_routes_before_root_and_mutating_phases(self):
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory(prefix="freq-init-owner-") as root:
            cfg = self._cfg(root)
            cfg.pve_nodes = ["192.0.2.10"]
            os.makedirs(cfg.conf_dir)
            os.makedirs(cfg.data_dir)
            status_path = os.path.join(cfg.conf_dir, "init-status.json")
            with open(status_path, "wb") as status_file:
                status_file.write(b'{"state":"prior"}\n')
            os.chmod(status_path, 0o600)
            with open(os.path.join(cfg.data_dir, "prior-state"), "wb") as state_file:
                state_file.write(b"prior-state\n")

            def snapshot_tree():
                snapshot = {}
                paths = [root]
                for directory, dirnames, filenames in os.walk(root):
                    paths.extend(os.path.join(directory, name) for name in dirnames)
                    paths.extend(os.path.join(directory, name) for name in filenames)
                for path in paths:
                    observed = os.lstat(path)
                    file_type = stat.S_IFMT(observed.st_mode)
                    contents = None
                    if stat.S_ISREG(file_type):
                        with open(path, "rb") as observed_file:
                            contents = observed_file.read()
                    snapshot[os.path.relpath(path, root)] = {
                        "type": file_type,
                        "device": observed.st_dev,
                        "inode": observed.st_ino,
                        "mode": stat.S_IMODE(observed.st_mode),
                        "uid": observed.st_uid,
                        "gid": observed.st_gid,
                        "size": observed.st_size,
                        "mtime_ns": observed.st_mtime_ns,
                        "ctime_ns": observed.st_ctime_ns,
                        "symlink_target": os.readlink(path)
                        if stat.S_ISLNK(file_type)
                        else None,
                        "contents": contents,
                    }
                return snapshot

            before_cfg_mapping = vars(cfg)
            before_cfg = copy.deepcopy(before_cfg_mapping)
            before_mutable_cfg_members = {
                name: value
                for name, value in before_cfg_mapping.items()
                if isinstance(value, (bytearray, dict, list, set))
            }
            before_tree = snapshot_tree()
            before_init_marker = init_cmd.INIT_MARKER
            args = self._args(
                dry_run=True,
                service_account="preview-svc",
                pve_nodes="192.0.2.20, 192.0.2.21",
                owned_vmids="100-102",
            )
            lines = []
            colors = types.SimpleNamespace(DIM="", RESET="", BOLD="")
            with mock.patch.object(
                init_cmd,
                "_apply_operator_vm_contract_args",
                wraps=init_cmd._apply_operator_vm_contract_args,
            ) as apply_contract, mock.patch.object(
                init_cmd.os, "geteuid", side_effect=AssertionError("dry-run reached root gate")
            ), mock.patch.object(
                init_cmd, "_phase_welcome", side_effect=AssertionError("dry-run mutated phase state")
            ), mock.patch.object(
                init_cmd, "_run", side_effect=AssertionError("dry-run launched subprocess work")
            ), mock.patch.object(
                init_cmd.subprocess,
                "run",
                side_effect=AssertionError("dry-run launched subprocess work"),
            ), mock.patch.object(
                init_cmd,
                "_cross_init_point_of_no_return",
                side_effect=AssertionError("dry-run reached PONR"),
            ), mock.patch.object(init_cmd, "fmt") as output:
                output.C = colors
                output.line.side_effect = lines.append
                self.assertEqual(init_cmd.cmd_init(cfg, None, args), 0)
            apply_contract.assert_not_called()
            self.assertIs(vars(cfg), before_cfg_mapping)
            self.assertEqual(vars(cfg), before_cfg)
            for name, value in before_mutable_cfg_members.items():
                self.assertIs(getattr(cfg, name), value)
            self.assertEqual(snapshot_tree(), before_tree)
            self.assertEqual(stat.S_IMODE(os.lstat(status_path).st_mode), 0o600)
            self.assertIs(init_cmd.INIT_MARKER, before_init_marker)
            plan = "\n".join(lines)
            self.assertIn("Deploy preview-svc to 2 PVE node(s)", plan)
            self.assertIn("Create preview-svc@pam!freq-rw token", plan)
            self.assertIn("PVE nodes: 192.0.2.20, 192.0.2.21", plan)

            precedence_cases = (
                ({"check": True}, "_init_check"),
                ({"fix": True}, "_init_fix"),
                ({"reset": True}, "_init_reset"),
                ({"uninstall": True}, "_uninstall_dry_run"),
            )
            for overrides, handler_name in precedence_cases:
                with self.subTest(handler=handler_name), mock.patch.object(
                    init_cmd, "_apply_operator_vm_contract_args"
                ) as apply_contract, mock.patch.object(
                    init_cmd, handler_name, return_value=7
                ) as routed, mock.patch.object(
                    init_cmd,
                    "_init_dry_run",
                    side_effect=AssertionError("specific mode lost precedence"),
                ), mock.patch.object(
                    init_cmd.os, "geteuid", return_value=0
                ):
                    self.assertEqual(
                        init_cmd.cmd_init(
                            self._cfg(root),
                            None,
                            self._args(dry_run=True, **overrides),
                        ),
                        7,
                    )
                apply_contract.assert_called_once()
                routed.assert_called_once()

    def _case_interactive_consumes_injected_typed_catalog(self):
        injected_catalog = tuple(
            PhaseIdentity(identity.number, f"injected_{identity.key}", identity.title)
            for identity in INIT_PHASES
        )
        rc, _headers, _calls, started, catalog_calls, phase_results = self._run_interactive(
            injected_catalog=injected_catalog
        )
        self.assertEqual(rc, 0)
        self.assertEqual(catalog_calls, [mock.call()])
        self.assertEqual(len(started), len(injected_catalog))
        self.assertTrue(
            all(
                actual is expected
                for actual, expected in zip(started, injected_catalog, strict=True)
            )
        )
        self._assert_result_ledger(
            phase_results,
            len(injected_catalog),
            expected_identities=injected_catalog,
        )

    def _case_phase_header_renderer_is_preserved(self):
        from freq.modules import init_cmd

        with mock.patch.object(init_cmd.fmt, "blank") as blank, mock.patch.object(
            init_cmd.fmt, "divider"
        ) as divider:
            init_cmd._phase(1, 13, "Prerequisites")
        self.assertEqual(blank.call_count, 2)
        divider.assert_called_once_with("Phase 1/13: Prerequisites")

    def _case_typed_phase_start_returns_detached_input(self):
        from freq.modules import init_cmd

        identity = PhaseIdentity(1, "injected_prerequisites", "Prerequisites")
        context = {"nested": {"items": ["before"]}}
        with mock.patch.object(init_cmd, "_phase") as renderer:
            phase_input = init_cmd._begin_init_phase(
                identity,
                13,
                context,
                dry_run=True,
            )
        self.assertIsInstance(phase_input, PhaseInput)
        self.assertIs(phase_input.identity, identity)
        self.assertIsNot(phase_input.context, context)
        self.assertTrue(phase_input.dry_run)
        context["nested"]["items"].append("after")
        self.assertEqual(phase_input.context["nested"]["items"], ("before",))
        renderer.assert_called_once_with(1, 13, "Prerequisites")

    def _case_typed_phase_finish_records_exact_results(self):
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory(prefix="freq-init-result-") as root:
            cfg = self._cfg(root)
            exact_run_id = self._run_id("exact-run-id")
            context = {
                "_init_run_id": exact_run_id,
                "_init_mode": "interactive",
                "nested": {"items": ["before"]},
            }
            success_identity = PhaseIdentity(
                1,
                "injected_prerequisites",
                "Injected Prerequisites",
            )
            failure_identity = PhaseIdentity(
                2,
                "injected_configure",
                "Injected Configuration",
            )
            phase_input = PhaseInput(success_identity, context, dry_run=True)
            details = {"checks": ["ready"], "secret": "must-not-persist"}
            with mock.patch.object(init_cmd.logger, "info") as log:
                succeeded = init_cmd._finish_init_phase(
                    cfg,
                    context,
                    phase_input,
                    details=details,
                )
                failed_input = PhaseInput(failure_identity, context)
                failed = init_cmd._finish_init_phase(
                    cfg,
                    context,
                    failed_input,
                    error="configuration failed",
                )

            self.assertIsInstance(succeeded, PhaseResult)
            self.assertIs(succeeded.identity, phase_input.identity)
            self.assertIs(succeeded.status, PhaseStatus.SUCCEEDED)
            self.assertTrue(phase_input.dry_run)
            details["checks"].append("mutated")
            self.assertEqual(succeeded.details["checks"], ("ready",))

            self.assertIsInstance(failed, PhaseResult)
            self.assertIs(failed.identity, failed_input.identity)
            self.assertIs(failed.status, PhaseStatus.FAILED)
            self.assertEqual(failed.error, "configuration failed")
            self.assertEqual(context["_phase_results"], (succeeded, failed))
            self.assertEqual(log.call_count, 2)

            with open(init_cmd._init_status_path(cfg), encoding="utf-8") as status_file:
                persisted = json.load(status_file)
            self.assertEqual(persisted["schema"], "pve-freq-init-status-v1")
            self.assertEqual(persisted["run_id"], exact_run_id)
            self.assertEqual(persisted["mode"], "interactive")
            self.assertEqual(persisted["state"], "failed")
            self.assertEqual(persisted["current_phase"], 2)
            self.assertEqual(
                persisted["phase_results"],
                [
                    {
                        "number": 1,
                        "key": "injected_prerequisites",
                        "title": "Injected Prerequisites",
                        "status": "succeeded",
                        "error": None,
                    },
                    {
                        "number": 2,
                        "key": "injected_configure",
                        "title": "Injected Configuration",
                        "status": "failed",
                        "error": "configuration failed",
                    },
                ],
            )
            self.assertEqual(persisted["failed_checks"], ["configuration failed"])
            self.assertNotIn("must-not-persist", json.dumps(persisted, sort_keys=True))

            init_cmd._write_init_status(
                cfg,
                {
                    "initialized": True,
                    "schema": "pve-freq-init-status-v1",
                    "run_id": self._run_id("terminal-run-id"),
                    "mode": "headless",
                    "passes": 9,
                    "fails": 0,
                    "warns": 1,
                    "failed_checks": [],
                    "fleet_deploy_failures": 0,
                    "fleet_deploy_recovered_failed_ips": ["10.0.0.1"],
                    "fleet_deploy_unresolved_failed_ips": [],
                    "out_of_contract_vmids": [100],
                    "unexpected_out_of_contract_vmids": [101],
                    "reason": "freq init completed",
                    "credentials": {"password": "must-not-survive"},
                    "context": {"bootstrap_pass": "must-not-survive"},
                    "details": {"secret": "must-not-survive"},
                    "undeclared": "must-not-survive",
                },
            )
            verification = PhaseResult.succeeded(
                PhaseIdentity(12, "injected_verify", "Injected Verification")
            )
            init_cmd._persist_init_phase_results(
                cfg,
                (verification,),
                run_id=self._run_id("terminal-run-id"),
                mode="headless",
            )
            with open(init_cmd._init_status_path(cfg), encoding="utf-8") as status_file:
                terminal = json.load(status_file)
            self.assertIs(terminal["initialized"], True)
            self.assertEqual(terminal["state"], "succeeded")
            self.assertEqual(terminal["passes"], 9)
            self.assertEqual(terminal["fails"], 0)
            self.assertEqual(terminal["warns"], 1)
            self.assertEqual(terminal["fleet_deploy_recovered_failed_ips"], ["10.0.0.1"])
            self.assertEqual(terminal["out_of_contract_vmids"], [100])
            self.assertEqual(terminal["unexpected_out_of_contract_vmids"], [101])
            self.assertEqual(terminal["reason"], "freq init completed")
            self.assertEqual(
                set(terminal),
                {
                    "checked_at",
                    "current_phase",
                    "current_phase_key",
                    "failed_checks",
                    "fails",
                    "fleet_deploy_failures",
                    "fleet_deploy_recovered_failed_ips",
                    "fleet_deploy_unresolved_failed_ips",
                    "initialized",
                    "mode",
                    "out_of_contract_vmids",
                    "passes",
                    "phase_results",
                    "reason",
                    "run_id",
                    "schema",
                    "state",
                    "unexpected_out_of_contract_vmids",
                    "warns",
                },
            )

            init_cmd._write_init_status(
                cfg,
                {
                    "initialized": True,
                    "run_id": self._run_id("stale-run-id"),
                    "reason": "stale success",
                },
            )
            init_cmd._persist_init_phase_results(
                cfg,
                (PhaseResult.succeeded(success_identity),),
                run_id=self._run_id("fresh-run-id"),
                mode="interactive",
            )
            with open(init_cmd._init_status_path(cfg), encoding="utf-8") as status_file:
                fresh = json.load(status_file)
            self.assertIs(fresh["initialized"], False)
            self.assertEqual(fresh["state"], "running")
            self.assertEqual(fresh["run_id"], self._run_id("fresh-run-id"))
            self.assertEqual(fresh["reason"], "")

            with open(init_cmd._init_status_path(cfg), "rb") as status_file:
                accepted_bytes = status_file.read()
            invalid_run_ids = (
                ("a" * 31, ValueError),
                ("A" * 32, ValueError),
                ("g" * 32, ValueError),
                (f" {'a' * 32} ", ValueError),
                ("", ValueError),
                (None, TypeError),
            )
            for invalid_run_id, expected_error in invalid_run_ids:
                with self.subTest(run_id=invalid_run_id), self.assertRaises(
                    expected_error
                ):
                    init_cmd._persist_init_phase_results(
                        cfg,
                        (PhaseResult.succeeded(success_identity),),
                        run_id=invalid_run_id,
                        mode="interactive",
                    )
                with open(init_cmd._init_status_path(cfg), "rb") as status_file:
                    self.assertEqual(status_file.read(), accepted_bytes)

    def _case_typed_phase_persistence_replay_is_exact_replacement(self):
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory(prefix="freq-init-replay-") as root:
            cfg = self._cfg(root)
            first = PhaseResult.succeeded(
                PhaseIdentity(1, "injected_prerequisites", "Injected Prerequisites")
            )
            second = PhaseResult.succeeded(
                PhaseIdentity(2, "injected_configure", "Injected Configuration")
            )
            first_tuple = (first,)
            expanded_tuple = (first, second)
            expected_keys = {
                "checked_at",
                "current_phase",
                "current_phase_key",
                "failed_checks",
                "initialized",
                "mode",
                "phase_results",
                "reason",
                "run_id",
                "schema",
                "state",
            }

            def persist_and_load(results):
                init_cmd._persist_init_phase_results(
                    cfg,
                    results,
                    run_id=self._run_id("replay-run-id"),
                    mode="headless",
                )
                with open(init_cmd._init_status_path(cfg), encoding="utf-8") as status_file:
                    return json.load(status_file)

            initial = persist_and_load(first_tuple)
            replayed = persist_and_load(first_tuple)
            expanded = persist_and_load(expanded_tuple)

            for payload in (initial, replayed, expanded):
                self.assertEqual(payload["run_id"], self._run_id("replay-run-id"))
                self.assertEqual(payload["mode"], "headless")
                self.assertEqual(set(payload), expected_keys)
            self.assertEqual(initial["current_phase"], 1)
            self.assertEqual(replayed["current_phase"], 1)
            self.assertEqual(replayed["phase_results"], initial["phase_results"])
            self.assertEqual(expanded["current_phase"], 2)
            self.assertEqual(expanded["current_phase_key"], "injected_configure")
            self.assertEqual(
                expanded["phase_results"],
                [
                    {
                        "number": 1,
                        "key": "injected_prerequisites",
                        "title": "Injected Prerequisites",
                        "status": "succeeded",
                        "error": None,
                    },
                    {
                        "number": 2,
                        "key": "injected_configure",
                        "title": "Injected Configuration",
                        "status": "succeeded",
                        "error": None,
                    },
                ],
            )
            self.assertEqual(
                [result["number"] for result in expanded["phase_results"]],
                [1, 2],
            )

    def _case_fresh_restart_resets_durable_progress(self):
        from freq.modules import init_cmd

        with mock.patch.object(
            init_cmd,
            "_start_init_run",
            wraps=init_cmd._start_init_run,
        ) as start_run:
            self._run_interactive()
            self._run_headless()
        self.assertEqual(
            [call.kwargs["mode"] for call in start_run.call_args_list],
            ["interactive", "headless"],
        )

        with tempfile.TemporaryDirectory(prefix="freq-init-restart-") as root:
            cfg = self._cfg(root)
            prior = PhaseResult.succeeded(
                PhaseIdentity(1, "prior_prerequisites", "Prior Prerequisites")
            )
            init_cmd._persist_init_phase_results(
                cfg,
                (prior,),
                run_id=self._run_id("prior-run-id"),
                mode="interactive",
            )
            status_path = init_cmd._init_status_path(cfg)
            self.assertTrue(os.path.isfile(status_path))
            marker_path = os.path.join(cfg.conf_dir, ".initialized")
            with open(marker_path, "wb") as marker_file:
                marker_file.write(b"prior initialized marker\n")
            with self.assertRaisesRegex(ValueError, "interactive or headless"):
                init_cmd._start_init_run(cfg, mode="web")
            self.assertTrue(os.path.isfile(status_path))
            init_cmd._prepare_init_control_dir(cfg)

            with mock.patch.object(
                init_cmd.secrets,
                "token_hex",
                side_effect=(
                    self._run_id("fresh-interactive-id"),
                    self._run_id("fresh-headless-id"),
                ),
            ):
                interactive = init_cmd._start_init_run(cfg, mode="interactive")
                self.assertTrue(os.path.exists(status_path))
                with mock.patch.object(init_cmd, "INIT_MARKER", marker_path):
                    init_cmd._cross_init_point_of_no_return(
                        cfg, interactive, clear_runtime_truth=False
                    )
                self.assertFalse(os.path.exists(status_path))
                self.assertFalse(os.path.exists(marker_path))
                init_cmd._persist_init_phase_results(
                    cfg,
                    (prior,),
                    run_id=interactive["_init_run_id"],
                    mode=interactive["_init_mode"],
                )
                headless = init_cmd._start_init_run(cfg, mode="headless")
                self.assertTrue(os.path.exists(status_path))
                with mock.patch.object(
                    init_cmd, "_clear_generated_runtime_truth_state"
                ) as clear_runtime_truth:
                    init_cmd._cross_init_point_of_no_return(
                        cfg, headless, clear_runtime_truth=True
                    )
                self.assertFalse(os.path.exists(status_path))
                clear_runtime_truth.assert_called_once_with(cfg)

            resumed = {
                "_init_run_id": self._run_id("resumed-run-id"),
                "_init_mode": "interactive",
                "_phase_results": (PhaseResult.succeeded(INIT_PHASES[0]),),
            }
            with mock.patch.object(init_cmd, "_clear_init_status") as clear_status:
                init_cmd._cross_init_point_of_no_return(
                    cfg, resumed, clear_runtime_truth=False
                )
            clear_status.assert_not_called()

            self.assertEqual(
                interactive,
                {
                    "_init_run_id": self._run_id("fresh-interactive-id"),
                    "_init_mode": "interactive",
                },
            )
            self.assertEqual(
                headless,
                {
                    "_init_run_id": self._run_id("fresh-headless-id"),
                    "_init_mode": "headless",
                },
            )
            self.assertNotEqual(interactive["_init_run_id"], headless["_init_run_id"])

    def _case_runtime_prepares_private_control_before_execution(self):
        from freq.modules import init_cmd

        with mock.patch.object(
            init_cmd,
            "_prepare_init_control_dir",
            wraps=init_cmd._prepare_init_control_dir,
        ) as prepare_control:
            interactive = self._run_interactive()
            headless = self._run_headless()
        self.assertEqual(interactive[0], 0)
        self.assertEqual(headless[0], 0)
        self.assertEqual(prepare_control.call_count, 2)

        for mode, runner in (
            ("interactive", self._run_interactive),
            ("headless", self._run_headless),
        ):
            preparation_error = OSError(f"{mode} control preparation failed")
            with self.subTest(mode=mode), mock.patch.object(
                init_cmd,
                "_prepare_init_control_dir",
                side_effect=preparation_error,
            ) as prepare_control, mock.patch.object(
                init_cmd,
                "_cross_init_point_of_no_return",
                wraps=init_cmd._cross_init_point_of_no_return,
            ) as cross_boundary:
                with self.assertRaises(OSError) as raised:
                    runner()
            self.assertIs(raised.exception, preparation_error)
            prepare_control.assert_called_once()
            cross_boundary.assert_not_called()

    def _case_private_point_of_no_return_claim_precedes_mutation(self):
        from freq.core.types import _InitControlState
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory(prefix="freq-init-ponr-claim-") as root:
            cfg = self._cfg(root)
            os.makedirs(cfg.conf_dir)
            status_path = init_cmd._init_status_path(cfg)
            marker_path = os.path.join(cfg.conf_dir, ".initialized")
            status_bytes = b'{"state":"accepted-prior"}\n'
            marker_bytes = b"accepted prior marker\n"
            context = {
                "_init_run_id": self._run_id("ponr-claim-run"),
                "_init_mode": "interactive",
            }

            def restore_prior_state():
                with open(status_path, "wb") as status_file:
                    status_file.write(status_bytes)
                with open(marker_path, "wb") as marker_file:
                    marker_file.write(marker_bytes)

            def assert_prior_state():
                with open(status_path, "rb") as status_file:
                    self.assertEqual(status_file.read(), status_bytes)
                with open(marker_path, "rb") as marker_file:
                    self.assertEqual(marker_file.read(), marker_bytes)

            restore_prior_state()
            with mock.patch.object(
                init_cmd,
                "INIT_MARKER",
                marker_path,
            ), mock.patch.object(
                init_cmd,
                "_claim_init_point_of_no_return",
                return_value=_InitControlState.CANCEL_REQUESTED,
            ) as claim, mock.patch.object(
                init_cmd,
                "_clear_generated_runtime_truth_state",
            ) as clear_runtime_truth:
                with self.assertRaisesRegex(
                    InterruptedError,
                    "cancellation won",
                ):
                    init_cmd._cross_init_point_of_no_return(
                        cfg,
                        context,
                        clear_runtime_truth=True,
                    )
            claim.assert_called_once_with(cfg, context["_init_run_id"])
            clear_runtime_truth.assert_not_called()
            assert_prior_state()

            for outcome in (OSError("control claim failed"), _InitControlState.PRE_PONR):
                restore_prior_state()
                expected_error = OSError if isinstance(outcome, OSError) else RuntimeError
                with self.subTest(outcome=outcome), mock.patch.object(
                    init_cmd,
                    "INIT_MARKER",
                    marker_path,
                ), mock.patch.object(
                    init_cmd,
                    "_claim_init_point_of_no_return",
                    side_effect=outcome if isinstance(outcome, OSError) else None,
                    return_value=outcome,
                ) as claim, mock.patch.object(
                    init_cmd,
                    "_clear_generated_runtime_truth_state",
                ) as clear_runtime_truth:
                    with self.assertRaises(expected_error) as raised:
                        init_cmd._cross_init_point_of_no_return(
                            cfg,
                            context,
                            clear_runtime_truth=True,
                        )
                if isinstance(outcome, OSError):
                    self.assertIs(raised.exception, outcome)
                claim.assert_called_once_with(cfg, context["_init_run_id"])
                clear_runtime_truth.assert_not_called()
                assert_prior_state()

            restore_prior_state()

            def accepted_claim(_cfg, _run_id):
                assert_prior_state()
                return _InitControlState.POINT_OF_NO_RETURN

            def clear_after_prior_state(_cfg):
                self.assertFalse(os.path.exists(status_path))
                self.assertFalse(os.path.exists(marker_path))

            with mock.patch.object(
                init_cmd,
                "INIT_MARKER",
                marker_path,
            ), mock.patch.object(
                init_cmd,
                "_claim_init_point_of_no_return",
                side_effect=accepted_claim,
            ) as claim, mock.patch.object(
                init_cmd,
                "_clear_generated_runtime_truth_state",
                side_effect=clear_after_prior_state,
            ) as clear_runtime_truth:
                self.assertIsNone(
                    init_cmd._cross_init_point_of_no_return(
                        cfg,
                        context,
                        clear_runtime_truth=True,
                    )
                )
            claim.assert_called_once_with(cfg, context["_init_run_id"])
            clear_runtime_truth.assert_called_once_with(cfg)
            self.assertFalse(os.path.exists(status_path))
            self.assertFalse(os.path.exists(marker_path))

    def _case_web_child_cancel_signal_is_pre_ponr_only(self):
        from freq.core import setup_state
        from freq.core.types import _InitControlState
        from freq.modules import init_cmd

        previous_handler = object()

        with tempfile.TemporaryDirectory(prefix="freq-init-web-cancel-before-") as root:
            cfg = self._cfg(root)
            init_cmd._prepare_init_control_dir(cfg)
            context = {
                "_init_run_id": self._run_id("web-cancel-before-ponr"),
                "_init_mode": "headless",
            }
            installed = []

            def install_handler(signum, handler):
                self.assertEqual(signum, init_cmd.signal.SIGINT)
                installed.append(handler)

            marker_path = os.path.join(cfg.conf_dir, ".initialized")
            status_path = init_cmd._init_status_path(cfg)
            os.makedirs(cfg.conf_dir)
            marker_bytes = b"accepted prior marker\n"
            status_bytes = b'{"state":"accepted-prior"}\n'
            with open(marker_path, "wb") as marker_file:
                marker_file.write(marker_bytes)
            with open(status_path, "wb") as status_file:
                status_file.write(status_bytes)

            def cancelled_child(child_cfg, _args):
                self.assertIs(child_cfg, cfg)
                installed[0](init_cmd.signal.SIGINT, None)
                init_cmd._cross_init_point_of_no_return(
                    cfg,
                    context,
                    clear_runtime_truth=False,
                )

            cleanup_events = []
            real_fsync = setup_state.os.fsync
            real_unlink = setup_state.os.unlink

            def tracked_fsync(fd):
                cleanup_events.append(("fsync", fd))
                return real_fsync(fd)

            def tracked_unlink(path, *, dir_fd=None):
                cleanup_events.append(("unlink", path, dir_fd))
                return real_unlink(path, dir_fd=dir_fd)

            def tracked_warning(message):
                cleanup_events.append(("warning", message))

            with mock.patch.dict(os.environ, {"FREQ_WEB_INIT": "1"}), mock.patch.object(
                init_cmd.signal,
                "getsignal",
                return_value=previous_handler,
            ), mock.patch.object(
                init_cmd.signal,
                "signal",
                side_effect=install_handler,
            ) as set_signal, mock.patch.object(
                init_cmd,
                "_init_headless",
                side_effect=cancelled_child,
            ), mock.patch.object(
                init_cmd,
                "_request_init_cancel",
                wraps=init_cmd._request_init_cancel,
            ) as request_cancel, mock.patch.object(
                init_cmd,
                "_claim_init_point_of_no_return",
                wraps=init_cmd._claim_init_point_of_no_return,
            ) as claim_ponr, mock.patch.object(
                init_cmd,
                "_rollback_cancelled_init_control",
                wraps=init_cmd._rollback_cancelled_init_control,
            ) as rollback_control, mock.patch.object(
                setup_state.os,
                "fsync",
                side_effect=tracked_fsync,
            ), mock.patch.object(
                setup_state.os,
                "unlink",
                side_effect=tracked_unlink,
            ), mock.patch.object(
                init_cmd.fmt,
                "step_warn",
                side_effect=tracked_warning,
            ) as warning:
                self.assertEqual(
                    init_cmd._run_web_init_with_cancel_signal(cfg, object()),
                    130,
                )

            request_cancel.assert_called_once_with(cfg, context["_init_run_id"])
            claim_ponr.assert_not_called()
            rollback_control.assert_called_once_with(cfg, context["_init_run_id"])
            warning.assert_called_once_with(
                "Initialization cancelled before point of no return; prior state preserved"
            )
            unlink_index = next(
                index
                for index, event in enumerate(cleanup_events)
                if event[0] == "unlink"
            )
            unlinked = cleanup_events[unlink_index]
            self.assertEqual(
                cleanup_events[unlink_index : unlink_index + 3],
                [
                    unlinked,
                    ("fsync", unlinked[2]),
                    (
                        "warning",
                        "Initialization cancelled before point of no return; prior state preserved",
                    ),
                ],
            )
            self.assertEqual(set_signal.call_count, 2)
            self.assertIs(installed[-1], previous_handler)
            self.assertFalse(init_cmd._WEB_INIT_CANCEL_SIGNALLED.is_set())
            self.assertFalse(
                os.path.exists(setup_state._init_control_path(cfg, context["_init_run_id"]))
            )
            with open(marker_path, "rb") as marker_file:
                self.assertEqual(marker_file.read(), marker_bytes)
            with open(status_path, "rb") as status_file:
                self.assertEqual(status_file.read(), status_bytes)

        with tempfile.TemporaryDirectory(prefix="freq-init-web-cancel-rollback-") as root:
            cfg = self._cfg(root)
            cfg.pve_nodes = ["192.0.2.10"]
            os.makedirs(cfg.conf_dir)
            marker_path = os.path.join(cfg.conf_dir, ".initialized")
            status_path = init_cmd._init_status_path(cfg)
            marker_bytes = b"accepted rollback marker\n"
            status_bytes = b'{"schema":"accepted-prior","state":"failed"}\n'
            with open(marker_path, "wb") as marker_file:
                marker_file.write(marker_bytes)
            with open(status_path, "wb") as status_file:
                status_file.write(status_bytes)

            bootstrap_key = os.path.join(root, "bootstrap-key")
            password_file = os.path.join(root, "service-password")
            dashboard_password_file = os.path.join(root, "dashboard-password")
            for path, value in (
                (bootstrap_key, "key"),
                (password_file, "service-password"),
                (dashboard_password_file, "dashboard-password"),
            ):
                with open(path, "w", encoding="utf-8") as secret_file:
                    secret_file.write(value)
            args = self._args(
                headless=True,
                bootstrap_key=bootstrap_key,
                bootstrap_user="root",
                bootstrap_password_file=None,
                password_file=password_file,
                dashboard_user="operator",
                dashboard_password_file=dashboard_password_file,
                device_credentials=None,
                device_password_file=None,
                device_user="root",
                service_account="preview-svc",
                hosts_file=None,
                owned_vmids="100-102",
            )
            before_cfg_mapping = vars(cfg)
            before_cfg = copy.deepcopy(before_cfg_mapping)
            before_mutable_cfg_members = {
                name: value
                for name, value in before_cfg_mapping.items()
                if isinstance(value, (bytearray, dict, list, set))
            }
            before_init_marker = os.path.join(root, "prior-global-init-marker")
            init_cmd.INIT_MARKER = before_init_marker
            real_begin = init_cmd._begin_init_phase
            real_control_rollback = init_cmd._rollback_cancelled_init_control
            real_topology_rollback = init_cmd._rollback_init_control_topology
            real_memory_rollback = init_cmd._rollback_web_init_pre_ponr_state
            rollback_events = []
            rollback_run_ids = []

            def cancel_at_phase_one(*call_args, **call_kwargs):
                phase_input = real_begin(*call_args, **call_kwargs)
                init_cmd._record_web_init_cancel_signal(init_cmd.signal.SIGINT, None)
                return phase_input

            def record_control_rollback(rollback_cfg, run_id):
                rollback_run_ids.append(run_id)
                rollback_events.append(("control_begin", run_id))
                result = real_control_rollback(rollback_cfg, run_id)
                rollback_events.append(("control_complete", run_id))
                return result

            def record_memory_rollback(rollback_cfg, state):
                self.assertEqual(len(rollback_run_ids), 1)
                run_id = rollback_run_ids[0]
                self.assertFalse(
                    os.path.lexists(setup_state._init_control_path(rollback_cfg, run_id))
                )
                self.assertFalse(
                    os.path.lexists(os.path.join(rollback_cfg.data_dir, "init-control"))
                )
                self.assertFalse(os.path.lexists(rollback_cfg.data_dir))
                rollback_events.append(("memory_begin", run_id))
                result = real_memory_rollback(rollback_cfg, state)
                rollback_events.append(("memory_complete", run_id))
                return result

            def record_topology_rollback(rollback_cfg, topology):
                self.assertEqual(len(rollback_run_ids), 1)
                run_id = rollback_run_ids[0]
                rollback_events.append(("topology_begin", run_id))
                result = real_topology_rollback(rollback_cfg, topology)
                rollback_events.append(("topology_complete", run_id))
                return result

            def assert_restored_before_warning(message):
                rollback_events.append(("warning", message))
                self.assertEqual(
                    message,
                    "Initialization cancelled before point of no return; prior state preserved",
                )
                self.assertIs(vars(cfg), before_cfg_mapping)
                self.assertEqual(vars(cfg), before_cfg)
                for name, value in before_mutable_cfg_members.items():
                    self.assertIs(getattr(cfg, name), value)
                self.assertIs(init_cmd.INIT_MARKER, before_init_marker)
                with open(marker_path, "rb") as marker_file:
                    self.assertEqual(marker_file.read(), marker_bytes)
                with open(status_path, "rb") as status_file:
                    self.assertEqual(status_file.read(), status_bytes)

            with mock.patch.dict(os.environ, {"FREQ_WEB_INIT": "1"}), mock.patch.object(
                init_cmd.os, "geteuid", return_value=0
            ), mock.patch.object(
                init_cmd, "_load_device_credentials", return_value={}
            ), mock.patch.object(
                init_cmd, "_validate_device_scoped_service_password", return_value=True
            ), mock.patch.object(
                init_cmd, "_validate_truenas_deployment_credentials", return_value=True
            ), mock.patch.object(
                init_cmd, "_validate_device_credential_scopes", return_value=True
            ), mock.patch.object(
                init_cmd, "_validate_username", return_value=True
            ), mock.patch.object(
                init_cmd, "_validate_service_account_choice", return_value=True
            ), mock.patch.object(
                init_cmd, "_headless_phase2_inputs_match_current_config", return_value=False
            ), mock.patch.object(
                init_cmd, "_begin_init_phase", side_effect=cancel_at_phase_one
            ), mock.patch.object(
                init_cmd,
                "_rollback_cancelled_init_control",
                side_effect=record_control_rollback,
            ), mock.patch.object(
                init_cmd,
                "_rollback_init_control_topology",
                side_effect=record_topology_rollback,
            ), mock.patch.object(
                init_cmd,
                "_rollback_web_init_pre_ponr_state",
                side_effect=record_memory_rollback,
            ), mock.patch.object(
                init_cmd, "_phase_welcome"
            ) as welcome, mock.patch.object(
                init_cmd.fmt, "step_warn", side_effect=assert_restored_before_warning
            ) as warning:
                self.assertEqual(init_cmd.cmd_init(cfg, None, args), 130)

            welcome.assert_not_called()
            warning.assert_called_once()
            self.assertEqual(len(rollback_run_ids), 1)
            run_id = rollback_run_ids[0]
            self.assertEqual(
                rollback_events,
                [
                    ("control_begin", run_id),
                    ("control_complete", run_id),
                    ("topology_begin", run_id),
                    ("topology_complete", run_id),
                    ("memory_begin", run_id),
                    ("memory_complete", run_id),
                    (
                        "warning",
                        "Initialization cancelled before point of no return; prior state preserved",
                    ),
                ],
            )
            self.assertIs(vars(cfg), before_cfg_mapping)
            self.assertEqual(vars(cfg), before_cfg)
            for name, value in before_mutable_cfg_members.items():
                self.assertIs(getattr(cfg, name), value)
            self.assertIs(init_cmd.INIT_MARKER, before_init_marker)

        with tempfile.TemporaryDirectory(prefix="freq-init-web-cancel-after-") as root:
            cfg = self._cfg(root)
            init_cmd._prepare_init_control_dir(cfg)
            context = {
                "_init_run_id": self._run_id("web-cancel-after-ponr"),
                "_init_mode": "headless",
            }
            installed = []

            def install_handler(_signum, handler):
                installed.append(handler)

            def running_child(_cfg, _args):
                init_cmd._cross_init_point_of_no_return(
                    cfg,
                    context,
                    clear_runtime_truth=False,
                )
                installed[0](init_cmd.signal.SIGINT, None)
                return "continued-after-ponr"

            with mock.patch.dict(os.environ, {"FREQ_WEB_INIT": "1"}), mock.patch.object(
                init_cmd.signal,
                "getsignal",
                return_value=previous_handler,
            ), mock.patch.object(
                init_cmd.signal,
                "signal",
                side_effect=install_handler,
            ), mock.patch.object(
                init_cmd,
                "_init_headless",
                side_effect=running_child,
            ):
                self.assertEqual(
                    init_cmd._run_web_init_with_cancel_signal(cfg, object()),
                    "continued-after-ponr",
                )

            self.assertIs(installed[-1], previous_handler)
            self.assertFalse(init_cmd._WEB_INIT_CANCEL_SIGNALLED.is_set())
            self.assertIs(
                setup_state._request_init_cancel(cfg, context["_init_run_id"]),
                _InitControlState.POINT_OF_NO_RETURN,
            )
            with self.assertRaisesRegex(ValueError, "requires cancelled pre-PONR state"):
                setup_state._rollback_cancelled_init_control(
                    cfg, context["_init_run_id"]
                )
            self.assertTrue(
                os.path.isfile(setup_state._init_control_path(cfg, context["_init_run_id"]))
            )

        with tempfile.TemporaryDirectory(prefix="freq-init-cancel-corrupt-") as root:
            cfg = self._cfg(root)
            setup_state._prepare_init_control_dir(cfg)
            run_id = self._run_id("corrupt-cancel-control")
            self.assertIs(
                setup_state._request_init_cancel(cfg, run_id),
                _InitControlState.CANCEL_REQUESTED,
            )
            control_path = setup_state._init_control_path(cfg, run_id)
            with open(control_path, "wb") as control_file:
                control_file.write(b"corrupt\n")
            with self.assertRaisesRegex(ValueError, "requires cancelled pre-PONR state"):
                setup_state._rollback_cancelled_init_control(cfg, run_id)
            with open(control_path, "rb") as control_file:
                self.assertEqual(control_file.read(), b"corrupt\n")

        with tempfile.TemporaryDirectory(prefix="freq-init-cancel-symlink-") as root:
            cfg = self._cfg(root)
            setup_state._prepare_init_control_dir(cfg)
            run_id = self._run_id("symlink-cancel-control")
            control_path = setup_state._init_control_path(cfg, run_id)
            outside_path = os.path.join(root, "outside-control")
            with open(outside_path, "wb") as outside_file:
                outside_file.write(b"cancel_requested\n")
            os.symlink(outside_path, control_path)
            with self.assertRaises(OSError):
                setup_state._rollback_cancelled_init_control(cfg, run_id)
            self.assertTrue(os.path.islink(control_path))
            with open(outside_path, "rb") as outside_file:
                self.assertEqual(outside_file.read(), b"cancel_requested\n")

        with tempfile.TemporaryDirectory(prefix="freq-init-cancel-multilink-") as root:
            cfg = self._cfg(root)
            setup_state._prepare_init_control_dir(cfg)
            run_id = self._run_id("multilink-cancel-control")
            self.assertIs(
                setup_state._request_init_cancel(cfg, run_id),
                _InitControlState.CANCEL_REQUESTED,
            )
            control_path = setup_state._init_control_path(cfg, run_id)
            linked_path = os.path.join(os.path.dirname(control_path), "linked-control.state")
            os.link(control_path, linked_path)
            with self.assertRaisesRegex(OSError, "private regular file"):
                setup_state._rollback_cancelled_init_control(cfg, run_id)
            for retained_path in (control_path, linked_path):
                with open(retained_path, "rb") as retained_file:
                    self.assertEqual(retained_file.read(), b"cancel_requested\n")

        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(
            init_cmd.signal,
            "signal",
        ) as set_signal, mock.patch.object(
            init_cmd,
            "_init_headless",
            return_value="ordinary-headless",
        ):
            os.environ.pop("FREQ_WEB_INIT", None)
            self.assertEqual(
                init_cmd._run_web_init_with_cancel_signal(object(), object()),
                "ordinary-headless",
            )
        set_signal.assert_not_called()

    @staticmethod
    def _web_pre_ponr_snapshot(cfg, marker):
        mapping = vars(cfg)
        return (
            mapping,
            copy.deepcopy(mapping),
            {
                name: value
                for name, value in mapping.items()
                if isinstance(value, (bytearray, dict, list, set))
            },
            marker,
        )

    def _assert_web_pre_ponr_restored(self, cfg, before):
        from freq.modules import init_cmd

        mapping, values, mutable_members, marker = before
        self.assertIs(vars(cfg), mapping)
        self.assertEqual(vars(cfg), values)
        for name, value in mutable_members.items():
            self.assertIs(getattr(cfg, name), value)
        self.assertIs(init_cmd.INIT_MARKER, marker)

    @staticmethod
    def _seed_web_pre_ponr_mutables(cfg):
        cfg.pve_nodes = ["192.0.2.10"]
        cfg.rollback_mapping = {"accepted": ["original"]}
        cfg.rollback_set = {"accepted"}
        cfg.rollback_bytes = bytearray(b"accepted")

    @staticmethod
    def _mutate_web_pre_ponr_members(cfg):
        cfg.pve_nodes.append("198.51.100.20")
        cfg.rollback_mapping["accepted"].append("mutated")
        cfg.rollback_mapping["transient"] = {"nested": ["value"]}
        cfg.rollback_set.add("mutated")
        cfg.rollback_bytes.extend(b"-mutated")

    def _case_web_pre_ponr_validation_return_restores_mutables(self):
        from freq.modules import init_cmd

        args = self._args(headless=True, owned_vmids="100-102")
        with tempfile.TemporaryDirectory(prefix="freq-init-web-validation-rollback-") as root:
            cfg = self._cfg(root)
            self._seed_web_pre_ponr_mutables(cfg)
            init_cmd.INIT_MARKER = os.path.join(root, "prior-validation-marker")
            before = self._web_pre_ponr_snapshot(cfg, init_cmd.INIT_MARKER)
            real_topology_rollback = init_cmd._rollback_init_control_topology
            real_rollback = init_cmd._rollback_web_init_pre_ponr_state
            rollback_events = []

            def restore_topology(rollback_cfg, topology):
                rollback_events.append("topology_begin")
                result = real_topology_rollback(rollback_cfg, topology)
                rollback_events.append("topology_complete")
                self.assertFalse(os.path.lexists(rollback_cfg.data_dir))
                return result

            def restore_before_return(rollback_cfg, state):
                self.assertEqual(
                    rollback_events,
                    ["topology_begin", "topology_complete"],
                )
                rollback_events.append("memory_begin")
                result = real_rollback(rollback_cfg, state)
                rollback_events.append("memory_complete")
                self._assert_web_pre_ponr_restored(cfg, before)
                return result

            def mutate_before_validation_return():
                init_cmd._prepare_init_control_dir(cfg)
                self._mutate_web_pre_ponr_members(cfg)
                return 1

            with mock.patch.dict(os.environ, {"FREQ_WEB_INIT": "1"}), mock.patch.object(
                init_cmd.os, "geteuid", side_effect=mutate_before_validation_return
            ), mock.patch.object(
                init_cmd,
                "_rollback_init_control_topology",
                side_effect=restore_topology,
            ), mock.patch.object(
                init_cmd,
                "_rollback_web_init_pre_ponr_state",
                side_effect=restore_before_return,
            ) as rollback:
                self.assertEqual(init_cmd.cmd_init(cfg, None, args), 1)

            rollback.assert_called_once()
            self.assertEqual(
                rollback_events,
                [
                    "topology_begin",
                    "topology_complete",
                    "memory_begin",
                    "memory_complete",
                ],
            )
            self._assert_web_pre_ponr_restored(cfg, before)
            self.assertFalse(os.path.lexists(cfg.data_dir))

    def _case_web_pre_ponr_exception_restores_mutables_and_reraises(self):
        from freq.modules import init_cmd

        args = self._args(headless=True, owned_vmids="100-102")
        with tempfile.TemporaryDirectory(prefix="freq-init-web-exception-rollback-") as root:
            cfg = self._cfg(root)
            self._seed_web_pre_ponr_mutables(cfg)
            init_cmd.INIT_MARKER = os.path.join(root, "prior-exception-marker")
            before = self._web_pre_ponr_snapshot(cfg, init_cmd.INIT_MARKER)
            ordinary_failure = RuntimeError("pre-PONR validation failed")
            real_topology_rollback = init_cmd._rollback_init_control_topology
            real_memory_rollback = init_cmd._rollback_web_init_pre_ponr_state
            rollback_events = []

            def restore_topology(rollback_cfg, topology):
                rollback_events.append("topology_begin")
                result = real_topology_rollback(rollback_cfg, topology)
                rollback_events.append("topology_complete")
                self.assertFalse(os.path.lexists(rollback_cfg.data_dir))
                return result

            def restore_memory(rollback_cfg, state):
                self.assertEqual(
                    rollback_events,
                    ["topology_begin", "topology_complete"],
                )
                rollback_events.append("memory_begin")
                result = real_memory_rollback(rollback_cfg, state)
                rollback_events.append("memory_complete")
                return result

            def mutate_before_exception(_cfg, _args):
                init_cmd._prepare_init_control_dir(cfg)
                self._mutate_web_pre_ponr_members(cfg)
                raise ordinary_failure

            with mock.patch.dict(os.environ, {"FREQ_WEB_INIT": "1"}), mock.patch.object(
                init_cmd, "_init_headless", side_effect=mutate_before_exception
            ), mock.patch.object(
                init_cmd,
                "_rollback_init_control_topology",
                side_effect=restore_topology,
            ), mock.patch.object(
                init_cmd,
                "_rollback_web_init_pre_ponr_state",
                side_effect=restore_memory,
            ) as rollback:
                with self.assertRaisesRegex(
                    RuntimeError, "pre-PONR validation failed"
                ) as raised:
                    init_cmd.cmd_init(cfg, None, args)

            rollback.assert_called_once()
            self.assertEqual(
                rollback_events,
                [
                    "topology_begin",
                    "topology_complete",
                    "memory_begin",
                    "memory_complete",
                ],
            )
            self.assertIs(raised.exception, ordinary_failure)
            self._assert_web_pre_ponr_restored(cfg, before)
            self.assertFalse(os.path.lexists(cfg.data_dir))

    def _case_web_post_ponr_failure_does_not_restore_memory(self):
        from freq.modules import init_cmd

        args = self._args(headless=True, owned_vmids="100-102")
        with tempfile.TemporaryDirectory(prefix="freq-init-web-post-ponr-failure-") as root:
            cfg = self._cfg(root)
            init_cmd._prepare_init_control_dir(cfg)
            pre_ponr_state = init_cmd._capture_web_init_pre_ponr_state(cfg)
            context = {
                "_init_run_id": self._run_id("web-post-ponr-failure"),
                "_init_mode": "headless",
            }

            def fail_after_ponr(_cfg, _args):
                init_cmd._cross_init_point_of_no_return(
                    cfg,
                    context,
                    clear_runtime_truth=False,
                )
                cfg.ssh_service_account = "post-ponr-state"
                return 1

            with mock.patch.dict(os.environ, {"FREQ_WEB_INIT": "1"}), mock.patch.object(
                init_cmd, "_init_headless", side_effect=fail_after_ponr
            ), mock.patch.object(
                init_cmd, "_rollback_web_init_pre_ponr_state"
            ) as rollback:
                self.assertEqual(
                    init_cmd._run_web_init_with_cancel_signal(
                        cfg,
                        args,
                        pre_ponr_state=pre_ponr_state,
                    ),
                    1,
                )

            rollback.assert_not_called()
            self.assertEqual(cfg.ssh_service_account, "post-ponr-state")
            self.assertFalse(init_cmd._WEB_INIT_PONR_ENTERED.is_set())

    def _case_web_cancel_topology_failure_never_claims_preservation(self):
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory(prefix="freq-init-web-topology-failure-") as root:
            cfg = self._cfg(root)
            state = init_cmd._capture_web_init_pre_ponr_state(cfg)
            run_id = self._run_id("web-topology-cleanup-failure")
            topology_error = OSError("init control topology is not empty")
            with mock.patch.dict(os.environ, {"FREQ_WEB_INIT": "1"}), mock.patch.object(
                init_cmd,
                "_init_headless",
                side_effect=init_cmd._InitCancelledBeforePointOfNoReturn(run_id),
            ), mock.patch.object(
                init_cmd, "_rollback_cancelled_init_control"
            ) as rollback_control, mock.patch.object(
                init_cmd,
                "_rollback_init_control_topology",
                side_effect=topology_error,
            ) as rollback_topology, mock.patch.object(
                init_cmd, "_rollback_web_init_pre_ponr_state"
            ) as rollback_memory, mock.patch.object(
                init_cmd.fmt, "step_warn"
            ) as warning:
                with self.assertRaises(OSError) as raised:
                    init_cmd._run_web_init_with_cancel_signal(
                        cfg,
                        self._args(headless=True),
                        pre_ponr_state=state,
                    )

            self.assertIs(raised.exception, topology_error)
            rollback_control.assert_called_once_with(cfg, run_id)
            rollback_topology.assert_called_once_with(
                cfg,
                state["init_control_topology"],
            )
            rollback_memory.assert_not_called()
            warning.assert_not_called()

    def _case_web_ordinary_topology_failure_never_restores_memory(self):
        from freq.modules import init_cmd

        for outcome in ("return", "exception"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory(
                prefix=f"freq-init-web-{outcome}-topology-failure-"
            ) as root:
                cfg = self._cfg(root)
                state = init_cmd._capture_web_init_pre_ponr_state(cfg)
                topology_error = OSError(f"{outcome} topology cleanup failed")
                ordinary_failure = RuntimeError("ordinary pre-PONR failure")
                with mock.patch.dict(
                    os.environ,
                    {"FREQ_WEB_INIT": "1"},
                ), mock.patch.object(
                    init_cmd,
                    "_init_headless",
                    return_value=1,
                    side_effect=(
                        ordinary_failure if outcome == "exception" else None
                    ),
                ), mock.patch.object(
                    init_cmd,
                    "_rollback_init_control_topology",
                    side_effect=topology_error,
                ) as rollback_topology, mock.patch.object(
                    init_cmd,
                    "_rollback_web_init_pre_ponr_state",
                ) as rollback_memory:
                    with self.assertRaises(OSError) as raised:
                        init_cmd._run_web_init_with_cancel_signal(
                            cfg,
                            self._args(headless=True),
                            pre_ponr_state=state,
                        )

                self.assertIs(raised.exception, topology_error)
                rollback_topology.assert_called_once_with(
                    cfg,
                    state["init_control_topology"],
                )
                rollback_memory.assert_not_called()
                self.assertFalse(init_cmd._WEB_INIT_PONR_ENTERED.is_set())

    def _case_non_web_headless_ordinary_failures_preserve_pre_ponr_state(self):
        from freq.modules import init_cmd

        def prepare(root, label):
            cfg = self._cfg(root)
            self._seed_web_pre_ponr_mutables(cfg)
            init_cmd.INIT_MARKER = os.path.join(root, f"prior-{label}-marker")
            before = self._web_pre_ponr_snapshot(cfg, init_cmd.INIT_MARKER)
            os.makedirs(cfg.conf_dir)
            secret_paths = {}
            for name, value in (
                ("bootstrap_key", "key"),
                ("password_file", "service-password"),
                ("dashboard_password_file", "dashboard-password"),
            ):
                path = os.path.join(root, name.replace("_", "-"))
                with open(path, "w", encoding="utf-8") as secret_file:
                    secret_file.write(value)
                secret_paths[name] = path
            args = self._args(
                headless=True,
                bootstrap_key=secret_paths["bootstrap_key"],
                bootstrap_user="root",
                bootstrap_password_file=None,
                password_file=secret_paths["password_file"],
                dashboard_user="operator",
                dashboard_password_file=secret_paths["dashboard_password_file"],
                device_credentials=None,
                device_password_file=None,
                device_user="root",
                service_account="freq-admin",
                hosts_file=None,
            )
            return cfg, before, args

        for outcome in ("return", "exception"):
            with self.subTest(window="pre_control", outcome=outcome), tempfile.TemporaryDirectory(
                prefix=f"freq-init-headless-pre-control-{outcome}-"
            ) as root:
                cfg, before, args = prepare(root, f"pre-control-{outcome}")
                ordinary_failure = RuntimeError(
                    f"pre-control headless {outcome} failure"
                )
                real_topology_rollback = init_cmd._rollback_init_control_topology
                real_memory_rollback = init_cmd._rollback_web_init_pre_ponr_state
                rollback_events = []

                def mutate_operator_contract(_cfg, _args):
                    init_cmd._prepare_init_control_dir(cfg)
                    self._mutate_web_pre_ponr_members(cfg)
                    cfg.headless_ordinary_transient = "remove"

                def restore_topology(rollback_cfg, topology):
                    rollback_events.append("topology_begin")
                    result = real_topology_rollback(rollback_cfg, topology)
                    rollback_events.append("topology_complete")
                    return result

                def restore_memory(rollback_cfg, state):
                    self.assertEqual(
                        rollback_events,
                        ["topology_begin", "topology_complete"],
                    )
                    rollback_events.append("memory_begin")
                    result = real_memory_rollback(rollback_cfg, state)
                    rollback_events.append("memory_complete")
                    return result

                with mock.patch.dict(
                    os.environ,
                    {"FREQ_WEB_INIT": "0"},
                ), mock.patch.object(
                    init_cmd.os,
                    "geteuid",
                    return_value=1 if outcome == "return" else 0,
                ), mock.patch.object(
                    init_cmd,
                    "_apply_operator_vm_contract_args",
                    side_effect=mutate_operator_contract,
                ), mock.patch.object(
                    init_cmd,
                    "_load_device_credentials",
                    side_effect=(
                        ordinary_failure if outcome == "exception" else None
                    ),
                ), mock.patch.object(
                    init_cmd,
                    "_request_init_cancel",
                ) as request_cancel, mock.patch.object(
                    init_cmd,
                    "_rollback_cancelled_init_control",
                ) as rollback_control, mock.patch.object(
                    init_cmd,
                    "_rollback_init_control_topology",
                    side_effect=restore_topology,
                ), mock.patch.object(
                    init_cmd,
                    "_rollback_web_init_pre_ponr_state",
                    side_effect=restore_memory,
                ), mock.patch.object(
                    init_cmd, "_begin_init_phase"
                ) as begin_phase, mock.patch.object(
                    init_cmd, "_cross_init_point_of_no_return"
                ) as cross_boundary:
                    if outcome == "return":
                        self.assertEqual(init_cmd.cmd_init(cfg, None, args), 1)
                    else:
                        with self.assertRaises(RuntimeError) as raised:
                            init_cmd.cmd_init(cfg, None, args)
                        self.assertIs(raised.exception, ordinary_failure)

                request_cancel.assert_not_called()
                rollback_control.assert_not_called()
                begin_phase.assert_not_called()
                cross_boundary.assert_not_called()
                self.assertEqual(
                    rollback_events,
                    [
                        "topology_begin",
                        "topology_complete",
                        "memory_begin",
                        "memory_complete",
                    ],
                )
                self._assert_web_pre_ponr_restored(cfg, before)
                self.assertFalse(os.path.lexists(cfg.data_dir))

        for outcome in ("return", "exception"):
            with self.subTest(window="run_ready", outcome=outcome), tempfile.TemporaryDirectory(
                prefix=f"freq-init-headless-run-ready-{outcome}-"
            ) as root:
                cfg, before, args = prepare(root, f"run-ready-{outcome}")
                ordinary_failure = RuntimeError(
                    f"run-ready pre-PONR headless {outcome} failure"
                )
                run_id = self._run_id(f"headless-run-ready-{outcome}")
                real_request_cancel = init_cmd._request_init_cancel
                real_control_rollback = init_cmd._rollback_cancelled_init_control
                real_topology_rollback = init_cmd._rollback_init_control_topology
                real_memory_rollback = init_cmd._rollback_web_init_pre_ponr_state
                rollback_events = []

                def mutate_operator_contract(_cfg, _args):
                    self._mutate_web_pre_ponr_members(cfg)
                    cfg.headless_ordinary_transient = "remove"

                def fail_after_run_publication(
                    _cfg,
                    _args,
                    *,
                    interruption_state,
                ):
                    init_cmd._prepare_init_control_dir(cfg)
                    interruption_state["run_id"] = run_id
                    if outcome == "exception":
                        raise ordinary_failure
                    return 1

                def restore_control(rollback_cfg, rollback_run_id):
                    rollback_events.append("control_begin")
                    result = real_control_rollback(rollback_cfg, rollback_run_id)
                    rollback_events.append("control_complete")
                    return result

                def restore_topology(rollback_cfg, topology):
                    self.assertEqual(
                        rollback_events,
                        ["control_begin", "control_complete"],
                    )
                    rollback_events.append("topology_begin")
                    result = real_topology_rollback(rollback_cfg, topology)
                    rollback_events.append("topology_complete")
                    return result

                def restore_memory(rollback_cfg, state):
                    self.assertEqual(
                        rollback_events,
                        [
                            "control_begin",
                            "control_complete",
                            "topology_begin",
                            "topology_complete",
                        ],
                    )
                    rollback_events.append("memory_begin")
                    result = real_memory_rollback(rollback_cfg, state)
                    rollback_events.append("memory_complete")
                    return result

                with mock.patch.dict(
                    os.environ,
                    {"FREQ_WEB_INIT": "0"},
                ), mock.patch.object(
                    init_cmd,
                    "_apply_operator_vm_contract_args",
                    side_effect=mutate_operator_contract,
                ), mock.patch.object(
                    init_cmd,
                    "_init_headless",
                    side_effect=fail_after_run_publication,
                ), mock.patch.object(
                    init_cmd,
                    "_request_init_cancel",
                    wraps=real_request_cancel,
                ) as request_cancel, mock.patch.object(
                    init_cmd,
                    "_rollback_cancelled_init_control",
                    side_effect=restore_control,
                ) as rollback_control, mock.patch.object(
                    init_cmd,
                    "_rollback_init_control_topology",
                    side_effect=restore_topology,
                ), mock.patch.object(
                    init_cmd,
                    "_rollback_web_init_pre_ponr_state",
                    side_effect=restore_memory,
                ):
                    if outcome == "return":
                        self.assertEqual(init_cmd.cmd_init(cfg, None, args), 1)
                    else:
                        with self.assertRaises(RuntimeError) as raised:
                            init_cmd.cmd_init(cfg, None, args)
                        self.assertIs(raised.exception, ordinary_failure)

                request_cancel.assert_called_once_with(cfg, run_id)
                rollback_control.assert_called_once_with(cfg, run_id)
                self.assertEqual(
                    rollback_events,
                    [
                        "control_begin",
                        "control_complete",
                        "topology_begin",
                        "topology_complete",
                        "memory_begin",
                        "memory_complete",
                    ],
                )
                self._assert_web_pre_ponr_restored(cfg, before)
                self.assertFalse(os.path.lexists(cfg.data_dir))

        for outcome in ("return", "exception"):
            with self.subTest(window="post_ponr", outcome=outcome), tempfile.TemporaryDirectory(
                prefix=f"freq-init-headless-post-ponr-{outcome}-"
            ) as root:
                cfg, before, args = prepare(root, f"post-ponr-{outcome}")
                ordinary_failure = RuntimeError(
                    f"post-PONR headless {outcome} failure"
                )
                real_request_cancel = init_cmd._request_init_cancel

                def mutate_operator_contract(_cfg, _args):
                    self._mutate_web_pre_ponr_members(cfg)
                    cfg.headless_ordinary_transient = "retain"

                with mock.patch.dict(
                    os.environ,
                    {"FREQ_WEB_INIT": "0"},
                ), mock.patch.object(
                    init_cmd.os, "geteuid", return_value=0
                ), mock.patch.object(
                    init_cmd,
                    "_apply_operator_vm_contract_args",
                    side_effect=mutate_operator_contract,
                ), mock.patch.object(
                    init_cmd, "_load_device_credentials", return_value={}
                ), mock.patch.object(
                    init_cmd, "_validate_device_scoped_service_password", return_value=True
                ), mock.patch.object(
                    init_cmd, "_validate_truenas_deployment_credentials", return_value=True
                ), mock.patch.object(
                    init_cmd, "_validate_device_credential_scopes", return_value=True
                ), mock.patch.object(
                    init_cmd, "_validate_username", return_value=True
                ), mock.patch.object(
                    init_cmd, "_validate_service_account_choice", return_value=True
                ), mock.patch.object(
                    init_cmd,
                    "_headless_phase2_inputs_match_current_config",
                    return_value=False,
                ), mock.patch.object(
                    init_cmd,
                    "_clear_generated_runtime_truth_state",
                ), mock.patch.object(
                    init_cmd,
                    "_phase_welcome",
                    return_value=False,
                    side_effect=(
                        ordinary_failure if outcome == "exception" else None
                    ),
                ), mock.patch.object(
                    init_cmd,
                    "_request_init_cancel",
                    wraps=real_request_cancel,
                ) as request_cancel, mock.patch.object(
                    init_cmd,
                    "_rollback_cancelled_init_control",
                ) as rollback_control, mock.patch.object(
                    init_cmd,
                    "_rollback_init_pre_ponr_state",
                ) as rollback_state, mock.patch.object(
                    init_cmd,
                    "_cross_init_point_of_no_return",
                    wraps=init_cmd._cross_init_point_of_no_return,
                ) as cross_boundary:
                    if outcome == "return":
                        self.assertEqual(init_cmd.cmd_init(cfg, None, args), 1)
                    else:
                        with self.assertRaises(RuntimeError) as raised:
                            init_cmd.cmd_init(cfg, None, args)
                        self.assertIs(raised.exception, ordinary_failure)

                cross_boundary.assert_called_once()
                request_cancel.assert_called_once()
                rollback_control.assert_not_called()
                rollback_state.assert_not_called()
                run_id = request_cancel.call_args.args[1]
                self.assertIs(
                    real_request_cancel(cfg, run_id),
                    init_cmd._InitControlState.POINT_OF_NO_RETURN,
                )
                self.assertNotEqual(vars(cfg), before[1])
                self.assertEqual(cfg.headless_ordinary_transient, "retain")
                self.assertTrue(os.path.lexists(cfg.data_dir))

        for outcome in ("return", "exception"):
            with self.subTest(
                window="cleanup_failure",
                outcome=outcome,
            ), tempfile.TemporaryDirectory(
                prefix=f"freq-init-headless-cleanup-failure-{outcome}-"
            ) as root:
                cfg, _before, args = prepare(root, f"cleanup-failure-{outcome}")
                ordinary_failure = RuntimeError(
                    f"pre-PONR headless {outcome} failure"
                )
                topology_error = OSError("headless topology cleanup failed")

                def fail_before_run_publication(
                    _cfg,
                    _args,
                    *,
                    interruption_state,
                ):
                    self.assertEqual(interruption_state, {})
                    if outcome == "exception":
                        raise ordinary_failure
                    return 1

                with mock.patch.dict(
                    os.environ,
                    {"FREQ_WEB_INIT": "0"},
                ), mock.patch.object(
                    init_cmd,
                    "_init_headless",
                    side_effect=fail_before_run_publication,
                ), mock.patch.object(
                    init_cmd,
                    "_request_init_cancel",
                ) as request_cancel, mock.patch.object(
                    init_cmd,
                    "_rollback_cancelled_init_control",
                ) as rollback_control, mock.patch.object(
                    init_cmd,
                    "_rollback_init_control_topology",
                    side_effect=topology_error,
                ) as rollback_topology, mock.patch.object(
                    init_cmd,
                    "_rollback_web_init_pre_ponr_state",
                ) as rollback_memory:
                    with self.assertRaises(OSError) as raised:
                        init_cmd.cmd_init(cfg, None, args)

                self.assertIs(raised.exception, topology_error)
                request_cancel.assert_not_called()
                rollback_control.assert_not_called()
                rollback_topology.assert_called_once()
                rollback_memory.assert_not_called()

        for cleanup_stage in ("control", "topology"):
            for outcome in ("return", "exception"):
                with self.subTest(
                    window="run_ready_cleanup_failure",
                    cleanup_stage=cleanup_stage,
                    outcome=outcome,
                ), tempfile.TemporaryDirectory(
                    prefix=(
                        "freq-init-headless-run-ready-"
                        f"{cleanup_stage}-failure-{outcome}-"
                    )
                ) as root:
                    cfg, _before, args = prepare(
                        root,
                        f"run-ready-{cleanup_stage}-failure-{outcome}",
                    )
                    run_id = self._run_id(
                        f"headless-{cleanup_stage}-failure-{outcome}"
                    )
                    ordinary_failure = RuntimeError(
                        f"run-ready headless {outcome} failure"
                    )
                    cleanup_error = OSError(
                        f"headless {cleanup_stage} cleanup failed"
                    )
                    real_request_cancel = init_cmd._request_init_cancel
                    real_control_rollback = init_cmd._rollback_cancelled_init_control

                    def fail_after_run_publication(
                        _cfg,
                        _args,
                        *,
                        interruption_state,
                    ):
                        init_cmd._prepare_init_control_dir(cfg)
                        interruption_state["run_id"] = run_id
                        if outcome == "exception":
                            raise ordinary_failure
                        return 1

                    control_side_effect = (
                        cleanup_error
                        if cleanup_stage == "control"
                        else real_control_rollback
                    )
                    topology_side_effect = (
                        cleanup_error
                        if cleanup_stage == "topology"
                        else None
                    )
                    with mock.patch.dict(
                        os.environ,
                        {"FREQ_WEB_INIT": "0"},
                    ), mock.patch.object(
                        init_cmd,
                        "_init_headless",
                        side_effect=fail_after_run_publication,
                    ), mock.patch.object(
                        init_cmd,
                        "_request_init_cancel",
                        wraps=real_request_cancel,
                    ) as request_cancel, mock.patch.object(
                        init_cmd,
                        "_rollback_cancelled_init_control",
                        side_effect=control_side_effect,
                    ) as rollback_control, mock.patch.object(
                        init_cmd,
                        "_rollback_init_control_topology",
                        side_effect=topology_side_effect,
                    ) as rollback_topology, mock.patch.object(
                        init_cmd,
                        "_rollback_web_init_pre_ponr_state",
                    ) as rollback_memory:
                        with self.assertRaises(OSError) as raised:
                            init_cmd.cmd_init(cfg, None, args)

                    self.assertIs(raised.exception, cleanup_error)
                    request_cancel.assert_called_once_with(cfg, run_id)
                    rollback_control.assert_called_once_with(cfg, run_id)
                    if cleanup_stage == "control":
                        rollback_topology.assert_not_called()
                    else:
                        rollback_topology.assert_called_once()
                    rollback_memory.assert_not_called()

        with self.subTest(window="invalid_arbitration"), tempfile.TemporaryDirectory(
            prefix="freq-init-headless-invalid-arbitration-"
        ) as root:
            cfg, _before, _args = prepare(root, "invalid-arbitration")
            state = init_cmd._capture_web_init_pre_ponr_state(cfg)
            run_id = self._run_id("headless-invalid-arbitration")
            with mock.patch.object(
                init_cmd,
                "_request_init_cancel",
                return_value=init_cmd._InitControlState.PRE_PONR,
            ), mock.patch.object(
                init_cmd,
                "_rollback_cancelled_init_control",
            ) as rollback_control, mock.patch.object(
                init_cmd,
                "_rollback_init_pre_ponr_state",
            ) as rollback_state:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "headless init failure arbitration returned invalid state",
                ):
                    init_cmd._restore_init_if_pre_ponr(
                        cfg,
                        state,
                        run_id,
                        mode="headless",
                        outcome="failure",
                    )

            rollback_control.assert_not_called()
            rollback_state.assert_not_called()

    def _case_interactive_ordinary_failures_preserve_pre_ponr_state(self):
        from freq.modules import init_cmd

        def prepare(root, label):
            cfg = self._cfg(root)
            self._seed_web_pre_ponr_mutables(cfg)
            init_cmd.INIT_MARKER = os.path.join(root, f"prior-{label}-marker")
            before = self._web_pre_ponr_snapshot(cfg, init_cmd.INIT_MARKER)
            os.makedirs(cfg.conf_dir)
            return cfg, before, self._args()

        for failure_stage in ("operator", "preparation"):
            with self.subTest(
                window="direct",
                failure_stage=failure_stage,
            ), tempfile.TemporaryDirectory(
                prefix=f"freq-init-interactive-{failure_stage}-exception-"
            ) as root:
                cfg, before, args = prepare(root, f"{failure_stage}-exception")
                ordinary_failure = RuntimeError(
                    f"interactive {failure_stage} failed"
                )
                real_topology_rollback = init_cmd._rollback_init_control_topology
                real_memory_rollback = init_cmd._rollback_web_init_pre_ponr_state
                rollback_events = []

                def mutate_operator_contract(_cfg, _args):
                    self._mutate_web_pre_ponr_members(cfg)
                    cfg.interactive_ordinary_transient = "remove"
                    if failure_stage == "operator":
                        init_cmd._prepare_init_control_dir(cfg)
                        raise ordinary_failure

                def restore_topology(rollback_cfg, topology):
                    rollback_events.append("topology_begin")
                    result = real_topology_rollback(rollback_cfg, topology)
                    rollback_events.append("topology_complete")
                    return result

                def restore_memory(rollback_cfg, state):
                    self.assertEqual(
                        rollback_events,
                        ["topology_begin", "topology_complete"],
                    )
                    rollback_events.append("memory_begin")
                    result = real_memory_rollback(rollback_cfg, state)
                    rollback_events.append("memory_complete")
                    return result

                with mock.patch.object(
                    init_cmd.os, "geteuid", return_value=0
                ), mock.patch(
                    "freq.core.personality.splash"
                ), mock.patch.object(
                    init_cmd,
                    "_apply_operator_vm_contract_args",
                    side_effect=mutate_operator_contract,
                ), mock.patch.object(
                    init_cmd,
                    "_begin_init_phase",
                    side_effect=(
                        ordinary_failure
                        if failure_stage == "preparation"
                        else None
                    ),
                ) as begin_phase, mock.patch.object(
                    init_cmd,
                    "_request_init_cancel",
                ) as request_cancel, mock.patch.object(
                    init_cmd,
                    "_rollback_cancelled_init_control",
                ) as rollback_control, mock.patch.object(
                    init_cmd,
                    "_rollback_init_control_topology",
                    side_effect=restore_topology,
                ), mock.patch.object(
                    init_cmd,
                    "_rollback_web_init_pre_ponr_state",
                    side_effect=restore_memory,
                ), mock.patch.object(
                    init_cmd, "_cross_init_point_of_no_return"
                ) as cross_boundary:
                    with self.assertRaises(RuntimeError) as raised:
                        init_cmd.cmd_init(cfg, None, args)

                self.assertIs(raised.exception, ordinary_failure)
                if failure_stage == "operator":
                    begin_phase.assert_not_called()
                else:
                    begin_phase.assert_called_once()
                request_cancel.assert_not_called()
                rollback_control.assert_not_called()
                cross_boundary.assert_not_called()
                self.assertEqual(
                    rollback_events,
                    [
                        "topology_begin",
                        "topology_complete",
                        "memory_begin",
                        "memory_complete",
                    ],
                )
                self._assert_web_pre_ponr_restored(cfg, before)
                self.assertFalse(os.path.lexists(cfg.data_dir))

        for failure_stage in ("operator", "preparation"):
            with self.subTest(
                window="direct_cleanup_error",
                failure_stage=failure_stage,
            ), tempfile.TemporaryDirectory(
                prefix=(
                    f"freq-init-interactive-{failure_stage}-cleanup-error-"
                )
            ) as root:
                cfg, _before, args = prepare(
                    root,
                    f"{failure_stage}-cleanup-error",
                )
                ordinary_failure = RuntimeError(
                    f"interactive {failure_stage} failed before cleanup"
                )
                topology_error = OSError(
                    f"interactive {failure_stage} topology cleanup failed"
                )

                def mutate_operator_contract(_cfg, _args):
                    self._mutate_web_pre_ponr_members(cfg)
                    cfg.interactive_ordinary_transient = "remove"
                    if failure_stage == "operator":
                        init_cmd._prepare_init_control_dir(cfg)
                        raise ordinary_failure

                with mock.patch.object(
                    init_cmd.os, "geteuid", return_value=0
                ), mock.patch(
                    "freq.core.personality.splash"
                ), mock.patch.object(
                    init_cmd,
                    "_apply_operator_vm_contract_args",
                    side_effect=mutate_operator_contract,
                ), mock.patch.object(
                    init_cmd,
                    "_begin_init_phase",
                    side_effect=(
                        ordinary_failure
                        if failure_stage == "preparation"
                        else None
                    ),
                ) as begin_phase, mock.patch.object(
                    init_cmd,
                    "_request_init_cancel",
                ) as request_cancel, mock.patch.object(
                    init_cmd,
                    "_rollback_cancelled_init_control",
                ) as rollback_control, mock.patch.object(
                    init_cmd,
                    "_rollback_init_control_topology",
                    side_effect=topology_error,
                ) as rollback_topology, mock.patch.object(
                    init_cmd,
                    "_rollback_web_init_pre_ponr_state",
                ) as rollback_memory, mock.patch.object(
                    init_cmd, "_cross_init_point_of_no_return"
                ) as cross_boundary:
                    with self.assertRaises(OSError) as raised:
                        init_cmd.cmd_init(cfg, None, args)

                self.assertIs(raised.exception, topology_error)
                if failure_stage == "operator":
                    begin_phase.assert_not_called()
                else:
                    begin_phase.assert_called_once()
                rollback_topology.assert_called_once()
                rollback_memory.assert_not_called()
                request_cancel.assert_not_called()
                rollback_control.assert_not_called()
                cross_boundary.assert_not_called()

        with self.subTest(window="boundary_cancel"), tempfile.TemporaryDirectory(
            prefix="freq-init-interactive-boundary-exception-"
        ) as root:
            cfg, before, args = prepare(root, "boundary-exception")
            ordinary_failure = RuntimeError("interactive boundary failed")
            real_request_cancel = init_cmd._request_init_cancel
            real_control_rollback = init_cmd._rollback_cancelled_init_control
            real_topology_rollback = init_cmd._rollback_init_control_topology
            real_memory_rollback = init_cmd._rollback_web_init_pre_ponr_state
            rollback_events = []

            def mutate_operator_contract(_cfg, _args):
                self._mutate_web_pre_ponr_members(cfg)
                cfg.interactive_ordinary_transient = "remove"

            def restore_control(rollback_cfg, run_id):
                rollback_events.append("control_begin")
                result = real_control_rollback(rollback_cfg, run_id)
                rollback_events.append("control_complete")
                return result

            def restore_topology(rollback_cfg, topology):
                self.assertEqual(
                    rollback_events,
                    ["control_begin", "control_complete"],
                )
                rollback_events.append("topology_begin")
                result = real_topology_rollback(rollback_cfg, topology)
                rollback_events.append("topology_complete")
                return result

            def restore_memory(rollback_cfg, state):
                self.assertEqual(
                    rollback_events,
                    [
                        "control_begin",
                        "control_complete",
                        "topology_begin",
                        "topology_complete",
                    ],
                )
                rollback_events.append("memory_begin")
                result = real_memory_rollback(rollback_cfg, state)
                rollback_events.append("memory_complete")
                return result

            with mock.patch.object(
                init_cmd.os, "geteuid", return_value=0
            ), mock.patch(
                "freq.core.personality.splash"
            ), mock.patch.object(
                init_cmd,
                "_apply_operator_vm_contract_args",
                side_effect=mutate_operator_contract,
            ), mock.patch.object(
                init_cmd, "_begin_init_phase", return_value=object()
            ), mock.patch.object(
                init_cmd,
                "_request_init_cancel",
                wraps=real_request_cancel,
            ) as request_cancel, mock.patch.object(
                init_cmd,
                "_rollback_cancelled_init_control",
                side_effect=restore_control,
            ) as rollback_control, mock.patch.object(
                init_cmd,
                "_rollback_init_control_topology",
                side_effect=restore_topology,
            ), mock.patch.object(
                init_cmd,
                "_rollback_web_init_pre_ponr_state",
                side_effect=restore_memory,
            ), mock.patch.object(
                init_cmd,
                "_cross_init_point_of_no_return",
                side_effect=ordinary_failure,
            ), mock.patch.object(
                init_cmd, "_phase_welcome"
            ) as welcome:
                with self.assertRaises(RuntimeError) as raised:
                    init_cmd.cmd_init(cfg, None, args)

            self.assertIs(raised.exception, ordinary_failure)
            request_cancel.assert_called_once()
            rollback_control.assert_called_once_with(
                cfg,
                request_cancel.call_args.args[1],
            )
            welcome.assert_not_called()
            self.assertEqual(
                rollback_events,
                [
                    "control_begin",
                    "control_complete",
                    "topology_begin",
                    "topology_complete",
                    "memory_begin",
                    "memory_complete",
                ],
            )
            self._assert_web_pre_ponr_restored(cfg, before)
            self.assertFalse(os.path.lexists(cfg.data_dir))

        with self.subTest(window="boundary_post_ponr"), tempfile.TemporaryDirectory(
            prefix="freq-init-interactive-post-ponr-exception-"
        ) as root:
            cfg, before, args = prepare(root, "post-ponr-exception")
            ordinary_failure = RuntimeError("interactive post-PONR failure")
            real_cross_boundary = init_cmd._cross_init_point_of_no_return
            real_request_cancel = init_cmd._request_init_cancel

            def mutate_operator_contract(_cfg, _args):
                self._mutate_web_pre_ponr_members(cfg)
                cfg.interactive_ordinary_transient = "retain"

            def fail_after_boundary(*call_args, **call_kwargs):
                real_cross_boundary(*call_args, **call_kwargs)
                raise ordinary_failure

            with mock.patch.object(
                init_cmd.os, "geteuid", return_value=0
            ), mock.patch(
                "freq.core.personality.splash"
            ), mock.patch.object(
                init_cmd,
                "_apply_operator_vm_contract_args",
                side_effect=mutate_operator_contract,
            ), mock.patch.object(
                init_cmd, "_begin_init_phase", return_value=object()
            ), mock.patch.object(
                init_cmd,
                "_request_init_cancel",
                wraps=real_request_cancel,
            ) as request_cancel, mock.patch.object(
                init_cmd,
                "_rollback_cancelled_init_control",
            ) as rollback_control, mock.patch.object(
                init_cmd,
                "_rollback_init_pre_ponr_state",
            ) as rollback_state, mock.patch.object(
                init_cmd,
                "_cross_init_point_of_no_return",
                side_effect=fail_after_boundary,
            ), mock.patch.object(
                init_cmd, "_phase_welcome"
            ) as welcome:
                with self.assertRaises(RuntimeError) as raised:
                    init_cmd.cmd_init(cfg, None, args)

            self.assertIs(raised.exception, ordinary_failure)
            request_cancel.assert_called_once()
            rollback_control.assert_not_called()
            rollback_state.assert_not_called()
            welcome.assert_not_called()
            run_id = request_cancel.call_args.args[1]
            self.assertIs(
                real_request_cancel(cfg, run_id),
                init_cmd._InitControlState.POINT_OF_NO_RETURN,
            )
            self.assertNotEqual(vars(cfg), before[1])
            self.assertEqual(cfg.interactive_ordinary_transient, "retain")
            self.assertTrue(os.path.lexists(cfg.data_dir))

        for cleanup_stage in ("control", "topology"):
            with self.subTest(
                window="boundary_cleanup_failure",
                cleanup_stage=cleanup_stage,
            ), tempfile.TemporaryDirectory(
                prefix=f"freq-init-interactive-{cleanup_stage}-failure-"
            ) as root:
                cfg, _before, args = prepare(root, f"{cleanup_stage}-failure")
                ordinary_failure = RuntimeError("interactive boundary failed")
                cleanup_error = OSError(
                    f"interactive {cleanup_stage} cleanup failed"
                )
                real_request_cancel = init_cmd._request_init_cancel
                real_control_rollback = init_cmd._rollback_cancelled_init_control
                control_side_effect = (
                    cleanup_error
                    if cleanup_stage == "control"
                    else real_control_rollback
                )
                topology_side_effect = (
                    cleanup_error
                    if cleanup_stage == "topology"
                    else None
                )

                with mock.patch.object(
                    init_cmd.os, "geteuid", return_value=0
                ), mock.patch(
                    "freq.core.personality.splash"
                ), mock.patch.object(
                    init_cmd, "_begin_init_phase", return_value=object()
                ), mock.patch.object(
                    init_cmd,
                    "_request_init_cancel",
                    wraps=real_request_cancel,
                ) as request_cancel, mock.patch.object(
                    init_cmd,
                    "_rollback_cancelled_init_control",
                    side_effect=control_side_effect,
                ) as rollback_control, mock.patch.object(
                    init_cmd,
                    "_rollback_init_control_topology",
                    side_effect=topology_side_effect,
                ) as rollback_topology, mock.patch.object(
                    init_cmd,
                    "_rollback_web_init_pre_ponr_state",
                ) as rollback_memory, mock.patch.object(
                    init_cmd,
                    "_cross_init_point_of_no_return",
                    side_effect=ordinary_failure,
                ):
                    with self.assertRaises(OSError) as raised:
                        init_cmd.cmd_init(cfg, None, args)

                self.assertIs(raised.exception, cleanup_error)
                request_cancel.assert_called_once()
                rollback_control.assert_called_once_with(
                    cfg,
                    request_cancel.call_args.args[1],
                )
                if cleanup_stage == "control":
                    rollback_topology.assert_not_called()
                else:
                    rollback_topology.assert_called_once()
                rollback_memory.assert_not_called()

        with self.subTest(window="boundary_invalid"), tempfile.TemporaryDirectory(
            prefix="freq-init-interactive-invalid-arbitration-"
        ) as root:
            cfg, _before, args = prepare(root, "invalid-arbitration")
            ordinary_failure = RuntimeError("interactive boundary failed")
            with mock.patch.object(
                init_cmd.os, "geteuid", return_value=0
            ), mock.patch(
                "freq.core.personality.splash"
            ), mock.patch.object(
                init_cmd, "_begin_init_phase", return_value=object()
            ), mock.patch.object(
                init_cmd,
                "_request_init_cancel",
                return_value=init_cmd._InitControlState.PRE_PONR,
            ), mock.patch.object(
                init_cmd,
                "_rollback_cancelled_init_control",
            ) as rollback_control, mock.patch.object(
                init_cmd,
                "_rollback_init_pre_ponr_state",
            ) as rollback_state, mock.patch.object(
                init_cmd,
                "_cross_init_point_of_no_return",
                side_effect=ordinary_failure,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "interactive init failure arbitration returned invalid state",
                ):
                    init_cmd.cmd_init(cfg, None, args)

            rollback_control.assert_not_called()
            rollback_state.assert_not_called()

    def _case_parent_delivers_owned_cancel_once(self):
        import ast
        import concurrent.futures
        import inspect
        from functools import partial

        from freq.modules import serve
        from freq.services import setup_progress

        serve_tree = ast.parse(inspect.getsource(serve))
        service_tree = ast.parse(inspect.getsource(setup_progress))
        controller_names = {
            "deliver_setup_init_cancel",
            "publish_setup_init_process",
            "request_setup_init_cancel",
        }
        self.assertEqual(
            {
                node.name
                for node in service_tree.body
                if isinstance(node, ast.FunctionDef) and node.name in controller_names
            },
            controller_names,
        )
        self.assertFalse(
            any(
                isinstance(node, ast.FunctionDef)
                and node.name in {f"_{name}" for name in controller_names}
                for node in serve_tree.body
            )
        )
        self.assertEqual(
            {
                name: sum(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == name
                    for node in ast.walk(service_tree)
                )
                for name in controller_names
            },
            {
                "deliver_setup_init_cancel": 2,
                "publish_setup_init_process": 0,
                "request_setup_init_cancel": 0,
            },
        )
        self.assertEqual(
            {
                name: sum(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == name
                    for node in ast.walk(serve_tree)
                )
                for name in {
                    "_deliver_setup_init_cancel",
                    "_publish_setup_init_process",
                    "_request_setup_init_cancel",
                }
            },
            {
                "_deliver_setup_init_cancel": 0,
                "_publish_setup_init_process": 1,
                "_request_setup_init_cancel": 1,
            },
        )
        deliver_tree = next(
            node
            for node in service_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "deliver_setup_init_cancel"
        )
        self.assertEqual(
            [
                ast.unparse(node)
                for node in ast.walk(deliver_tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "send_signal"
            ],
            ["process.send_signal(signal.SIGINT)"],
        )
        self.assertFalse(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
                and node.func.attr == "kill"
                for name in controller_names
                for function in service_tree.body
                if isinstance(function, ast.FunctionDef) and function.name == name
                for node in ast.walk(function)
            )
        )
        compatibility = {
            "_deliver_setup_init_cancel": setup_progress.deliver_setup_init_cancel,
            "_publish_setup_init_process": setup_progress.publish_setup_init_process,
            "_request_setup_init_cancel": setup_progress.request_setup_init_cancel,
        }
        for name, lower_function in compatibility.items():
            adapter = getattr(serve, name)
            self.assertIsInstance(adapter, partial)
            self.assertIs(adapter.func, lower_function)
            self.assertEqual(set(adapter.keywords), {"runtime"})
            self.assertIs(
                adapter.keywords["runtime"],
                serve._setup_init_cancellation_runtime,
            )
        runtime = serve._setup_init_cancellation_runtime
        self.assertTrue(runtime.__dataclass_params__.frozen)
        self.assertEqual(set(runtime.__dataclass_fields__), {"current_lock", "current_job"})
        self.assertIs(runtime.current_lock(), serve._setup_init_lock)
        self.assertIs(runtime.current_job(), serve._setup_init_job)
        self.assertEqual(
            serve._SETUP_INIT_CANCEL_REQUESTED,
            setup_progress.SETUP_INIT_CANCEL_REQUESTED,
        )
        self.assertEqual(
            serve._SETUP_INIT_CANCEL_NOT_FOUND,
            setup_progress.SETUP_INIT_CANCEL_NOT_FOUND,
        )
        self.assertEqual(
            serve._SETUP_INIT_CANCEL_NOT_RUNNING,
            setup_progress.SETUP_INIT_CANCEL_NOT_RUNNING,
        )
        self.assertEqual(serve._SETUP_INIT_CANCEL_REQUESTED, "requested")
        self.assertEqual(serve._SETUP_INIT_CANCEL_NOT_FOUND, "not_found")
        self.assertEqual(serve._SETUP_INIT_CANCEL_NOT_RUNNING, "not_running")

        class ChildProcess:
            def __init__(self, pid, errors=(), on_signal=None):
                self.pid = pid
                self.errors = list(errors)
                self.on_signal = on_signal
                self.signals = []

            def send_signal(self, signum):
                self.signals.append(signum)
                if self.on_signal is not None:
                    self.on_signal(self)
                if self.errors:
                    raise self.errors.pop(0)

        def job(job_id, *, owner="operator", state="queued"):
            return {
                "id": job_id,
                "owner": owner,
                "state": state,
                "pid": None,
                "process": None,
                "cancel_requested": False,
                "cancel_signal_sent": False,
                "cancel_delivery_failed": False,
            }

        original_job = serve._setup_init_job
        try:
            serve._setup_init_job = None
            self.assertEqual(
                serve._request_setup_init_cancel("missing", "operator"),
                serve._SETUP_INIT_CANCEL_NOT_FOUND,
            )

            queued_id = self._run_id("queued-parent-cancel")
            queued_process = ChildProcess(4101)
            delivery_error = OSError("queued cancellation delivery failed")
            queued_process.errors.append(delivery_error)
            serve._setup_init_job = job(queued_id)
            self.assertEqual(
                serve._request_setup_init_cancel(queued_id, "other-operator"),
                serve._SETUP_INIT_CANCEL_NOT_FOUND,
            )
            self.assertFalse(serve._setup_init_job["cancel_requested"])
            self.assertEqual(
                serve._request_setup_init_cancel(queued_id, "operator"),
                serve._SETUP_INIT_CANCEL_REQUESTED,
            )
            self.assertTrue(serve._setup_init_job["cancel_requested"])
            self.assertEqual(queued_process.signals, [])
            self.assertFalse(
                serve._publish_setup_init_process(queued_id, queued_process)
            )
            self.assertFalse(serve._setup_init_job["cancel_signal_sent"])
            self.assertTrue(serve._setup_init_job["cancel_delivery_failed"])
            self.assertIs(serve._setup_init_job["process"], queued_process)
            self.assertTrue(
                serve._publish_setup_init_process(queued_id, queued_process)
            )
            self.assertEqual(
                queued_process.signals,
                [serve.signal.SIGINT, serve.signal.SIGINT],
            )
            self.assertTrue(serve._setup_init_job["cancel_signal_sent"])
            self.assertFalse(serve._setup_init_job["cancel_delivery_failed"])
            self.assertEqual(serve._setup_init_job["pid"], queued_process.pid)
            self.assertEqual(
                serve._request_setup_init_cancel(queued_id, "operator"),
                serve._SETUP_INIT_CANCEL_REQUESTED,
            )
            self.assertEqual(len(queued_process.signals), 2)

            error_id = self._run_id("running-parent-cancel-error")
            running_delivery_error = OSError("running cancellation delivery failed")
            error_process = ChildProcess(4104, errors=(running_delivery_error,))
            serve._setup_init_job = job(error_id, state="running")
            self.assertTrue(
                serve._publish_setup_init_process(error_id, error_process)
            )
            with self.assertRaises(OSError) as raised:
                serve._request_setup_init_cancel(error_id, "operator")
            self.assertIs(raised.exception, running_delivery_error)
            self.assertFalse(serve._setup_init_job["cancel_signal_sent"])
            self.assertTrue(serve._setup_init_job["cancel_delivery_failed"])
            self.assertEqual(
                serve._request_setup_init_cancel(error_id, "operator"),
                serve._SETUP_INIT_CANCEL_REQUESTED,
            )
            self.assertEqual(
                error_process.signals,
                [serve.signal.SIGINT, serve.signal.SIGINT],
            )
            self.assertFalse(serve._setup_init_job["cancel_delivery_failed"])

            stale_id = self._run_id("stale-parent-cancel")
            replacement_id = self._run_id("replacement-parent-cancel")
            replacement = job(replacement_id, state="running")
            replacement["cancel_delivery_failed"] = True
            stale_error = OSError("stale cancellation delivery failed")
            stale_process = ChildProcess(
                4105,
                errors=(stale_error,),
                on_signal=lambda _process: setattr(
                    serve,
                    "_setup_init_job",
                    replacement,
                ),
            )
            serve._setup_init_job = job(stale_id, state="running")
            self.assertTrue(
                serve._publish_setup_init_process(stale_id, stale_process)
            )
            with self.assertRaises(OSError) as raised:
                serve._request_setup_init_cancel(stale_id, "operator")
            self.assertIs(raised.exception, stale_error)
            self.assertIs(serve._setup_init_job, replacement)
            self.assertFalse(replacement["cancel_requested"])
            self.assertFalse(replacement["cancel_signal_sent"])
            self.assertTrue(replacement["cancel_delivery_failed"])

            stale_success_id = self._run_id("stale-success-parent-cancel")
            success_replacement = job(
                self._run_id("success-replacement-parent-cancel"),
                state="running",
            )
            success_replacement["cancel_delivery_failed"] = True
            stale_success_process = ChildProcess(
                4106,
                on_signal=lambda _process: setattr(
                    serve,
                    "_setup_init_job",
                    success_replacement,
                ),
            )
            serve._setup_init_job = job(stale_success_id, state="running")
            self.assertTrue(
                serve._publish_setup_init_process(
                    stale_success_id,
                    stale_success_process,
                )
            )
            self.assertEqual(
                serve._request_setup_init_cancel(stale_success_id, "operator"),
                serve._SETUP_INIT_CANCEL_REQUESTED,
            )
            self.assertIs(serve._setup_init_job, success_replacement)
            self.assertFalse(success_replacement["cancel_requested"])
            self.assertFalse(success_replacement["cancel_signal_sent"])
            self.assertTrue(success_replacement["cancel_delivery_failed"])

            running_id = self._run_id("running-parent-cancel")
            running_process = ChildProcess(4102)
            serve._setup_init_job = job(running_id, state="running")
            self.assertTrue(
                serve._publish_setup_init_process(running_id, running_process)
            )
            self.assertEqual(running_process.signals, [])
            with mock.patch.object(serve.os, "kill") as pid_kill, concurrent.futures.ThreadPoolExecutor(
                max_workers=8
            ) as pool:
                outcomes = list(
                    pool.map(
                        lambda _index: serve._request_setup_init_cancel(
                            running_id,
                            "operator",
                        ),
                        range(16),
                    )
                )
            self.assertEqual(
                outcomes,
                [serve._SETUP_INIT_CANCEL_REQUESTED] * 16,
            )
            self.assertEqual(running_process.signals, [serve.signal.SIGINT])
            pid_kill.assert_not_called()
            self.assertNotIn("process", serve._setup_init_snapshot()["job"])
            self.assertIs(serve._setup_init_job["process"], running_process)

            serve._setup_init_job["state"] = "failed"
            self.assertEqual(
                serve._request_setup_init_cancel(running_id, "operator"),
                serve._SETUP_INIT_CANCEL_NOT_RUNNING,
            )
            self.assertFalse(
                serve._publish_setup_init_process("other-job", ChildProcess(4103))
            )
            self.assertIs(serve._setup_init_job["process"], running_process)
        finally:
            with serve._setup_init_lock:
                serve._setup_init_job = original_job

    def _case_web_cancel_endpoint_is_owner_scoped_and_fail_closed(self):
        import ast
        import inspect
        from functools import partial

        from freq.modules import serve
        from freq.services import setup_progress

        job_id = self._run_id("web-cancel-endpoint")

        def handler(*, command="POST", body=None, body_error=None):
            instance = serve.FreqHandler.__new__(serve.FreqHandler)
            instance.command = command
            instance._session_user = "operator"
            responses = []

            def request_body():
                if body_error is not None:
                    raise body_error
                return {"id": job_id} if body is None else body

            instance._request_body = request_body
            instance._json_response = lambda payload, status=200: responses.append(
                (status, payload)
            )
            return instance, responses

        self.assertEqual(
            serve.FreqHandler._ROUTES["/api/setup/init/cancel"],
            "_serve_setup_init_cancel",
        )
        self.assertNotIn("/api/setup/init/cancel", serve.FreqHandler._AUTH_WHITELIST)
        self.assertNotIn("/api/setup/init/cancel", serve.FreqHandler._CSRF_EXEMPT)
        csrf_handler, _responses = handler()
        self.assertTrue(csrf_handler._requires_csrf("/api/setup/init/cancel"))

        serve_tree = ast.parse(inspect.getsource(serve))
        cancel_handler = next(
            node
            for node in ast.walk(serve_tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_serve_setup_init_cancel"
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_cancel_setup_init"
                for node in ast.walk(cancel_handler)
            ),
            1,
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_request_setup_init_cancel"
                for node in ast.walk(cancel_handler)
            ),
            0,
        )
        service_tree = ast.parse(inspect.getsource(setup_progress))
        self.assertEqual(
            sum(
                isinstance(node, ast.FunctionDef)
                and node.name == "cancel_setup_init"
                for node in service_tree.body
            ),
            1,
        )
        self.assertFalse(
            any(
                isinstance(node, ast.FunctionDef)
                and node.name == "_cancel_setup_init"
                for node in serve_tree.body
            )
        )
        self.assertFalse(
            any(
                isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith("freq.modules")
                for node in ast.walk(service_tree)
            )
        )
        self.assertIsInstance(serve._cancel_setup_init, partial)
        self.assertIs(serve._cancel_setup_init.func, setup_progress.cancel_setup_init)
        self.assertIs(
            serve._cancel_setup_init.keywords["runtime"],
            serve._setup_init_cancel_admission_runtime,
        )
        self.assertTrue(setup_progress.SetupInitCancelAdmissionRuntime.__dataclass_params__.frozen)
        self.assertTrue(setup_progress.SetupInitCancelResult.__dataclass_params__.frozen)
        self.assertEqual(
            sorted(
                node.args[2].value
                for node in ast.walk(cancel_handler)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_setup_error"
                and len(node.args) >= 3
                and isinstance(node.args[2], ast.Constant)
            ),
            sorted(
                (
                    "admin_required",
                    "init_cancel_delivery_failed",
                    "init_cancel_failed",
                    "init_not_found",
                    "init_not_found",
                    "init_not_running",
                    "invalid_json",
                    "invalid_json",
                    "method_not_allowed",
                    "required_field",
                    "unknown_field",
                )
            ),
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
                and node.func.attr == "_json_response"
                for node in ast.walk(cancel_handler)
            ),
            1,
        )

        method_handler, responses = handler(command="GET")
        with mock.patch.object(serve, "_request_setup_init_cancel") as request_cancel:
            serve.FreqHandler._serve_setup_init_cancel(method_handler)
        self.assertEqual(responses[0][0], 405)
        self.assertEqual(responses[0][1]["error"]["code"], "method_not_allowed")
        request_cancel.assert_not_called()

        auth_handler, responses = handler()
        with mock.patch.object(
            serve,
            "_check_session_role",
            return_value=(None, "Authentication required"),
        ), mock.patch.object(serve, "_request_setup_init_cancel") as request_cancel:
            serve.FreqHandler._serve_setup_init_cancel(auth_handler)
        self.assertEqual(responses[0][0], 403)
        self.assertEqual(responses[0][1]["error"]["code"], "admin_required")
        request_cancel.assert_not_called()

        for invalid_handler in (
            handler(body=[])[0],
            handler(body_error=ValueError("invalid json"))[0],
        ):
            responses = []
            invalid_handler._json_response = lambda payload, status=200: responses.append(
                (status, payload)
            )
            with mock.patch.object(
                serve,
                "_check_session_role",
                return_value=("admin", None),
            ), mock.patch.object(serve, "_request_setup_init_cancel") as request_cancel:
                serve.FreqHandler._serve_setup_init_cancel(invalid_handler)
            self.assertEqual(responses[0][0], 400)
            self.assertEqual(responses[0][1]["error"]["code"], "invalid_json")
            request_cancel.assert_not_called()

        for missing_body in ({}, {"id": None}, {"id": ""}):
            missing_handler, responses = handler(body=missing_body)
            with mock.patch.object(
                serve,
                "_check_session_role",
                return_value=("admin", None),
            ), mock.patch.object(serve, "_request_setup_init_cancel") as request_cancel:
                serve.FreqHandler._serve_setup_init_cancel(missing_handler)
            self.assertEqual(responses[0][0], 400)
            self.assertEqual(responses[0][1]["error"]["code"], "required_field")
            self.assertEqual(responses[0][1]["error"]["field"], "id")
            request_cancel.assert_not_called()

        extra_handler, responses = handler(
            body={"id": job_id, "z_private": "never", "a_private": "never"}
        )
        with mock.patch.object(
            serve,
            "_check_session_role",
            return_value=("admin", None),
        ), mock.patch.object(serve, "_request_setup_init_cancel") as request_cancel:
            serve.FreqHandler._serve_setup_init_cancel(extra_handler)
        self.assertEqual(responses[0][0], 400)
        self.assertEqual(responses[0][1]["error"]["code"], "unknown_field")
        self.assertEqual(responses[0][1]["error"]["field"], "a_private")
        self.assertNotIn("never", json.dumps(responses[0][1]))
        request_cancel.assert_not_called()

        for rejected_body, expected_status, expected_code in (
            ({"id": job_id, "owner": "other-operator"}, 400, "unknown_field"),
            ({"id": "not-a-canonical-job-id"}, 404, "init_not_found"),
            ({"id": f" {job_id} "}, 404, "init_not_found"),
            ({"id": job_id.upper()}, 404, "init_not_found"),
            ({"id": int("1" * 32)}, 404, "init_not_found"),
        ):
            rejected_handler, responses = handler(body=rejected_body)
            with mock.patch.object(
                serve,
                "_check_session_role",
                return_value=("admin", None),
            ), mock.patch.object(serve, "_request_setup_init_cancel") as request_cancel:
                serve.FreqHandler._serve_setup_init_cancel(rejected_handler)
            self.assertEqual(responses[0][0], expected_status)
            self.assertEqual(responses[0][1]["error"]["code"], expected_code)
            request_cancel.assert_not_called()

        expected = (
            (serve._SETUP_INIT_CANCEL_NOT_FOUND, 404, "init_not_found"),
            (serve._SETUP_INIT_CANCEL_NOT_RUNNING, 409, "init_not_running"),
            ("invalid-outcome", 500, "init_cancel_failed"),
        )
        for outcome, status, code in expected:
            outcome_handler, responses = handler(body={"id": job_id})
            with mock.patch.object(
                serve,
                "_check_session_role",
                return_value=("admin", None),
            ), mock.patch.object(
                serve,
                "_request_setup_init_cancel",
                return_value=outcome,
            ) as request_cancel:
                serve.FreqHandler._serve_setup_init_cancel(outcome_handler)
            request_cancel.assert_called_once_with(job_id, "operator")
            self.assertEqual(responses[0][0], status)
            self.assertEqual(responses[0][1]["error"]["code"], code)

        delivery_error = OSError("private delivery detail")
        error_handler, responses = handler()
        with mock.patch.object(
            serve,
            "_check_session_role",
            return_value=("admin", None),
        ), mock.patch.object(
            serve,
            "_request_setup_init_cancel",
            side_effect=delivery_error,
        ):
            serve.FreqHandler._serve_setup_init_cancel(error_handler)
        self.assertEqual(responses[0][0], 503)
        self.assertEqual(
            responses[0][1]["error"],
            {
                "code": "init_cancel_delivery_failed",
                "message": "Init cancellation could not be delivered.",
                "retryable": True,
            },
        )
        self.assertNotIn("private delivery detail", json.dumps(responses[0][1]))

        internal_error = RuntimeError("controller contract failed")
        internal_handler, responses = handler()
        with mock.patch.object(
            serve,
            "_check_session_role",
            return_value=("admin", None),
        ), mock.patch.object(
            serve,
            "_request_setup_init_cancel",
            side_effect=internal_error,
        ) as request_cancel:
            with self.assertRaises(RuntimeError) as raised:
                serve.FreqHandler._serve_setup_init_cancel(internal_handler)
        self.assertIs(raised.exception, internal_error)
        request_cancel.assert_called_once_with(job_id, "operator")
        self.assertEqual(responses, [])

        success_handler, responses = handler()
        with mock.patch.object(
            serve,
            "_check_session_role",
            return_value=("admin", None),
        ), mock.patch.object(
            serve,
            "_request_setup_init_cancel",
            return_value=serve._SETUP_INIT_CANCEL_REQUESTED,
        ) as request_cancel:
            serve.FreqHandler._serve_setup_init_cancel(success_handler)
        request_cancel.assert_called_once_with(job_id, "operator")
        self.assertEqual(
            responses,
            [
                (
                    202,
                    {
                        "ok": True,
                        "schema": serve.ZERO_STATE_WEB_SCHEMA,
                        "cancellation": {
                            "job_id": job_id,
                            "state": serve._SETUP_INIT_CANCEL_REQUESTED,
                            "poll_after_ms": 250,
                        },
                    },
                )
            ],
        )
        self.assertNotIn("pid", json.dumps(responses[0][1]))
        self.assertNotIn("process", json.dumps(responses[0][1]))

    def _case_pre_phase_one_interruption_preserves_product_state(self):
        from freq.modules import init_cmd

        with mock.patch.object(
            init_cmd,
            "_cross_init_point_of_no_return",
            wraps=init_cmd._cross_init_point_of_no_return,
        ) as cross_boundary:
            self._run_interactive()
            self._run_headless()
        self.assertEqual(len(cross_boundary.call_args_list), 2)
        self.assertEqual(
            [call.kwargs["clear_runtime_truth"] for call in cross_boundary.call_args_list],
            [False, True],
        )

        with tempfile.TemporaryDirectory(prefix="freq-init-pre-ponr-interactive-") as root:
            cfg = self._cfg(root)
            self._seed_web_pre_ponr_mutables(cfg)
            init_cmd.INIT_MARKER = os.path.join(root, "prior-interactive-marker")
            before = self._web_pre_ponr_snapshot(cfg, init_cmd.INIT_MARKER)
            os.makedirs(cfg.conf_dir)
            marker_path = os.path.join(cfg.conf_dir, ".initialized")
            status_path = init_cmd._init_status_path(cfg)
            marker_bytes = b"accepted initialized marker\n"
            status_bytes = b'{"schema":"prior-status","state":"failed"}\n'
            with open(marker_path, "wb") as marker_file:
                marker_file.write(marker_bytes)
            with open(status_path, "wb") as status_file:
                status_file.write(status_bytes)
            interruption = KeyboardInterrupt()
            real_topology_rollback = init_cmd._rollback_init_control_topology
            real_memory_rollback = init_cmd._rollback_web_init_pre_ponr_state
            rollback_events = []

            def mutate_operator_contract(_cfg, _args):
                self._mutate_web_pre_ponr_members(cfg)
                cfg.interactive_transient = "remove"

            def restore_interactive_topology(rollback_cfg, topology):
                rollback_events.append("topology_begin")
                result = real_topology_rollback(rollback_cfg, topology)
                rollback_events.append("topology_complete")
                self.assertFalse(os.path.lexists(rollback_cfg.data_dir))
                return result

            def restore_interactive_memory(rollback_cfg, state):
                self.assertEqual(
                    rollback_events,
                    ["topology_begin", "topology_complete"],
                )
                rollback_events.append("memory_begin")
                result = real_memory_rollback(rollback_cfg, state)
                rollback_events.append("memory_complete")
                return result

            with mock.patch.object(init_cmd.os, "geteuid", return_value=0), mock.patch(
                "freq.core.personality.splash"
            ), mock.patch.object(
                init_cmd,
                "_apply_operator_vm_contract_args",
                side_effect=mutate_operator_contract,
            ), mock.patch.object(
                init_cmd,
                "_begin_init_phase",
                side_effect=interruption,
            ), mock.patch.object(
                init_cmd,
                "_rollback_init_control_topology",
                side_effect=restore_interactive_topology,
            ), mock.patch.object(
                init_cmd,
                "_rollback_web_init_pre_ponr_state",
                side_effect=restore_interactive_memory,
            ), mock.patch.object(
                init_cmd, "_phase_welcome"
            ) as welcome, mock.patch.object(
                init_cmd, "_cross_init_point_of_no_return"
            ) as cross_boundary:
                with self.assertRaises(KeyboardInterrupt) as raised:
                    init_cmd.cmd_init(cfg, None, self._args())
            self.assertIs(raised.exception, interruption)
            welcome.assert_not_called()
            cross_boundary.assert_not_called()
            self.assertEqual(
                rollback_events,
                [
                    "topology_begin",
                    "topology_complete",
                    "memory_begin",
                    "memory_complete",
                ],
            )
            self._assert_web_pre_ponr_restored(cfg, before)
            self.assertFalse(os.path.lexists(cfg.data_dir))
            with open(marker_path, "rb") as marker_file:
                self.assertEqual(marker_file.read(), marker_bytes)
            with open(status_path, "rb") as status_file:
                self.assertEqual(status_file.read(), status_bytes)

        with tempfile.TemporaryDirectory(
            prefix="freq-init-boundary-entry-interruption-"
        ) as root:
            cfg = self._cfg(root)
            self._seed_web_pre_ponr_mutables(cfg)
            init_cmd.INIT_MARKER = os.path.join(root, "prior-boundary-marker")
            before = self._web_pre_ponr_snapshot(cfg, init_cmd.INIT_MARKER)
            os.makedirs(cfg.conf_dir)
            marker_path = os.path.join(cfg.conf_dir, ".initialized")
            status_path = init_cmd._init_status_path(cfg)
            marker_bytes = b"accepted initialized marker\n"
            status_bytes = b'{"schema":"prior-status","state":"failed"}\n'
            with open(marker_path, "wb") as marker_file:
                marker_file.write(marker_bytes)
            with open(status_path, "wb") as status_file:
                status_file.write(status_bytes)
            interruption = KeyboardInterrupt()
            real_control_rollback = init_cmd._rollback_cancelled_init_control
            real_topology_rollback = init_cmd._rollback_init_control_topology
            real_memory_rollback = init_cmd._rollback_web_init_pre_ponr_state
            rollback_events = []
            rollback_run_ids = []

            def mutate_operator_contract(_cfg, _args):
                self._mutate_web_pre_ponr_members(cfg)
                cfg.interactive_transient = "remove"

            def restore_interactive_control(rollback_cfg, run_id):
                rollback_run_ids.append(run_id)
                rollback_events.append("control_begin")
                result = real_control_rollback(rollback_cfg, run_id)
                rollback_events.append("control_complete")
                return result

            def restore_interactive_topology(rollback_cfg, topology):
                self.assertEqual(len(rollback_run_ids), 1)
                rollback_events.append("topology_begin")
                result = real_topology_rollback(rollback_cfg, topology)
                rollback_events.append("topology_complete")
                self.assertFalse(os.path.lexists(rollback_cfg.data_dir))
                return result

            def restore_interactive_memory(rollback_cfg, state):
                self.assertEqual(
                    rollback_events,
                    [
                        "control_begin",
                        "control_complete",
                        "topology_begin",
                        "topology_complete",
                    ],
                )
                rollback_events.append("memory_begin")
                result = real_memory_rollback(rollback_cfg, state)
                rollback_events.append("memory_complete")
                return result

            with mock.patch.object(init_cmd.os, "geteuid", return_value=0), mock.patch(
                "freq.core.personality.splash"
            ), mock.patch.object(
                init_cmd,
                "_apply_operator_vm_contract_args",
                side_effect=mutate_operator_contract,
            ), mock.patch.object(
                init_cmd,
                "_begin_init_phase",
                return_value=object(),
            ), mock.patch.object(
                init_cmd,
                "_rollback_cancelled_init_control",
                side_effect=restore_interactive_control,
            ), mock.patch.object(
                init_cmd,
                "_rollback_init_control_topology",
                side_effect=restore_interactive_topology,
            ), mock.patch.object(
                init_cmd,
                "_rollback_web_init_pre_ponr_state",
                side_effect=restore_interactive_memory,
            ), mock.patch.object(
                init_cmd, "_phase_welcome"
            ) as welcome, mock.patch.object(
                init_cmd,
                "_cross_init_point_of_no_return",
                side_effect=interruption,
            ) as cross_boundary:
                with self.assertRaises(KeyboardInterrupt) as raised:
                    init_cmd.cmd_init(cfg, None, self._args())
            self.assertIs(raised.exception, interruption)
            welcome.assert_not_called()
            cross_boundary.assert_called_once()
            self.assertFalse(cross_boundary.call_args.kwargs["clear_runtime_truth"])
            self.assertEqual(
                rollback_events,
                [
                    "control_begin",
                    "control_complete",
                    "topology_begin",
                    "topology_complete",
                    "memory_begin",
                    "memory_complete",
                ],
            )
            self._assert_web_pre_ponr_restored(cfg, before)
            self.assertFalse(os.path.lexists(cfg.data_dir))
            with open(marker_path, "rb") as marker_file:
                self.assertEqual(marker_file.read(), marker_bytes)
            with open(status_path, "rb") as status_file:
                self.assertEqual(status_file.read(), status_bytes)

        with tempfile.TemporaryDirectory(
            prefix="freq-init-post-ponr-interruption-"
        ) as root:
            cfg = self._cfg(root)
            self._seed_web_pre_ponr_mutables(cfg)
            init_cmd.INIT_MARKER = os.path.join(root, "prior-post-ponr-marker")
            before = self._web_pre_ponr_snapshot(cfg, init_cmd.INIT_MARKER)
            interruption = KeyboardInterrupt()
            real_cross_boundary = init_cmd._cross_init_point_of_no_return

            def mutate_operator_contract(_cfg, _args):
                self._mutate_web_pre_ponr_members(cfg)
                cfg.interactive_transient = "retain"

            def interrupt_after_boundary(*call_args, **call_kwargs):
                real_cross_boundary(*call_args, **call_kwargs)
                raise interruption

            with mock.patch.object(init_cmd.os, "geteuid", return_value=0), mock.patch(
                "freq.core.personality.splash"
            ), mock.patch.object(
                init_cmd,
                "_apply_operator_vm_contract_args",
                side_effect=mutate_operator_contract,
            ), mock.patch.object(
                init_cmd,
                "_begin_init_phase",
                return_value=object(),
            ), mock.patch.object(
                init_cmd,
                "_rollback_cancelled_init_control",
            ) as rollback_control, mock.patch.object(
                init_cmd,
                "_rollback_init_pre_ponr_state",
            ) as rollback_state, mock.patch.object(
                init_cmd, "_phase_welcome"
            ) as welcome, mock.patch.object(
                init_cmd,
                "_cross_init_point_of_no_return",
                side_effect=interrupt_after_boundary,
            ) as cross_boundary:
                with self.assertRaises(KeyboardInterrupt) as raised:
                    init_cmd.cmd_init(cfg, None, self._args())
            self.assertIs(raised.exception, interruption)
            welcome.assert_not_called()
            cross_boundary.assert_called_once()
            rollback_control.assert_not_called()
            rollback_state.assert_not_called()
            context = cross_boundary.call_args.args[1]
            self.assertIs(
                init_cmd._request_init_cancel(cfg, context["_init_run_id"]),
                init_cmd._InitControlState.POINT_OF_NO_RETURN,
            )
            self.assertNotEqual(vars(cfg), before[1])
            self.assertEqual(cfg.interactive_transient, "retain")
            self.assertTrue(os.path.lexists(cfg.data_dir))

        with tempfile.TemporaryDirectory(
            prefix="freq-init-pre-ponr-interactive-cleanup-failure-"
        ) as root:
            cfg = self._cfg(root)
            topology_error = OSError("interactive topology cleanup failed")
            interruption = KeyboardInterrupt()
            with mock.patch.object(init_cmd.os, "geteuid", return_value=0), mock.patch(
                "freq.core.personality.splash"
            ), mock.patch.object(
                init_cmd,
                "_apply_operator_vm_contract_args",
                side_effect=interruption,
            ), mock.patch.object(
                init_cmd,
                "_begin_init_phase",
            ) as begin_phase, mock.patch.object(
                init_cmd,
                "_rollback_init_control_topology",
                side_effect=topology_error,
            ) as rollback_topology, mock.patch.object(
                init_cmd,
                "_rollback_web_init_pre_ponr_state",
            ) as rollback_memory, mock.patch.object(
                init_cmd, "_cross_init_point_of_no_return"
            ) as cross_boundary:
                with self.assertRaises(OSError) as raised:
                    init_cmd.cmd_init(cfg, None, self._args())
            self.assertIs(raised.exception, topology_error)
            begin_phase.assert_not_called()
            rollback_topology.assert_called_once()
            rollback_memory.assert_not_called()
            cross_boundary.assert_not_called()

        with tempfile.TemporaryDirectory(
            prefix="freq-init-pre-control-headless-"
        ) as root:
            cfg = self._cfg(root)
            self._seed_web_pre_ponr_mutables(cfg)
            init_cmd.INIT_MARKER = os.path.join(root, "prior-pre-control-marker")
            before = self._web_pre_ponr_snapshot(cfg, init_cmd.INIT_MARKER)
            os.makedirs(cfg.conf_dir)
            bootstrap_key = os.path.join(root, "bootstrap-key")
            password_file = os.path.join(root, "service-password")
            dashboard_password_file = os.path.join(root, "dashboard-password")
            for path, value in (
                (bootstrap_key, "key"),
                (password_file, "service-password"),
                (dashboard_password_file, "dashboard-password"),
            ):
                with open(path, "w", encoding="utf-8") as secret_file:
                    secret_file.write(value)
            args = self._args(
                headless=True,
                bootstrap_key=bootstrap_key,
                bootstrap_user="root",
                bootstrap_password_file=None,
                password_file=password_file,
                dashboard_user="operator",
                dashboard_password_file=dashboard_password_file,
                device_credentials=None,
                device_password_file=None,
                device_user="root",
                service_account="freq-admin",
                hosts_file=None,
            )
            interruption = KeyboardInterrupt()
            real_topology_rollback = init_cmd._rollback_init_control_topology
            real_memory_rollback = init_cmd._rollback_web_init_pre_ponr_state
            rollback_events = []

            def mutate_operator_contract(_cfg, _args):
                self._mutate_web_pre_ponr_members(cfg)
                cfg.headless_transient = "remove"

            def restore_headless_topology(rollback_cfg, topology):
                rollback_events.append("topology_begin")
                result = real_topology_rollback(rollback_cfg, topology)
                rollback_events.append("topology_complete")
                return result

            def restore_headless_memory(rollback_cfg, state):
                self.assertEqual(
                    rollback_events,
                    ["topology_begin", "topology_complete"],
                )
                rollback_events.append("memory_begin")
                result = real_memory_rollback(rollback_cfg, state)
                rollback_events.append("memory_complete")
                return result

            with mock.patch.dict(
                os.environ,
                {"FREQ_WEB_INIT": "0"},
            ), mock.patch.object(
                init_cmd.os, "geteuid", return_value=0
            ), mock.patch.object(
                init_cmd,
                "_apply_operator_vm_contract_args",
                side_effect=mutate_operator_contract,
            ), mock.patch.object(
                init_cmd,
                "_load_device_credentials",
                side_effect=interruption,
            ), mock.patch.object(
                init_cmd,
                "_request_init_cancel",
            ) as request_cancel, mock.patch.object(
                init_cmd,
                "_rollback_cancelled_init_control",
            ) as rollback_control, mock.patch.object(
                init_cmd,
                "_rollback_init_control_topology",
                side_effect=restore_headless_topology,
            ), mock.patch.object(
                init_cmd,
                "_rollback_web_init_pre_ponr_state",
                side_effect=restore_headless_memory,
            ), mock.patch.object(
                init_cmd, "_begin_init_phase"
            ) as begin_phase, mock.patch.object(
                init_cmd, "_cross_init_point_of_no_return"
            ) as cross_boundary:
                with self.assertRaises(KeyboardInterrupt) as raised:
                    init_cmd.cmd_init(cfg, None, args)
            self.assertIs(raised.exception, interruption)
            request_cancel.assert_not_called()
            rollback_control.assert_not_called()
            begin_phase.assert_not_called()
            cross_boundary.assert_not_called()
            self.assertEqual(
                rollback_events,
                [
                    "topology_begin",
                    "topology_complete",
                    "memory_begin",
                    "memory_complete",
                ],
            )
            self._assert_web_pre_ponr_restored(cfg, before)
            self.assertFalse(os.path.lexists(cfg.data_dir))

        with tempfile.TemporaryDirectory(prefix="freq-init-pre-ponr-headless-") as root:
            cfg = self._cfg(root)
            self._seed_web_pre_ponr_mutables(cfg)
            init_cmd.INIT_MARKER = os.path.join(root, "prior-headless-marker")
            before = self._web_pre_ponr_snapshot(cfg, init_cmd.INIT_MARKER)
            os.makedirs(cfg.conf_dir)
            marker_path = os.path.join(cfg.conf_dir, ".initialized")
            status_path = init_cmd._init_status_path(cfg)
            bootstrap_key = os.path.join(root, "bootstrap-key")
            password_file = os.path.join(root, "service-password")
            dashboard_password_file = os.path.join(root, "dashboard-password")
            for path, value in (
                (bootstrap_key, "key"),
                (password_file, "service-password"),
                (dashboard_password_file, "dashboard-password"),
            ):
                with open(path, "w", encoding="utf-8") as secret_file:
                    secret_file.write(value)
            marker_bytes = b"accepted initialized marker\n"
            status_bytes = b'{"schema":"prior-status","state":"failed"}\n'
            with open(marker_path, "wb") as marker_file:
                marker_file.write(marker_bytes)
            with open(status_path, "wb") as status_file:
                status_file.write(status_bytes)
            args = self._args(
                headless=True,
                bootstrap_key=bootstrap_key,
                bootstrap_user="root",
                bootstrap_password_file=None,
                password_file=password_file,
                dashboard_user="operator",
                dashboard_password_file=dashboard_password_file,
                device_credentials=None,
                device_password_file=None,
                device_user="root",
                service_account="freq-admin",
                hosts_file=None,
            )
            interruption = KeyboardInterrupt()
            real_control_rollback = init_cmd._rollback_cancelled_init_control
            real_topology_rollback = init_cmd._rollback_init_control_topology
            real_memory_rollback = init_cmd._rollback_web_init_pre_ponr_state
            rollback_events = []
            rollback_run_ids = []

            def mutate_operator_contract(_cfg, _args):
                self._mutate_web_pre_ponr_members(cfg)
                cfg.headless_transient = "remove"

            def restore_headless_control(rollback_cfg, run_id):
                rollback_run_ids.append(run_id)
                rollback_events.append("control_begin")
                result = real_control_rollback(rollback_cfg, run_id)
                rollback_events.append("control_complete")
                return result

            def restore_headless_topology(rollback_cfg, topology):
                self.assertEqual(len(rollback_run_ids), 1)
                rollback_events.append("topology_begin")
                result = real_topology_rollback(rollback_cfg, topology)
                rollback_events.append("topology_complete")
                self.assertFalse(os.path.lexists(rollback_cfg.data_dir))
                return result

            def restore_headless_memory(rollback_cfg, state):
                self.assertEqual(
                    rollback_events,
                    [
                        "control_begin",
                        "control_complete",
                        "topology_begin",
                        "topology_complete",
                    ],
                )
                rollback_events.append("memory_begin")
                result = real_memory_rollback(rollback_cfg, state)
                rollback_events.append("memory_complete")
                return result

            with mock.patch.object(init_cmd.os, "geteuid", return_value=0), mock.patch.object(
                init_cmd,
                "_apply_operator_vm_contract_args",
                side_effect=mutate_operator_contract,
            ), mock.patch.object(
                init_cmd, "_load_device_credentials", return_value={}
            ), mock.patch.object(
                init_cmd, "_validate_device_scoped_service_password", return_value=True
            ), mock.patch.object(
                init_cmd, "_validate_truenas_deployment_credentials", return_value=True
            ), mock.patch.object(
                init_cmd, "_validate_device_credential_scopes", return_value=True
            ), mock.patch.object(
                init_cmd, "_validate_username", return_value=True
            ), mock.patch.object(
                init_cmd, "_validate_service_account_choice", return_value=True
            ), mock.patch.object(
                init_cmd, "_headless_phase2_inputs_match_current_config", return_value=False
            ), mock.patch.object(
                init_cmd, "_begin_init_phase", side_effect=interruption
            ), mock.patch.object(
                init_cmd,
                "_rollback_cancelled_init_control",
                side_effect=restore_headless_control,
            ), mock.patch.object(
                init_cmd,
                "_rollback_init_control_topology",
                side_effect=restore_headless_topology,
            ), mock.patch.object(
                init_cmd,
                "_rollback_web_init_pre_ponr_state",
                side_effect=restore_headless_memory,
            ), mock.patch.object(
                init_cmd, "_phase_welcome"
            ) as welcome, mock.patch.object(
                init_cmd, "_clear_generated_runtime_truth_state"
            ) as clear_runtime_truth, mock.patch.object(
                init_cmd, "_cross_init_point_of_no_return", wraps=init_cmd._cross_init_point_of_no_return
            ) as cross_boundary:
                with self.assertRaises(KeyboardInterrupt) as raised:
                    init_cmd.cmd_init(cfg, None, args)
            self.assertIs(raised.exception, interruption)
            welcome.assert_not_called()
            clear_runtime_truth.assert_not_called()
            cross_boundary.assert_not_called()
            self.assertEqual(
                rollback_events,
                [
                    "control_begin",
                    "control_complete",
                    "topology_begin",
                    "topology_complete",
                    "memory_begin",
                    "memory_complete",
                ],
            )
            self._assert_web_pre_ponr_restored(cfg, before)
            self.assertFalse(os.path.lexists(cfg.data_dir))
            with open(marker_path, "rb") as marker_file:
                self.assertEqual(marker_file.read(), marker_bytes)
            with open(status_path, "rb") as status_file:
                self.assertEqual(status_file.read(), status_bytes)

        with tempfile.TemporaryDirectory(
            prefix="freq-init-post-ponr-headless-"
        ) as root:
            cfg = self._cfg(root)
            self._seed_web_pre_ponr_mutables(cfg)
            init_cmd.INIT_MARKER = os.path.join(root, "prior-headless-ponr-marker")
            before = self._web_pre_ponr_snapshot(cfg, init_cmd.INIT_MARKER)
            os.makedirs(cfg.conf_dir)
            bootstrap_key = os.path.join(root, "bootstrap-key")
            password_file = os.path.join(root, "service-password")
            dashboard_password_file = os.path.join(root, "dashboard-password")
            for path, value in (
                (bootstrap_key, "key"),
                (password_file, "service-password"),
                (dashboard_password_file, "dashboard-password"),
            ):
                with open(path, "w", encoding="utf-8") as secret_file:
                    secret_file.write(value)
            args = self._args(
                headless=True,
                bootstrap_key=bootstrap_key,
                bootstrap_user="root",
                bootstrap_password_file=None,
                password_file=password_file,
                dashboard_user="operator",
                dashboard_password_file=dashboard_password_file,
                device_credentials=None,
                device_password_file=None,
                device_user="root",
                service_account="freq-admin",
                hosts_file=None,
            )
            interruption = KeyboardInterrupt()
            real_cross_boundary = init_cmd._cross_init_point_of_no_return

            def mutate_operator_contract(_cfg, _args):
                self._mutate_web_pre_ponr_members(cfg)
                cfg.headless_transient = "retain"

            def interrupt_after_boundary(*call_args, **call_kwargs):
                real_cross_boundary(*call_args, **call_kwargs)
                raise interruption

            with mock.patch.dict(
                os.environ,
                {"FREQ_WEB_INIT": "0"},
            ), mock.patch.object(
                init_cmd.os, "geteuid", return_value=0
            ), mock.patch.object(
                init_cmd,
                "_apply_operator_vm_contract_args",
                side_effect=mutate_operator_contract,
            ), mock.patch.object(
                init_cmd, "_load_device_credentials", return_value={}
            ), mock.patch.object(
                init_cmd, "_validate_device_scoped_service_password", return_value=True
            ), mock.patch.object(
                init_cmd, "_validate_truenas_deployment_credentials", return_value=True
            ), mock.patch.object(
                init_cmd, "_validate_device_credential_scopes", return_value=True
            ), mock.patch.object(
                init_cmd, "_validate_username", return_value=True
            ), mock.patch.object(
                init_cmd, "_validate_service_account_choice", return_value=True
            ), mock.patch.object(
                init_cmd, "_headless_phase2_inputs_match_current_config", return_value=False
            ), mock.patch.object(
                init_cmd, "_begin_init_phase", return_value=object()
            ), mock.patch.object(
                init_cmd, "_rollback_cancelled_init_control"
            ) as rollback_control, mock.patch.object(
                init_cmd, "_rollback_init_pre_ponr_state"
            ) as rollback_state, mock.patch.object(
                init_cmd, "_phase_welcome"
            ) as welcome, mock.patch.object(
                init_cmd,
                "_cross_init_point_of_no_return",
                side_effect=interrupt_after_boundary,
            ) as cross_boundary:
                with self.assertRaises(KeyboardInterrupt) as raised:
                    init_cmd.cmd_init(cfg, None, args)
            self.assertIs(raised.exception, interruption)
            welcome.assert_not_called()
            cross_boundary.assert_called_once()
            rollback_control.assert_not_called()
            rollback_state.assert_not_called()
            context = cross_boundary.call_args.args[1]
            self.assertIs(
                init_cmd._request_init_cancel(cfg, context["_init_run_id"]),
                init_cmd._InitControlState.POINT_OF_NO_RETURN,
            )
            self.assertNotEqual(vars(cfg), before[1])
            self.assertEqual(cfg.headless_transient, "retain")
            self.assertTrue(os.path.lexists(cfg.data_dir))

    def _case_interruption_artifact_preserves_exact_running_and_failed_truth(self):
        from freq.modules import init_cmd

        expected_keys = {
            "checked_at",
            "current_phase",
            "current_phase_key",
            "failed_checks",
            "initialized",
            "mode",
            "phase_results",
            "reason",
            "run_id",
            "schema",
            "state",
        }
        prefix = tuple(PhaseResult.succeeded(identity) for identity in INIT_PHASES[:2])
        serialized_prefix = [
            {
                "number": result.identity.number,
                "key": result.identity.key,
                "title": result.identity.title,
                "status": "succeeded",
                "error": None,
            }
            for result in prefix
        ]

        with tempfile.TemporaryDirectory(prefix="freq-init-interrupted-") as root:
            cfg = self._cfg(root)
            init_cmd._persist_init_phase_results(
                cfg,
                prefix,
                run_id=self._run_id("interrupted-run-id"),
                mode="headless",
            )
            status_path = init_cmd._init_status_path(cfg)
            with open(status_path, "rb") as status_file:
                before_reload = status_file.read()
            before_fingerprint = hashlib.sha256(before_reload).hexdigest()

            running = init_cmd._load_init_status(cfg)

            with open(status_path, "rb") as status_file:
                after_reload = status_file.read()
            self.assertEqual(after_reload, before_reload)
            self.assertEqual(hashlib.sha256(after_reload).hexdigest(), before_fingerprint)
            self.assertEqual(set(running), expected_keys)
            self.assertIsInstance(running["checked_at"], str)
            self.assertTrue(running["checked_at"])
            self.assertEqual(
                {key: value for key, value in running.items() if key != "checked_at"},
                {
                    "current_phase": 2,
                    "current_phase_key": "configure",
                    "failed_checks": [],
                    "initialized": False,
                    "mode": "headless",
                    "phase_results": serialized_prefix,
                    "reason": "",
                    "run_id": self._run_id("interrupted-run-id"),
                    "schema": "pve-freq-init-status-v1",
                    "state": "running",
                },
            )

            error = "service account setup interrupted"
            failed_result = PhaseResult.failed(INIT_PHASES[2], error)
            init_cmd._persist_init_phase_results(
                cfg,
                (*prefix, failed_result),
                run_id=self._run_id("interrupted-run-id"),
                mode="headless",
            )
            failed = init_cmd._load_init_status(cfg)
            self.assertEqual(set(failed), expected_keys)
            self.assertEqual(
                {key: value for key, value in failed.items() if key != "checked_at"},
                {
                    "current_phase": 3,
                    "current_phase_key": "service_account",
                    "failed_checks": [error],
                    "initialized": False,
                    "mode": "headless",
                    "phase_results": [
                        *serialized_prefix,
                        {
                            "number": 3,
                            "key": "service_account",
                            "title": "Service Account Setup",
                            "status": "failed",
                            "error": error,
                        },
                    ],
                    "reason": error,
                    "run_id": self._run_id("interrupted-run-id"),
                    "schema": "pve-freq-init-status-v1",
                    "state": "failed",
                },
            )

    def _case_resume_candidate_parser_fails_closed(self):
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory(prefix="freq-init-resume-candidate-") as root:
            cfg = self._cfg(root)
            candidate_run_id = "a" * 32
            prefix = tuple(PhaseResult.succeeded(identity) for identity in INIT_PHASES[:2])
            init_cmd._persist_init_phase_results(
                cfg,
                prefix,
                run_id=candidate_run_id,
                mode="headless",
            )
            status_path = init_cmd._init_status_path(cfg)
            with open(status_path, "rb") as status_file:
                before = status_file.read()

            candidate = init_cmd._parse_init_resume_candidate(cfg, mode="headless")

            with open(status_path, "rb") as status_file:
                self.assertEqual(status_file.read(), before)
            self.assertIsNotNone(candidate)
            run_id, completed = candidate
            self.assertEqual(run_id, candidate_run_id)
            self.assertEqual(len(completed), 2)
            self.assertTrue(
                all(
                    result.identity is expected
                    for result, expected in zip(completed, INIT_PHASES[:2], strict=True)
                )
            )
            self.assertTrue(all(result.status is PhaseStatus.SUCCEEDED for result in completed))

            canonical = init_cmd._load_init_status(cfg)

            def changed(mutator):
                payload = json.loads(json.dumps(canonical))
                mutator(payload)
                return payload

            corruptions = (
                changed(lambda payload: payload.update(schema="wrong")),
                changed(
                    lambda payload: payload.update(
                        checked_at=f" {payload['checked_at']} "
                    )
                ),
                changed(lambda payload: payload.update(mode="interactive")),
                changed(lambda payload: payload.update(run_id="")),
                changed(lambda payload: payload.update(run_id=" padded-run-id ")),
                changed(lambda payload: payload.update(run_id="A" * 32)),
                changed(lambda payload: payload.update(run_id="a" * 31)),
                changed(lambda payload: payload.update(run_id="g" * 32)),
                changed(lambda payload: payload.update(state="succeeded")),
                changed(lambda payload: payload.update(initialized=True)),
                changed(lambda payload: payload.update(failed_checks=["failure"])),
                changed(lambda payload: payload.update(reason="failure")),
                changed(lambda payload: payload.update(current_phase=3)),
                changed(lambda payload: payload.update(current_phase=True)),
                changed(lambda payload: payload.update(current_phase_key="service_account")),
                changed(lambda payload: payload.update(undeclared="poison")),
                changed(lambda payload: payload["phase_results"].clear()),
                changed(lambda payload: payload["phase_results"][0].update(number=True)),
                changed(lambda payload: payload["phase_results"][0].update(status="failed")),
                changed(lambda payload: payload["phase_results"][0].update(error="failure")),
                changed(lambda payload: payload["phase_results"][1].update(number=3)),
                changed(lambda payload: payload["phase_results"][1].update(title="wrong")),
                changed(lambda payload: payload["phase_results"][1].update(extra="poison")),
            )
            for payload in corruptions:
                with self.subTest(payload=payload), mock.patch.object(
                    init_cmd,
                    "_load_init_status",
                    return_value=payload,
                ):
                    self.assertIsNone(
                        init_cmd._parse_init_resume_candidate(cfg, mode="headless")
                    )

            failed = PhaseResult.failed(INIT_PHASES[2], "interrupted failure")
            init_cmd._persist_init_phase_results(
                cfg,
                (*prefix, failed),
                run_id=candidate_run_id,
                mode="headless",
            )
            self.assertIsNone(init_cmd._parse_init_resume_candidate(cfg, mode="headless"))
            with self.assertRaisesRegex(ValueError, "interactive or headless"):
                init_cmd._parse_init_resume_candidate(cfg, mode="web")

    def _case_phase_one_resume_reuses_exact_run_and_skips_only_prerequisites(self):
        from freq.modules import init_cmd

        interactive_prefix = (PhaseResult.succeeded(INIT_PHASES[0]),)
        headless_prefix = (PhaseResult.succeeded(INIT_PHASES[0]),)
        with mock.patch.object(
            init_cmd,
            "_parse_init_resume_candidate",
            side_effect=(
                (self._run_id("interactive-resume-id"), interactive_prefix),
                (self._run_id("headless-resume-id"), headless_prefix),
            ),
        ) as parse_candidate, mock.patch.object(
            init_cmd,
            "_start_init_run",
            wraps=init_cmd._start_init_run,
        ) as start_run, mock.patch.object(
            init_cmd,
            "_persist_init_phase_results",
            wraps=init_cmd._persist_init_phase_results,
        ) as persist_results:
            interactive = self._run_interactive()
            headless = self._run_headless(catalog_override=INIT_PHASES)

        self.assertEqual(
            parse_candidate.call_args_list,
            [mock.call(mock.ANY, mode="interactive"), mock.call(mock.ANY, mode="headless")],
        )
        start_run.assert_not_called()
        self.assertEqual(
            [call.kwargs["run_id"] for call in persist_results.call_args_list],
            [self._run_id("interactive-resume-id")] * (len(INIT_PHASES) - 1)
            + [self._run_id("headless-resume-id")] * (len(INIT_PHASES) - 1),
        )
        self.assertEqual(
            [call.kwargs["mode"] for call in persist_results.call_args_list],
            ["interactive"] * (len(INIT_PHASES) - 1)
            + ["headless"] * (len(INIT_PHASES) - 1),
        )

        interactive_rc, interactive_headers, interactive_calls, _, _, interactive_results = (
            interactive
        )
        self.assertEqual(interactive_rc, 0)
        self.assertEqual(
            [number for number, _total, _title in interactive_headers],
            list(range(2, len(INIT_PHASES) + 1)),
        )
        self.assertEqual(
            tuple(interactive_calls),
            tuple(call for call in INTERACTIVE_SUCCESS_CALLS if call != "prerequisites"),
        )
        self._assert_result_ledger(
            interactive_results,
            len(INIT_PHASES),
            expected_identities=INIT_PHASES,
        )

        (
            headless_rc,
            headless_headers,
            headless_calls,
            _headless_started,
            _headless_catalog_calls,
            _headless_deploy_count,
            headless_catalog,
            headless_results,
        ) = headless
        self.assertEqual(headless_rc, 0)
        self.assertEqual(
            [number for number, _total, _title in headless_headers],
            list(range(2, len(headless_catalog) + 1)),
        )
        self.assertEqual(
            tuple(headless_calls),
            tuple(call for call in HEADLESS_SUCCESS_CALLS if call != "prerequisites"),
        )
        self._assert_result_ledger(
            headless_results,
            len(headless_catalog),
            expected_identities=headless_catalog,
        )

        with tempfile.TemporaryDirectory(prefix="freq-init-resume-boundary-") as root:
            cfg = self._cfg(root)
            longer_prefix = tuple(
                PhaseResult.succeeded(identity) for identity in INIT_PHASES[:2]
            )
            with mock.patch.object(
                init_cmd,
                "_parse_init_resume_candidate",
                return_value=("unsupported-resume-id", longer_prefix),
            ), mock.patch.object(
                init_cmd,
                "_start_init_run",
                return_value={
                    "_init_run_id": self._run_id("fresh-fallback-id"),
                    "_init_mode": "headless",
                },
            ) as fresh_start:
                fallback = init_cmd._resume_or_start_init_run(cfg, mode="headless")
            self.assertEqual(
                fallback,
                {
                    "_init_run_id": self._run_id("fresh-fallback-id"),
                    "_init_mode": "headless",
                },
            )
            fresh_start.assert_called_once_with(cfg, mode="headless")

    def _case_two_phase_resume_candidate_fresh_falls_back(self):
        from freq.modules import init_cmd

        completed = tuple(
            PhaseResult.succeeded(identity) for identity in INIT_PHASES[:2]
        )
        for mode in ("interactive", "headless"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(
                prefix=f"freq-init-two-phase-fallback-{mode}-"
            ) as root:
                cfg = self._cfg(root)
                init_cmd._persist_init_phase_results(
                    cfg,
                    completed,
                    run_id=self._run_id(f"prior-{mode}-run-id"),
                    mode=mode,
                )
                status_path = init_cmd._init_status_path(cfg)
                self.assertTrue(os.path.isfile(status_path))
                with open(status_path, "rb") as status_file:
                    prior_status = status_file.read()

                with mock.patch.object(
                    init_cmd.secrets,
                    "token_hex",
                    return_value=self._run_id(f"fresh-{mode}-run-id"),
                ):
                    fresh = init_cmd._resume_or_start_init_run(cfg, mode=mode)

                self.assertEqual(
                    fresh,
                    {
                        "_init_run_id": self._run_id(f"fresh-{mode}-run-id"),
                        "_init_mode": mode,
                    },
                )
                with open(status_path, "rb") as status_file:
                    self.assertEqual(status_file.read(), prior_status)

    def _case_phase_two_resume_provenance_factory_is_exact_and_fail_closed(self):
        from freq.modules import init_cmd

        freq_toml = b'[pve]\nnodes = ["10.0.0.2"]\n'
        vlans_toml = b'[vlan.vlan10]\nid = 10\n'

        def expected_fingerprint(vlans):
            digest = hashlib.sha256()
            for filename, data in (("freq.toml", freq_toml), ("vlans.toml", vlans)):
                digest.update(filename.encode("utf-8"))
                digest.update(b"\0")
                if data is None:
                    digest.update(b"missing\0")
                else:
                    digest.update(str(len(data)).encode("ascii"))
                    digest.update(b"\0")
                    digest.update(data)
            return digest.hexdigest()

        with tempfile.TemporaryDirectory(prefix="freq-init-phase2-provenance-") as root:
            cfg = self._cfg(root)
            os.makedirs(cfg.conf_dir)
            freq_path = os.path.join(cfg.conf_dir, "freq.toml")
            vlans_path = os.path.join(cfg.conf_dir, "vlans.toml")
            with open(freq_path, "wb") as config_file:
                config_file.write(freq_toml)
            with open(vlans_path, "wb") as config_file:
                config_file.write(vlans_toml)

            key_context = {
                "_init_mode": "headless",
                "bootstrap_user": "freq-bootstrap",
                "bootstrap_key": "/run/freq/bootstrap-key",
                "bootstrap_pass": "",
            }
            key_provenance = init_cmd._build_init_phase2_resume_provenance(
                cfg, key_context
            )
            self.assertEqual(
                key_provenance.to_payload(),
                {
                    "schema": "pve-freq-init-phase2-provenance-v1",
                    "config_fingerprint": expected_fingerprint(vlans_toml),
                    "bootstrap_user": "freq-bootstrap",
                    "bootstrap_auth": "key",
                    "mode": "headless",
                    "version": 1,
                },
            )

            password_sentinel = "must-never-enter-provenance"
            password_provenance = init_cmd._build_init_phase2_resume_provenance(
                cfg,
                {
                    **key_context,
                    "bootstrap_key": "",
                    "bootstrap_pass": password_sentinel,
                },
            )
            self.assertEqual(password_provenance.bootstrap_auth, "password")
            self.assertEqual(
                password_provenance.config_fingerprint,
                key_provenance.config_fingerprint,
            )
            self.assertNotIn(password_sentinel, json.dumps(password_provenance.to_payload()))

            os.unlink(vlans_path)
            missing_vlans = init_cmd._build_init_phase2_resume_provenance(cfg, key_context)
            self.assertEqual(
                missing_vlans.config_fingerprint,
                expected_fingerprint(None),
            )
            self.assertNotEqual(
                missing_vlans.config_fingerprint,
                key_provenance.config_fingerprint,
            )

            with open(vlans_path, "wb"):
                pass
            empty_vlans = init_cmd._build_init_phase2_resume_provenance(cfg, key_context)
            self.assertEqual(
                empty_vlans.config_fingerprint,
                expected_fingerprint(b""),
            )
            self.assertNotEqual(
                empty_vlans.config_fingerprint,
                missing_vlans.config_fingerprint,
            )

            invalid_contexts = (
                {**key_context, "_init_mode": "interactive"},
                {**key_context, "bootstrap_key": "", "bootstrap_pass": ""},
                {**key_context, "bootstrap_pass": "also-present"},
                {**key_context, "bootstrap_user": " padded "},
            )
            for invalid_context in invalid_contexts:
                self.assertIsNone(
                    init_cmd._build_init_phase2_resume_provenance(cfg, invalid_context)
                )

            os.unlink(freq_path)
            self.assertIsNone(
                init_cmd._build_init_phase2_resume_provenance(cfg, key_context)
            )
            with self.assertRaisesRegex(TypeError, "context must be a dict"):
                init_cmd._build_init_phase2_resume_provenance(cfg, None)

    def _case_phase_two_provenance_persistence_is_exact_and_not_reusable_by_v1(self):
        from freq.modules import init_cmd

        password_sentinel = "must-not-persist-in-phase2-provenance"
        with tempfile.TemporaryDirectory(prefix="freq-init-phase2-persistence-") as root:
            cfg = self._cfg(root)
            os.makedirs(cfg.conf_dir)
            with open(os.path.join(cfg.conf_dir, "freq.toml"), "wb") as config_file:
                config_file.write(b'[pve]\nnodes = ["10.0.0.2"]\n')

            provenance = init_cmd._build_init_phase2_resume_provenance(
                cfg,
                {
                    "_init_mode": "headless",
                    "bootstrap_user": "freq-bootstrap",
                    "bootstrap_key": "",
                    "bootstrap_pass": password_sentinel,
                },
            )
            prefix = tuple(
                PhaseResult.succeeded(identity) for identity in INIT_PHASES[:2]
            )
            init_cmd._persist_init_phase_results(
                cfg,
                prefix,
                run_id=self._run_id("phase2-provenance-run-id"),
                mode="headless",
                phase2_provenance=provenance,
            )
            status_path = init_cmd._init_status_path(cfg)
            with open(status_path, "rb") as status_file:
                original_bytes = status_file.read()
            payload = json.loads(original_bytes)
            self.assertEqual(
                set(payload),
                {
                    "checked_at",
                    "current_phase",
                    "current_phase_key",
                    "failed_checks",
                    "initialized",
                    "mode",
                    "phase2_provenance",
                    "phase_results",
                    "reason",
                    "run_id",
                    "schema",
                    "state",
                },
            )
            self.assertEqual(payload["schema"], "pve-freq-init-status-v2")
            self.assertEqual(payload["phase2_provenance"], provenance.to_payload())
            self.assertNotIn(password_sentinel.encode(), original_bytes)
            self.assertIsNone(
                init_cmd._parse_init_resume_candidate(cfg, mode="headless")
            )
            with open(status_path, "rb") as status_file:
                self.assertEqual(status_file.read(), original_bytes)

            expanded = (*prefix, PhaseResult.succeeded(INIT_PHASES[2]))
            init_cmd._persist_init_phase_results(
                cfg,
                expanded,
                run_id=self._run_id("phase2-provenance-run-id"),
                mode="headless",
                phase2_provenance=provenance,
            )
            expanded_payload = init_cmd._load_init_status(cfg)
            self.assertEqual(expanded_payload["schema"], "pve-freq-init-status-v2")
            self.assertEqual(
                expanded_payload["phase2_provenance"], provenance.to_payload()
            )
            self.assertEqual(
                [item["number"] for item in expanded_payload["phase_results"]],
                [1, 2, 3],
            )

            with open(status_path, "rb") as status_file:
                before_invalid = status_file.read()
            invalid_calls = (
                {
                    "results": prefix,
                    "mode": "headless",
                    "phase2_provenance": "not-provenance",
                    "error": TypeError,
                },
                {
                    "results": prefix,
                    "mode": "interactive",
                    "phase2_provenance": provenance,
                    "error": ValueError,
                },
                {
                    "results": prefix[:1],
                    "mode": "headless",
                    "phase2_provenance": provenance,
                    "error": ValueError,
                },
                {
                    "results": (
                        prefix[0],
                        PhaseResult.failed(INIT_PHASES[1], "configuration failed"),
                    ),
                    "mode": "headless",
                    "phase2_provenance": provenance,
                    "error": ValueError,
                },
                {
                    "results": (
                        PhaseResult.failed(INIT_PHASES[0], "prerequisites failed"),
                        prefix[1],
                    ),
                    "mode": "headless",
                    "phase2_provenance": provenance,
                    "error": ValueError,
                },
                {
                    "results": (
                        PhaseResult.succeeded(
                            PhaseIdentity(1, "prerequisites", "Prerequisites")
                        ),
                        prefix[1],
                    ),
                    "mode": "headless",
                    "phase2_provenance": provenance,
                    "error": ValueError,
                },
                {
                    "results": (
                        prefix[0],
                        PhaseResult.succeeded(
                            PhaseIdentity(
                                2,
                                "configure",
                                "Cluster Configuration + VLAN Discovery",
                            )
                        ),
                    ),
                    "mode": "headless",
                    "phase2_provenance": provenance,
                    "error": ValueError,
                },
            )
            for invalid_call in invalid_calls:
                with self.assertRaises(invalid_call["error"]):
                    init_cmd._persist_init_phase_results(
                        cfg,
                        invalid_call["results"],
                        run_id=self._run_id("phase2-provenance-run-id"),
                        mode=invalid_call["mode"],
                        phase2_provenance=invalid_call["phase2_provenance"],
                    )
                with open(status_path, "rb") as status_file:
                    self.assertEqual(status_file.read(), before_invalid)

    def _case_phase_two_provenance_runtime_wiring_is_exact_and_fail_closed(self):
        from freq.modules import init_cmd

        def finish(cfg, context, identity, *, error=None):
            return init_cmd._finish_init_phase(
                cfg,
                context,
                PhaseInput(identity, context),
                error=error,
            )

        with tempfile.TemporaryDirectory(prefix="freq-init-phase2-runtime-") as root:
            cfg = self._cfg(root)
            os.makedirs(cfg.conf_dir)
            config_path = os.path.join(cfg.conf_dir, "freq.toml")
            with open(config_path, "wb") as config_file:
                config_file.write(b'[pve]\nnodes = ["10.0.0.2"]\n')
            context = {
                "_init_run_id": self._run_id("phase2-runtime-run-id"),
                "_init_mode": "headless",
                "bootstrap_user": "freq-bootstrap",
                "bootstrap_key": "/private/bootstrap-key",
                "bootstrap_pass": "",
            }

            with mock.patch.object(
                init_cmd,
                "_persist_init_phase_results",
                wraps=init_cmd._persist_init_phase_results,
            ) as persist_results:
                finish(cfg, context, INIT_PHASES[0])
                phase1_payload = init_cmd._load_init_status(cfg)
                self.assertEqual(phase1_payload["schema"], "pve-freq-init-status-v1")
                self.assertNotIn("_phase2_resume_provenance", context)

                finish(cfg, context, INIT_PHASES[1])
                provenance = context["_phase2_resume_provenance"]
                phase2_payload = init_cmd._load_init_status(cfg)
                self.assertEqual(phase2_payload["schema"], "pve-freq-init-status-v2")
                self.assertEqual(
                    phase2_payload["phase2_provenance"],
                    provenance.to_payload(),
                )
                self.assertIs(
                    persist_results.call_args_list[1].kwargs["phase2_provenance"],
                    provenance,
                )

                status_path = init_cmd._init_status_path(cfg)
                with open(status_path, "rb") as status_file:
                    before_parse = status_file.read()
                self.assertIsNone(
                    init_cmd._parse_init_resume_candidate(cfg, mode="headless")
                )
                with open(status_path, "rb") as status_file:
                    self.assertEqual(status_file.read(), before_parse)

                with open(config_path, "ab") as config_file:
                    config_file.write(b"# changed after Phase 2\n")
                finish(cfg, context, INIT_PHASES[2])
                phase3_payload = init_cmd._load_init_status(cfg)
                self.assertIs(
                    persist_results.call_args_list[2].kwargs["phase2_provenance"],
                    provenance,
                )
                self.assertEqual(
                    phase3_payload["phase2_provenance"],
                    phase2_payload["phase2_provenance"],
                )

        password_sentinel = "phase2-runtime-password-must-not-persist"
        with tempfile.TemporaryDirectory(
            prefix="freq-init-phase2-password-runtime-"
        ) as root:
            cfg = self._cfg(root)
            os.makedirs(cfg.conf_dir)
            with open(os.path.join(cfg.conf_dir, "freq.toml"), "wb") as config_file:
                config_file.write(b"[pve]\n")
            context = {
                "_init_run_id": self._run_id("phase2-password-runtime-run-id"),
                "_init_mode": "headless",
                "bootstrap_user": "freq-bootstrap",
                "bootstrap_key": "",
                "bootstrap_pass": password_sentinel,
            }
            with mock.patch.object(
                init_cmd,
                "_persist_init_phase_results",
                wraps=init_cmd._persist_init_phase_results,
            ) as persist_results:
                finish(cfg, context, INIT_PHASES[0])
                finish(cfg, context, INIT_PHASES[1])
            provenance = context["_phase2_resume_provenance"]
            self.assertIs(
                persist_results.call_args_list[1].kwargs["phase2_provenance"],
                provenance,
            )
            self.assertEqual(provenance.bootstrap_auth, "password")
            with open(init_cmd._init_status_path(cfg), "rb") as status_file:
                raw_status = status_file.read()
            self.assertNotIn(password_sentinel.encode(), raw_status)
            payload = json.loads(raw_status)
            self.assertEqual(payload["schema"], "pve-freq-init-status-v2")
            self.assertEqual(
                payload["phase2_provenance"],
                provenance.to_payload(),
            )

        fallback_scenarios = (
            {
                "name": "interactive",
                "mode": "interactive",
                "bootstrap_key": "/private/bootstrap-key",
                "bootstrap_pass": "",
                "phase1_identity": INIT_PHASES[0],
                "phase1_error": None,
                "phase2_identity": INIT_PHASES[1],
                "error": None,
            },
            {
                "name": "failed-phase2",
                "mode": "headless",
                "bootstrap_key": "/private/bootstrap-key",
                "bootstrap_pass": "",
                "phase1_identity": INIT_PHASES[0],
                "phase1_error": None,
                "phase2_identity": INIT_PHASES[1],
                "error": "configuration failed",
            },
            {
                "name": "invalid-auth",
                "mode": "headless",
                "bootstrap_key": "/private/bootstrap-key",
                "bootstrap_pass": "also-present",
                "phase1_identity": INIT_PHASES[0],
                "phase1_error": None,
                "phase2_identity": INIT_PHASES[1],
                "error": None,
            },
            {
                "name": "noncanonical-phase2",
                "mode": "headless",
                "bootstrap_key": "/private/bootstrap-key",
                "bootstrap_pass": "",
                "phase1_identity": INIT_PHASES[0],
                "phase1_error": None,
                "phase2_identity": PhaseIdentity(
                    INIT_PHASES[1].number,
                    INIT_PHASES[1].key,
                    INIT_PHASES[1].title,
                ),
                "error": None,
            },
            {
                "name": "noncanonical-phase1",
                "mode": "headless",
                "bootstrap_key": "/private/bootstrap-key",
                "bootstrap_pass": "",
                "phase1_identity": PhaseIdentity(
                    INIT_PHASES[0].number,
                    INIT_PHASES[0].key,
                    INIT_PHASES[0].title,
                ),
                "phase1_error": None,
                "phase2_identity": INIT_PHASES[1],
                "error": None,
            },
            {
                "name": "failed-phase1",
                "mode": "headless",
                "bootstrap_key": "/private/bootstrap-key",
                "bootstrap_pass": "",
                "phase1_identity": INIT_PHASES[0],
                "phase1_error": "prerequisites failed",
                "phase2_identity": INIT_PHASES[1],
                "error": None,
            },
        )
        for scenario in fallback_scenarios:
            with self.subTest(scenario=scenario["name"]), tempfile.TemporaryDirectory(
                prefix=f"freq-init-phase2-{scenario['name']}-"
            ) as root:
                cfg = self._cfg(root)
                os.makedirs(cfg.conf_dir)
                with open(os.path.join(cfg.conf_dir, "freq.toml"), "wb") as config_file:
                    config_file.write(b"[pve]\n")
                context = {
                    "_init_run_id": self._run_id(f"{scenario['name']}-run-id"),
                    "_init_mode": scenario["mode"],
                    "bootstrap_user": "freq-bootstrap",
                    "bootstrap_key": scenario["bootstrap_key"],
                    "bootstrap_pass": scenario["bootstrap_pass"],
                }
                finish(
                    cfg,
                    context,
                    scenario["phase1_identity"],
                    error=scenario["phase1_error"],
                )
                finish(
                    cfg,
                    context,
                    scenario["phase2_identity"],
                    error=scenario["error"],
                )
                payload = init_cmd._load_init_status(cfg)
                self.assertEqual(payload["schema"], "pve-freq-init-status-v1")
                self.assertNotIn("phase2_provenance", payload)
                self.assertNotIn("_phase2_resume_provenance", context)

    def _case_phase_two_resume_candidate_parser_is_exact_and_unwired(self):
        from freq.core.types import phase_catalog
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory(prefix="freq-init-phase2-parser-") as root:
            cfg = self._cfg(root)
            phase2_run_id = "b" * 32
            os.makedirs(cfg.conf_dir)
            with open(os.path.join(cfg.conf_dir, "freq.toml"), "wb") as config_file:
                config_file.write(b'[pve]\nnodes = ["10.0.0.2"]\n')
            provenance = init_cmd._build_init_phase2_resume_provenance(
                cfg,
                {
                    "_init_mode": "headless",
                    "bootstrap_user": "freq-bootstrap",
                    "bootstrap_key": "/private/bootstrap-key",
                    "bootstrap_pass": "",
                },
            )
            phases = phase_catalog()
            completed_prefix = tuple(
                PhaseResult.succeeded(identity) for identity in phases[:4]
            )
            init_cmd._persist_init_phase_results(
                cfg,
                completed_prefix,
                run_id=phase2_run_id,
                mode="headless",
                phase2_provenance=provenance,
            )
            status_path = init_cmd._init_status_path(cfg)
            with open(status_path, "rb") as status_file:
                original_bytes = status_file.read()

            candidate = init_cmd._parse_init_phase2_resume_candidate(cfg)
            self.assertIsNotNone(candidate)
            run_id, reusable_prefix, parsed_provenance = candidate
            self.assertEqual(run_id, phase2_run_id)
            self.assertEqual(len(reusable_prefix), 2)
            self.assertTrue(
                all(
                    result.identity is phases[index]
                    and result.status is PhaseStatus.SUCCEEDED
                    for index, result in enumerate(reusable_prefix)
                )
            )
            self.assertEqual(parsed_provenance, provenance)
            self.assertIsNot(parsed_provenance, provenance)
            with open(status_path, "rb") as status_file:
                self.assertEqual(status_file.read(), original_bytes)

            invalid_payloads = []

            def invalid(mutator):
                changed = json.loads(original_bytes)
                mutator(changed)
                invalid_payloads.append(changed)

            invalid(lambda value: value.update({"unexpected": True}))
            invalid(lambda value: value.update(schema="pve-freq-init-status-v1"))
            invalid(lambda value: value.update(checked_at=" padded "))
            invalid(lambda value: value.update(run_id=" padded "))
            invalid(lambda value: value.update(run_id="B" * 32))
            invalid(lambda value: value.update(run_id="b" * 31))
            invalid(lambda value: value.update(run_id="g" * 32))
            invalid(lambda value: value.update(mode="interactive"))
            invalid(lambda value: value.update(state="succeeded"))
            invalid(lambda value: value.update(initialized=True))
            invalid(lambda value: value.update(failed_checks=["failed"]))
            invalid(lambda value: value.update(reason="failed"))
            invalid(lambda value: value.update(phase_results=value["phase_results"][:1]))

            def complete_artifact(value):
                value["phase_results"] = [
                    {
                        "number": identity.number,
                        "key": identity.key,
                        "title": identity.title,
                        "status": "succeeded",
                        "error": None,
                    }
                    for identity in phases
                ]
                value["current_phase"] = phases[-1].number
                value["current_phase_key"] = phases[-1].key

            invalid(complete_artifact)
            invalid(lambda value: value["phase_results"][0].update(extra=True))
            invalid(
                lambda value: value["phase_results"][0].update(
                    number=101,
                    key="forged-phase-1",
                    title="Forged Phase 1",
                )
            )
            invalid(
                lambda value: value["phase_results"][0].update(
                    status="failed", error="Phase 1 failed"
                )
            )
            invalid(
                lambda value: value["phase_results"][1].update(
                    number=202,
                    key="forged-phase-2",
                    title="Forged Phase 2",
                )
            )
            invalid(
                lambda value: value["phase_results"][1].update(
                    status="failed", error="Phase 2 failed"
                )
            )
            invalid(
                lambda value: value["phase_results"][3].update(
                    status="failed", error="later phase failed"
                )
            )
            invalid(lambda value: value["phase_results"][3].update(number=True))
            invalid(lambda value: value.update(current_phase=3))
            invalid(lambda value: value.update(current_phase_key="service_account"))
            invalid(lambda value: value.update(phase2_provenance="not-a-mapping"))
            invalid(
                lambda value: value["phase2_provenance"].update(unexpected=True)
            )
            invalid(
                lambda value: value["phase2_provenance"].update(
                    config_fingerprint="not-a-fingerprint"
                )
            )
            invalid(
                lambda value: value["phase2_provenance"].update(
                    bootstrap_auth="token"
                )
            )
            invalid(
                lambda value: value["phase2_provenance"].update(version=True)
            )

            for index, invalid_payload in enumerate(invalid_payloads):
                with self.subTest(invalid_payload=index), mock.patch.object(
                    init_cmd,
                    "_load_init_status",
                    return_value=invalid_payload,
                ):
                    self.assertIsNone(
                        init_cmd._parse_init_phase2_resume_candidate(cfg)
                    )

            self.assertIsNone(
                init_cmd._parse_init_resume_candidate(cfg, mode="headless")
            )
            with mock.patch.object(
                init_cmd,
                "_parse_init_phase2_resume_candidate",
                wraps=init_cmd._parse_init_phase2_resume_candidate,
            ) as parse_phase2, mock.patch.object(
                init_cmd,
                "_start_init_run",
                return_value={
                    "_init_run_id": self._run_id("fresh-unwired-run-id"),
                    "_init_mode": "headless",
                },
            ) as fresh_start:
                fresh = init_cmd._resume_or_start_init_run(cfg, mode="headless")
            self.assertEqual(
                fresh,
                {
                    "_init_run_id": self._run_id("fresh-unwired-run-id"),
                    "_init_mode": "headless",
                },
            )
            parse_phase2.assert_not_called()
            fresh_start.assert_called_once_with(cfg, mode="headless")
            with open(status_path, "rb") as status_file:
                self.assertEqual(status_file.read(), original_bytes)

    def _case_phase_two_resume_selector_requires_exact_current_provenance(self):
        from freq.core.types import phase_catalog
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory(prefix="freq-init-phase2-selector-") as root:
            cfg = self._cfg(root)
            os.makedirs(cfg.conf_dir)
            config_paths = {
                "freq.toml": os.path.join(cfg.conf_dir, "freq.toml"),
                "vlans.toml": os.path.join(cfg.conf_dir, "vlans.toml"),
            }
            config_bytes = {
                "freq.toml": b'[pve]\nnodes = ["10.0.0.2"]\n',
                "vlans.toml": b'[vlan.vlan10]\nid = 10\n',
            }
            for filename, path in config_paths.items():
                with open(path, "wb") as config_file:
                    config_file.write(config_bytes[filename])

            context = {
                "_init_mode": "headless",
                "bootstrap_user": "freq-bootstrap",
                "bootstrap_key": "/private/bootstrap-key",
                "bootstrap_pass": "",
            }
            provenance = init_cmd._build_init_phase2_resume_provenance(cfg, context)
            selector_run_id = "c" * 32
            phases = phase_catalog()
            completed_prefix = tuple(
                PhaseResult.succeeded(identity) for identity in phases[:4]
            )
            init_cmd._persist_init_phase_results(
                cfg,
                completed_prefix,
                run_id=selector_run_id,
                mode="headless",
                phase2_provenance=provenance,
            )
            status_path = init_cmd._init_status_path(cfg)
            with open(status_path, "rb") as status_file:
                original_status = status_file.read()

            selected = init_cmd._select_init_phase2_resume_candidate(cfg, context)
            self.assertIsNotNone(selected)
            run_id, reusable_prefix, selected_provenance = selected
            self.assertEqual(run_id, selector_run_id)
            self.assertEqual(
                [result.identity for result in reusable_prefix],
                list(phases[:2]),
            )
            self.assertEqual(selected_provenance, provenance)
            with open(status_path, "rb") as status_file:
                self.assertEqual(status_file.read(), original_status)

            with mock.patch.object(
                init_cmd,
                "_parse_init_phase2_resume_candidate",
                return_value=None,
            ) as reject_candidate, mock.patch.object(
                init_cmd,
                "_build_init_phase2_resume_provenance",
                wraps=init_cmd._build_init_phase2_resume_provenance,
            ) as build_after_rejection:
                self.assertIsNone(
                    init_cmd._select_init_phase2_resume_candidate(cfg, context)
                )
            reject_candidate.assert_called_once_with(cfg)
            build_after_rejection.assert_not_called()

            mismatched_contexts = (
                {**context, "bootstrap_user": "other-bootstrap"},
                {
                    **context,
                    "bootstrap_key": "",
                    "bootstrap_pass": "current-password",
                },
                {**context, "_init_mode": "interactive"},
                {**context, "bootstrap_key": ""},
                {**context, "bootstrap_pass": "also-present"},
                {**context, "bootstrap_user": " padded "},
            )
            for mismatch in mismatched_contexts:
                with self.subTest(mismatch=mismatch):
                    self.assertIsNone(
                        init_cmd._select_init_phase2_resume_candidate(cfg, mismatch)
                    )
            self.assertIsNone(
                init_cmd._select_init_phase2_resume_candidate(cfg, None)
            )

            for filename, path in config_paths.items():
                with self.subTest(changed_config=filename):
                    with open(path, "ab") as config_file:
                        config_file.write(b"# changed after checkpoint\n")
                    self.assertIsNone(
                        init_cmd._select_init_phase2_resume_candidate(cfg, context)
                    )
                    with open(path, "wb") as config_file:
                        config_file.write(config_bytes[filename])

            parsed_candidate = init_cmd._parse_init_phase2_resume_candidate(cfg)
            with mock.patch.object(
                init_cmd,
                "_parse_init_phase2_resume_candidate",
                return_value=parsed_candidate,
            ) as parse_candidate, mock.patch.object(
                init_cmd,
                "_build_init_phase2_resume_provenance",
                return_value=parsed_candidate[2],
            ) as build_current:
                exact_candidate = init_cmd._select_init_phase2_resume_candidate(
                    cfg, context
                )
            self.assertIs(exact_candidate, parsed_candidate)
            parse_candidate.assert_called_once_with(cfg)
            build_current.assert_called_once_with(cfg, context)

            with mock.patch.object(
                init_cmd,
                "_select_init_phase2_resume_candidate",
                wraps=init_cmd._select_init_phase2_resume_candidate,
            ) as select_phase2, mock.patch.object(
                init_cmd,
                "_start_init_run",
                return_value={
                    "_init_run_id": self._run_id("fresh-selector-unwired-run-id"),
                    "_init_mode": "headless",
                },
            ) as fresh_start:
                fresh = init_cmd._resume_or_start_init_run(cfg, mode="headless")
            self.assertEqual(
                fresh,
                {
                    "_init_run_id": self._run_id("fresh-selector-unwired-run-id"),
                    "_init_mode": "headless",
                },
            )
            select_phase2.assert_not_called()
            fresh_start.assert_called_once_with(cfg, mode="headless")
            with open(status_path, "rb") as status_file:
                self.assertEqual(status_file.read(), original_status)

            password_sentinel = "phase2-selector-password-must-not-persist"
            password_context = {
                **context,
                "bootstrap_key": "",
                "bootstrap_pass": password_sentinel,
            }
            password_provenance = init_cmd._build_init_phase2_resume_provenance(
                cfg, password_context
            )
            password_selector_run_id = "f" * 32
            init_cmd._persist_init_phase_results(
                cfg,
                completed_prefix,
                run_id=password_selector_run_id,
                mode="headless",
                phase2_provenance=password_provenance,
            )
            password_selected = init_cmd._select_init_phase2_resume_candidate(
                cfg, password_context
            )
            self.assertIsNotNone(password_selected)
            self.assertEqual(password_selected[0], password_selector_run_id)
            self.assertEqual(password_selected[2].bootstrap_auth, "password")
            with open(status_path, "rb") as status_file:
                password_status = status_file.read()
            self.assertNotIn(password_sentinel.encode(), password_status)
            self.assertIsNotNone(
                init_cmd._select_init_phase2_resume_candidate(
                    cfg,
                    {
                        **password_context,
                        "bootstrap_pass": "different-current-password",
                    },
                )
            )

    def _case_phase_two_resume_context_projection_is_exact_and_unwired(self):
        from freq.core.types import InitPhase2ResumeProvenance, phase_catalog
        from freq.modules import init_cmd

        phases = phase_catalog()
        completed = tuple(
            PhaseResult.succeeded(identity) for identity in phases[:2]
        )
        provenance = InitPhase2ResumeProvenance(
            config_fingerprint="a" * 64,
            bootstrap_user="freq-bootstrap",
            bootstrap_auth="key",
        )
        candidate = (self._run_id("phase2-context-run-id"), completed, provenance)

        context = init_cmd._build_init_phase2_resume_context(candidate)
        self.assertEqual(
            context,
            {
                "_init_run_id": self._run_id("phase2-context-run-id"),
                "_init_mode": "headless",
                "_phase_results": completed,
                "_phase2_resume_provenance": provenance,
            },
        )
        self.assertIs(context["_phase_results"], completed)
        self.assertIs(context["_phase2_resume_provenance"], provenance)

        password_provenance = InitPhase2ResumeProvenance(
            config_fingerprint="b" * 64,
            bootstrap_user="freq-bootstrap",
            bootstrap_auth="password",
        )
        password_candidate = (
            self._run_id("phase2-password-context-run-id"),
            completed,
            password_provenance,
        )
        password_context = init_cmd._build_init_phase2_resume_context(
            password_candidate
        )
        self.assertEqual(
            password_context,
            {
                "_init_run_id": self._run_id("phase2-password-context-run-id"),
                "_init_mode": "headless",
                "_phase_results": completed,
                "_phase2_resume_provenance": password_provenance,
            },
        )
        self.assertIs(password_context["_phase_results"], completed)
        self.assertIs(
            password_context["_phase2_resume_provenance"], password_provenance
        )

        invalid_candidates = (
            None,
            list(candidate),
            candidate[:2],
            (*candidate, "extra"),
            ("", completed, provenance),
            (" padded-run-id ", completed, provenance),
            (candidate[0], list(completed), provenance),
            (candidate[0], completed[:1], provenance),
            (candidate[0], tuple(reversed(completed)), provenance),
            (candidate[0], (completed[0], completed[0]), provenance),
            (candidate[0], (completed[1], completed[1]), provenance),
            (
                candidate[0],
                (*completed, PhaseResult.succeeded(phases[2])),
                provenance,
            ),
            (
                candidate[0],
                (
                    PhaseResult.succeeded(
                        PhaseIdentity(
                            phases[0].number,
                            phases[0].key,
                            phases[0].title,
                        )
                    ),
                    completed[1],
                ),
                provenance,
            ),
            (
                candidate[0],
                (
                    completed[0],
                    PhaseResult.succeeded(
                        PhaseIdentity(
                            phases[1].number,
                            phases[1].key,
                            phases[1].title,
                        )
                    ),
                ),
                provenance,
            ),
            (
                candidate[0],
                (
                    PhaseResult.failed(phases[0], "prerequisites failed"),
                    completed[1],
                ),
                provenance,
            ),
            (
                candidate[0],
                (
                    completed[0],
                    PhaseResult.failed(phases[1], "configuration failed"),
                ),
                provenance,
            ),
            (
                candidate[0],
                (
                    PhaseResult.succeeded(
                        phases[0], details={"unexpected": "state"}
                    ),
                    completed[1],
                ),
                provenance,
            ),
            (
                candidate[0],
                (
                    completed[0],
                    PhaseResult.succeeded(
                        phases[1], details={"unexpected": "state"}
                    ),
                ),
                provenance,
            ),
            (candidate[0], completed, "not-provenance"),
        )
        for index, invalid_candidate in enumerate(invalid_candidates):
            with self.subTest(invalid_candidate=index):
                self.assertIsNone(
                    init_cmd._build_init_phase2_resume_context(invalid_candidate)
                )

        with mock.patch.object(
            init_cmd,
            "_build_init_phase2_resume_context",
            wraps=init_cmd._build_init_phase2_resume_context,
        ) as build_resume_context:
            self._run_headless(catalog_override=phases)
        build_resume_context.assert_not_called()

    def _case_headless_phase_two_inputs_require_exact_current_config(self):
        from freq.modules import init_cmd

        cfg = types.SimpleNamespace(
            pve_nodes=["10.0.0.2", "10.0.0.3"],
            pve_node_names=["pve01", "pve02"],
            vm_gateway="10.0.0.1",
            vm_nameserver="10.0.0.53",
            cluster_name="dc01",
            ssh_mode="sudo",
        )
        exact = self._args(
            headless=True,
            pve_nodes="10.0.0.2, 10.0.0.3",
            pve_node_names=None,
            gateway="10.0.0.1",
            nameserver="10.0.0.53",
            cluster_name="dc01",
            ssh_mode="sudo",
        )
        self.assertTrue(
            init_cmd._headless_phase2_inputs_match_current_config(cfg, exact)
        )
        self.assertTrue(
            init_cmd._headless_phase2_inputs_match_current_config(
                cfg,
                self._args(headless=True),
            )
        )

        exact_named = types.SimpleNamespace(
            **{
                **vars(exact),
                "pve_node_names": "pve01 pve02",
            }
        )
        self.assertTrue(
            init_cmd._headless_phase2_inputs_match_current_config(cfg, exact_named)
        )
        exact_padded_names = types.SimpleNamespace(
            **{
                **vars(exact),
                "pve_node_names": "pve01",
            }
        )
        self.assertTrue(
            init_cmd._headless_phase2_inputs_match_current_config(
                cfg, exact_padded_names
            )
        )

        divergent = (
            {"pve_nodes": "10.0.0.2,10.0.0.4"},
            {"pve_node_names": "pve01 other"},
            {"gateway": "10.0.0.254"},
            {"nameserver": "1.1.1.1"},
            {"cluster_name": "dc02"},
            {"ssh_mode": "root"},
            {"pve_nodes": "not-an-ip"},
            {"pve_nodes": "   "},
            {"pve_nodes": None, "pve_node_names": "pve01 pve02"},
            {"gateway": object()},
            {"pve_nodes": []},
        )
        for changes in divergent:
            with self.subTest(changes=changes):
                candidate = types.SimpleNamespace(**{**vars(exact), **changes})
                self.assertFalse(
                    init_cmd._headless_phase2_inputs_match_current_config(
                        cfg, candidate
                    )
                )

        malformed_matching_configs = (
            ("vm_gateway", "gateway", "not-an-ip"),
            ("vm_nameserver", "nameserver", "not-an-ip"),
            ("ssh_mode", "ssh_mode", "unsupported"),
        )
        for config_name, input_name, invalid_value in malformed_matching_configs:
            with self.subTest(malformed=input_name):
                malformed_cfg = types.SimpleNamespace(
                    **{**vars(cfg), config_name: invalid_value}
                )
                malformed_args = types.SimpleNamespace(
                    **{**vars(exact), input_name: invalid_value}
                )
                self.assertFalse(
                    init_cmd._headless_phase2_inputs_match_current_config(
                        malformed_cfg, malformed_args
                    )
                )

        malformed_pve_cfg = types.SimpleNamespace(
            **{
                **vars(cfg),
                "pve_nodes": ["not-an-ip"],
                "pve_node_names": ["pve01"],
            }
        )
        malformed_pve_args = types.SimpleNamespace(
            **{
                **vars(exact),
                "pve_nodes": "not-an-ip",
                "pve_node_names": None,
            }
        )
        self.assertFalse(
            init_cmd._headless_phase2_inputs_match_current_config(
                malformed_pve_cfg, malformed_pve_args
            )
        )

        self.assertFalse(
            init_cmd._headless_phase2_inputs_match_current_config(
                cfg, types.SimpleNamespace(**{**vars(exact), "headless": False})
            )
        )
        self.assertFalse(
            init_cmd._headless_phase2_inputs_match_current_config(cfg, None)
        )

    def _case_headless_phase_two_resume_wiring_skips_exact_prefix_only(self):
        from freq.core.types import InitPhase2ResumeProvenance, phase_catalog
        from freq.modules import init_cmd

        phases = phase_catalog()
        completed = tuple(
            PhaseResult.succeeded(identity) for identity in phases[:2]
        )
        provenance = InitPhase2ResumeProvenance(
            config_fingerprint="a" * 64,
            bootstrap_user="root",
            bootstrap_auth="key",
        )
        candidate = ("d" * 32, completed, provenance)
        final_payload = {}

        def seed_phase_two_checkpoint(cfg, args):
            nonlocal provenance, candidate
            os.makedirs(cfg.conf_dir)
            with open(
                os.path.join(cfg.conf_dir, "freq.toml"),
                "w",
                encoding="utf-8",
            ) as config_file:
                config_file.write("[pve]\nnodes = []\n")
            provenance = init_cmd._build_init_phase2_resume_provenance(
                cfg,
                {
                    "_init_mode": "headless",
                    "bootstrap_key": args.bootstrap_key,
                    "bootstrap_pass": "",
                    "bootstrap_user": args.bootstrap_user,
                },
            )
            candidate = ("d" * 32, completed, provenance)
            init_cmd._persist_init_phase_results(
                cfg,
                completed,
                run_id=candidate[0],
                mode="headless",
                phase2_provenance=provenance,
            )

        with mock.patch.object(
            init_cmd,
            "_headless_phase2_inputs_match_current_config",
            wraps=init_cmd._headless_phase2_inputs_match_current_config,
        ) as match_inputs, mock.patch.object(
            init_cmd,
            "_select_init_phase2_resume_candidate",
            wraps=init_cmd._select_init_phase2_resume_candidate,
        ) as select_candidate, mock.patch.object(
            init_cmd,
            "_build_init_phase2_resume_context",
            wraps=init_cmd._build_init_phase2_resume_context,
        ) as build_context, mock.patch.object(
            init_cmd,
            "_resume_or_start_init_run",
            wraps=init_cmd._resume_or_start_init_run,
        ) as fresh_fallback:
            resumed = self._run_headless(
                catalog_override=phases,
                prepare=seed_phase_two_checkpoint,
                observe=lambda cfg: final_payload.update(
                    init_cmd._load_init_status(cfg)
                ),
            )

        (
            rc,
            _headers,
            calls,
            started,
            _catalog_calls,
            _deploy_count,
            _injected_catalog,
            phase_results,
        ) = resumed
        projected_candidate = build_context.call_args.args[0]
        self.assertEqual(rc, 0)
        self.assertEqual(tuple(calls), HEADLESS_SUCCESS_CALLS[3:])
        self.assertEqual(started, list(phases[2:]))
        self.assertIs(phase_results[0], projected_candidate[1][0])
        self.assertIs(phase_results[1], projected_candidate[1][1])
        self._assert_result_ledger(
            phase_results,
            len(phases),
            expected_identities=phases,
        )
        match_inputs.assert_called_once()
        self.assertIs(match_inputs.call_args.args[1].headless, True)
        select_candidate.assert_called_once()
        self.assertEqual(select_candidate.call_args.args[1]["_init_mode"], "headless")
        self.assertEqual(select_candidate.call_args.args[1]["bootstrap_user"], "root")
        self.assertTrue(select_candidate.call_args.args[1]["bootstrap_key"])
        self.assertEqual(select_candidate.call_args.args[1]["bootstrap_pass"], "")
        self.assertEqual(projected_candidate[0], candidate[0])
        self.assertEqual(projected_candidate[1], completed)
        self.assertEqual(projected_candidate[2], provenance)
        self.assertEqual(final_payload["run_id"], candidate[0])
        self.assertEqual(final_payload["schema"], "pve-freq-init-status-v2")
        self.assertEqual(len(final_payload["phase_results"]), len(phases))
        self.assertEqual(
            final_payload["phase2_provenance"],
            provenance.to_payload(),
        )
        fresh_fallback.assert_not_called()

        password_sentinel = "bootstrap-password"
        password_payload = {}
        password_candidate = None

        def seed_password_checkpoint(cfg, args):
            nonlocal password_candidate
            os.makedirs(cfg.conf_dir)
            with open(
                os.path.join(cfg.conf_dir, "freq.toml"),
                "w",
                encoding="utf-8",
            ) as config_file:
                config_file.write("[pve]\nnodes = []\n")
            password_provenance = init_cmd._build_init_phase2_resume_provenance(
                cfg,
                {
                    "_init_mode": "headless",
                    "bootstrap_key": "",
                    "bootstrap_pass": password_sentinel,
                    "bootstrap_user": args.bootstrap_user,
                },
            )
            password_candidate = (
                "e" * 32,
                completed,
                password_provenance,
            )
            init_cmd._persist_init_phase_results(
                cfg,
                completed,
                run_id=password_candidate[0],
                mode="headless",
                phase2_provenance=password_provenance,
            )

        with mock.patch.object(
            init_cmd,
            "_select_init_phase2_resume_candidate",
            wraps=init_cmd._select_init_phase2_resume_candidate,
        ) as select_password, mock.patch.object(
            init_cmd,
            "_resume_or_start_init_run",
            wraps=init_cmd._resume_or_start_init_run,
        ) as password_fallback:
            password_resumed = self._run_headless(
                catalog_override=phases,
                prepare=seed_password_checkpoint,
                observe=lambda cfg: password_payload.update(
                    init_cmd._load_init_status(cfg)
                ),
                bootstrap_auth="password",
            )
        self.assertEqual(tuple(password_resumed[2]), HEADLESS_SUCCESS_CALLS[3:])
        self.assertEqual(password_resumed[3], list(phases[2:]))
        self.assertEqual(select_password.call_args.args[1]["bootstrap_key"], "")
        self.assertEqual(
            select_password.call_args.args[1]["bootstrap_pass"],
            password_sentinel,
        )
        self.assertEqual(password_payload["run_id"], password_candidate[0])
        self.assertEqual(
            password_payload["phase2_provenance"],
            password_candidate[2].to_payload(),
        )
        self.assertNotIn(password_sentinel, json.dumps(password_payload))
        password_fallback.assert_not_called()

        rejected_status = {}

        def seed_rejected_checkpoint(cfg, args):
            seed_phase_two_checkpoint(cfg, args)
            with open(init_cmd._init_status_path(cfg), "rb") as status_file:
                rejected_status["before"] = status_file.read()

        def observe_rejected_checkpoint(cfg):
            with open(init_cmd._init_status_path(cfg), "rb") as status_file:
                rejected_status["after"] = status_file.read()

        with mock.patch.object(
            init_cmd,
            "_headless_phase2_inputs_match_current_config",
            wraps=init_cmd._headless_phase2_inputs_match_current_config,
        ) as rejected_inputs, mock.patch.object(
            init_cmd,
            "_select_init_phase2_resume_candidate",
            wraps=init_cmd._select_init_phase2_resume_candidate,
        ) as rejected_selector, mock.patch.object(
            init_cmd,
            "_build_init_phase2_resume_context",
            wraps=init_cmd._build_init_phase2_resume_context,
        ) as rejected_projection, mock.patch.object(
            init_cmd,
            "_resume_or_start_init_run",
            wraps=init_cmd._resume_or_start_init_run,
        ) as rejected_fallback:
            credential_rejected = self._run_headless(
                catalog_override=phases,
                prepare=seed_rejected_checkpoint,
                observe=observe_rejected_checkpoint,
                service_account_valid=False,
            )
        self.assertEqual(credential_rejected[0], 1)
        self.assertEqual(rejected_status["after"], rejected_status["before"])
        rejected_inputs.assert_not_called()
        rejected_selector.assert_not_called()
        rejected_projection.assert_not_called()
        rejected_fallback.assert_not_called()

        fallback_scenarios = (
            {"name": "input-mismatch", "inputs_match": False, "candidate": candidate},
            {"name": "selector-reject", "inputs_match": True, "candidate": None},
        )
        for scenario in fallback_scenarios:
            with self.subTest(fallback=scenario["name"]), mock.patch.object(
                init_cmd,
                "_headless_phase2_inputs_match_current_config",
                return_value=scenario["inputs_match"],
            ) as match_inputs, mock.patch.object(
                init_cmd,
                "_select_init_phase2_resume_candidate",
                return_value=scenario["candidate"],
            ) as select_candidate, mock.patch.object(
                init_cmd,
                "_build_init_phase2_resume_context",
                wraps=init_cmd._build_init_phase2_resume_context,
            ) as build_context, mock.patch.object(
                init_cmd,
                "_resume_or_start_init_run",
                wraps=init_cmd._resume_or_start_init_run,
            ) as fresh_fallback:
                fresh = self._run_headless(catalog_override=phases)

            self.assertEqual(fresh[0], 0)
            self.assertEqual(tuple(fresh[2]), HEADLESS_SUCCESS_CALLS)
            self.assertEqual(fresh[3], list(phases))
            match_inputs.assert_called_once()
            if scenario["inputs_match"]:
                select_candidate.assert_called_once()
            else:
                select_candidate.assert_not_called()
            build_context.assert_not_called()
            fresh_fallback.assert_called_once()

        with mock.patch.object(
            init_cmd,
            "_headless_phase2_inputs_match_current_config",
            return_value=True,
        ), mock.patch.object(
            init_cmd,
            "_select_init_phase2_resume_candidate",
            return_value=candidate,
        ), mock.patch.object(
            init_cmd,
            "_build_init_phase2_resume_context",
            return_value=None,
        ) as reject_projection, mock.patch.object(
            init_cmd,
            "_resume_or_start_init_run",
            wraps=init_cmd._resume_or_start_init_run,
        ) as fresh_fallback:
            rejected_projection = self._run_headless(catalog_override=phases)
        self.assertEqual(tuple(rejected_projection[2]), HEADLESS_SUCCESS_CALLS)
        self.assertEqual(rejected_projection[3], list(phases))
        reject_projection.assert_called_once_with(candidate)
        fresh_fallback.assert_called_once()

    def _case_phase_result_details_never_persist(self):
        from freq.modules import init_cmd

        password_sentinel = "gate13-password-sentinel-9f42"
        token_sentinel = "gate13-token-sentinel-7c31"
        result = PhaseResult.succeeded(
            INIT_PHASES[1],
            details={
                "credentials": {"password": password_sentinel},
                "tokens": [token_sentinel],
            },
        )
        with tempfile.TemporaryDirectory(prefix="freq-init-no-details-") as root:
            cfg = self._cfg(root)
            init_cmd._persist_init_phase_results(
                cfg,
                (result,),
                run_id=self._run_id("no-details-run-id"),
                mode="interactive",
            )
            with open(init_cmd._init_status_path(cfg), "rb") as status_file:
                raw_status = status_file.read()

        self.assertNotIn(password_sentinel.encode(), raw_status)
        self.assertNotIn(token_sentinel.encode(), raw_status)
        payload = json.loads(raw_status)
        self.assertEqual(
            payload["phase_results"],
            [
                {
                    "number": 2,
                    "key": "configure",
                    "title": "Cluster Configuration + VLAN Discovery",
                    "status": "succeeded",
                    "error": None,
                }
            ],
        )
        self.assertEqual(
            set(payload["phase_results"][0]),
            {"number", "key", "title", "status", "error"},
        )


INIT_ORCHESTRATOR_CASES = (
    "_case_interactive_executes_canonical_order",
    "_case_headless_executes_canonical_order",
    "_case_failure_stops_before_later_mutation",
    "_case_welcome_failure_stops_both_paths_at_phase_one",
    "_case_fleet_discovery_failure_stops_both_paths_at_phase_seven",
    "_case_verification_failure_completes_current_topology",
    "_case_dry_run_routes_before_root_and_mutating_phases",
    "_case_interactive_consumes_injected_typed_catalog",
    "_case_phase_header_renderer_is_preserved",
    "_case_typed_phase_start_returns_detached_input",
    "_case_typed_phase_finish_records_exact_results",
    "_case_typed_phase_persistence_replay_is_exact_replacement",
    "_case_fresh_restart_resets_durable_progress",
    "_case_runtime_prepares_private_control_before_execution",
    "_case_private_point_of_no_return_claim_precedes_mutation",
    "_case_web_child_cancel_signal_is_pre_ponr_only",
    "_case_web_pre_ponr_validation_return_restores_mutables",
    "_case_web_pre_ponr_exception_restores_mutables_and_reraises",
    "_case_web_post_ponr_failure_does_not_restore_memory",
    "_case_web_cancel_topology_failure_never_claims_preservation",
    "_case_web_ordinary_topology_failure_never_restores_memory",
    "_case_non_web_headless_ordinary_failures_preserve_pre_ponr_state",
    "_case_parent_delivers_owned_cancel_once",
    "_case_web_cancel_endpoint_is_owner_scoped_and_fail_closed",
    "_case_pre_phase_one_interruption_preserves_product_state",
    "_case_interactive_ordinary_failures_preserve_pre_ponr_state",
    "_case_interruption_artifact_preserves_exact_running_and_failed_truth",
    "_case_resume_candidate_parser_fails_closed",
    "_case_phase_one_resume_reuses_exact_run_and_skips_only_prerequisites",
    "_case_two_phase_resume_candidate_fresh_falls_back",
    "_case_phase_two_resume_provenance_factory_is_exact_and_fail_closed",
    "_case_phase_two_provenance_persistence_is_exact_and_not_reusable_by_v1",
    "_case_phase_two_provenance_runtime_wiring_is_exact_and_fail_closed",
    "_case_phase_two_resume_candidate_parser_is_exact_and_unwired",
    "_case_phase_two_resume_selector_requires_exact_current_provenance",
    "_case_phase_two_resume_context_projection_is_exact_and_unwired",
    "_case_headless_phase_two_inputs_require_exact_current_config",
    "_case_headless_phase_two_resume_wiring_skips_exact_prefix_only",
    "_case_phase_result_details_never_persist",
)


class TestInitOrchestratorContractMatrix(unittest.TestCase):
    def test_init_orchestrator_contract_matrix(self):
        run_case_matrix(self, TestInitOrchestratorContract, INIT_ORCHESTRATOR_CASES)


if __name__ == "__main__":
    unittest.main()
