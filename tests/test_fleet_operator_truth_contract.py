"""Operator-truth contracts for fleet placement, probes, and logs.

These tests pin the DC01 regressions found during the VM100 install:
lab physical devices must not appear as core systems, unmanaged
inventory-only rows must not drive doctor/API probe failures, and
optional dashboard enrichment must not look like a service-breaking SSH
error in the logs.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from freq.core.config import load_fleet_boundaries
from tests.case_matrix import run_case_matrix

REPO_ROOT = Path(__file__).parent.parent


class TestFleetPhysicalScope(unittest.TestCase):
    """Fleet-boundary physical devices carry core/lab scope."""

    def test_legacy_lab_physical_scope_is_inferred(self):
        with tempfile.TemporaryDirectory(prefix="freq-physical-scope-") as tmp:
            path = Path(tmp) / "fleet-boundaries.toml"
            path.write_text(
                "\n".join(
                    [
                        "[physical.truenas]",
                        'ip = "10.25.255.2"',
                        'label = "truenas"',
                        'type = "nas"',
                        "",
                        "[physical.truenas_lab]",
                        'ip = "10.25.255.200"',
                        'label = "truenas-lab"',
                        'type = "nas"',
                    ]
                )
            )

            fb = load_fleet_boundaries(str(path))

        self.assertEqual(fb.physical["truenas"].scope, "core")
        self.assertEqual(fb.physical["truenas_lab"].scope, "lab")

    def test_dashboard_splits_lab_physical_from_core(self):
        src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        self.assertIn("_isLabPhysical", src)
        self.assertIn("_normalizeFleetPhysical", src)
        self.assertIn("corePhysicals", src)
        self.assertIn("labPhysicals", src)
        self.assertIn("infraLabels", src)
        self.assertIn("var corePhysical=fo.core_physical||[];", src)
        self.assertIn("var tnDev=corePhysical.find(function(p){return p.type==='truenas'})||null;", src)
        self.assertIn("(fo.core_physical||[]).forEach(function(p)", src)

    def test_fleet_overview_returns_core_physical_as_primary_physical(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        window = src.split("def _bg_probe_fleet_overview", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('"physical": core_physical', window)
        self.assertIn('"core_physical": core_physical', window)
        self.assertIn('"lab_physical": lab_physical', window)
        self.assertIn('"all_physical": physical', window)

    def test_admin_ui_can_assign_device_scope_and_probe_mode(self):
        html = (REPO_ROOT / "freq" / "data" / "web" / "app.html").read_text()
        src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        self.assertIn("Device Assignment", html)
        self.assertIn("PROD, LAB, TEMP, or OOC", html)
        self.assertIn("inventory-only devices stay visible without alerts or doctor degradation", html)
        self.assertIn("var DEVICE_ASSIGNMENT_OPTIONS=", src)
        self.assertIn("{value:'prod',label:'PROD'}", src)
        self.assertIn("{value:'lab',label:'LAB'}", src)
        self.assertIn("{value:'template',label:'TEMP'}", src)
        self.assertIn("{value:'ooc',label:'OOC'}", src)
        self.assertIn("data-action=\"saveDeviceAssignmentRow\"", src)
        self.assertIn("<option value=\"false\"", src)

    def test_fleet_overview_uses_operator_vm_contract_not_deployed_hosts(self):
        from freq.modules import serve
        from freq.services import pve_inventory

        owned_vmids = [100, 101, 102, 103, 104, 105, 999, 5000, 5001, 5002, 5003, 5005, 201, 202, 203, 204, 301]
        out_of_contract = [400, 404, 802, 804, 900, 901, 902, 903]
        cfg = SimpleNamespace(
            hosts=[
                SimpleNamespace(label="plex", htype="docker", managed=True, vmid=101),
            ],
            fleet_boundaries=SimpleNamespace(
                categories={
                    "production": {"tier": "operator", "vmids": [100, 101, 102, 103, 104, 105, 999, 201, 202, 203, 204, 301]},
                    "lab": {"tier": "admin", "vmids": [5000, 5001, 5002, 5003, 5005]},
                    "templates": {"tier": "probe", "vmids": list(range(9000, 9010))},
                    "out_of_contract": {"tier": "probe", "vmids": out_of_contract},
                },
                categorize=lambda vmid: (
                    "out_of_contract" if vmid in out_of_contract
                    else "templates" if vmid >= 9000
                    else "lab" if vmid >= 5000
                    else "production",
                    "probe" if vmid in out_of_contract or vmid >= 9000 else "operator",
                ),
                allowed_actions=lambda vmid: ["view"],
                is_prod=lambda vmid: True,
            ),
        )
        pve_vms = [
            {"vmid": vmid, "name": f"vm-{vmid}", "node": "pve01", "status": "running", "type": "qemu"}
            for vmid in owned_vmids + out_of_contract
        ]
        pve_vms.append({"vmid": 9000, "name": "debian-template", "node": "pve01", "status": "stopped", "type": "qemu"})

        with patch.object(pve_inventory, "_get_discovered_node_ips", return_value=["10.25.255.26"]), \
             patch.object(pve_inventory, "_pve_call", return_value=(pve_vms, True)), \
             patch.object(pve_inventory, "get_vm_tags", return_value=[]):
            result = serve._get_fleet_vms(cfg)

        vmids = {v["vmid"] for v in result}
        self.assertEqual(set(owned_vmids) | {9000}, vmids)
        self.assertFalse(set(out_of_contract) & vmids)

    def test_init_records_inventory_without_prefilling_operator_categories(self):
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory(prefix="freq-inventory-unknown-") as tmp:
            boundaries = Path(tmp) / "fleet-boundaries.toml"
            original = (
                "[categories.operator_choice]\n"
                'description = "Explicit choice"\n'
                'tier = "probe"\n'
                "vmids = [777]\n"
            )
            boundaries.write_text(original)
            key_path = Path(tmp) / "fleet-key"
            key_path.write_text("test-key")
            cfg = SimpleNamespace(
                conf_dir=tmp,
                pve_nodes=["10.25.255.26"],
                hosts=[SimpleNamespace(
                    ip="192.0.2.77", label="inventory-only", htype="linux", managed=False,
                )],
                ssh_key_path=str(key_path),
                ssh_service_account="freq-admin",
            )
            resources = [
                {"vmid": 106, "name": "prod-looking", "type": "qemu", "tags": "prod"},
                {"vmid": 5005, "name": "lab-looking", "type": "qemu", "tags": "dev"},
            ]

            with patch.object(
                init_cmd, "normalize_owned_install_root"
            ), patch.object(init_cmd, "_fetch_pve_resources", return_value=resources):
                init_cmd._phase_fleet_configure(cfg, {})

            inventory = (Path(tmp) / "pve-inventory.toml").read_text()
            self.assertEqual(boundaries.read_text(), original)

        self.assertIn('name = "prod-looking"', inventory)
        self.assertIn('name = "lab-looking"', inventory)
        self.assertNotIn("categories.", inventory)

    def test_init_accepts_operator_vm_contract_toml(self):
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory(prefix="freq-vm-contract-") as tmp:
            contract = Path(tmp) / "vm-contract.toml"
            contract.write_text(
                "\n".join(
                    [
                        "[fleet]",
                        "owned_vmids = [100, 101, 102, 103, 104, 105, 999, 5000, 5001, 5002, 5003, 5005, 201, 202, 203, 204, 301]",
                        'template_vmids = ["9000-9009"]',
                        "acknowledged_out_of_contract_vmids = [400, 404, 802, 804, 900, 901, 902, 903]",
                    ]
                )
            )
            cfg = SimpleNamespace()
            args = SimpleNamespace(
                vm_contract=str(contract),
                owned_vmids=None,
                template_vmids=None,
                acknowledged_out_of_contract_vmids=None,
            )

            init_cmd._apply_operator_vm_contract_args(cfg, args)

        self.assertEqual(
            {100, 101, 102, 103, 104, 105, 999, 5000, 5001, 5002, 5003, 5005, 201, 202, 203, 204, 301},
            cfg._owned_vmids,
        )
        self.assertEqual(set(range(9000, 9010)), cfg._contract_template_vmids)
        self.assertEqual({400, 404, 802, 804, 900, 901, 902, 903}, cfg._acknowledged_out_of_contract_vmids)

    def test_unassigned_inventory_has_no_init_failure_gate(self):
        src = (REPO_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("acknowledged_out_of_contract_vmids", src)
        self.assertNotIn("def _categorize_vms", src)
        self.assertNotIn("Auto-categorized VM groups", src)
        self.assertNotIn("Unexpected out-of-contract PVE VMs discovered", src)
        self.assertNotIn("0 unexpected out-of-contract PVE VMs", src)


class TestFleetProbeNoiseContract(unittest.TestCase):
    """Probe/log code must preserve operator truth."""

    def _case_doctor_uses_managed_hosts_only(self):
        src = (REPO_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("from freq.core.host_scope import managed_probe_hosts", src)
        self.assertIn("return managed_probe_hosts(cfg)", src)
        service_block = src.split("def _check_service_account", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("hosts_for_check = [", service_block)
        self.assertIn("_doctor_managed_hosts(cfg)", service_block)
        self.assertIn("h.htype in service_account_htypes", service_block)

    def _case_operator_doctor_does_not_fake_fleet_outage_without_service_key(self):
        src = (REPO_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("service-owned keys live in", src)
        self.assertIn("Run `sudo -u {svc} freq doctor` or use /api/doctor", src)
        self.assertIn("Service account '{svc}': not checked from", src)

    def _case_api_health_fallback_uses_managed_hosts_only(self):
        src = (REPO_ROOT / "freq" / "api" / "fleet.py").read_text()
        self.assertIn("active_hosts = managed_probe_hosts(cfg)", src)
        self.assertIn("pool.submit(_probe_host, h): h for h in active_hosts", src)
        self.assertIn("hosts = managed_probe_hosts(cfg)", src)

    def _case_init_deploy_phase_uses_managed_hosts_only(self):
        src = (REPO_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("managed_hosts = [h for h in cfg.hosts if getattr(h, \"managed\", True)]", src)
        self.assertIn("linux_hosts = [h for h in managed_hosts", src)

    def _case_optional_dashboard_enrichment_downgrades_ssh_log_severity(self):
        ssh_src = (REPO_ROOT / "freq" / "core" / "ssh.py").read_text()
        serve_src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("failure_log_level: str = \"error\"", ssh_src)
        self.assertIn("optional=normalized_failure_log_level not in", ssh_src)
        self.assertGreaterEqual(serve_src.count('failure_log_level="warn"'), 2)

    def _case_health_probe_completion_logs_state_counts_not_catchall_unreachable(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("state_counts = {", src)
        self.assertIn("stale=state_counts[STATE_STALE]", src)
        self.assertIn("auth_failed=state_counts[STATE_AUTH_FAILED]", src)
        self.assertIn("unreachable=state_counts[STATE_UNREACHABLE]", src)
        self.assertIn('f"{h_e[\'label\']} is now {cur_state}"', src)
        self.assertNotIn('unreachable_count = sum(1 for h in host_data if h.get("status") != "healthy")', src)

    def _case_tls_client_disconnects_do_not_print_tracebacks(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        server_window = src.split("class ThreadedHTTPServer", 1)[1].split("# ── CONSTANTS", 1)[0]
        self.assertIn("def handle_error", server_window)
        self.assertIn("ssl.SSLError", server_window)
        self.assertIn("UNEXPECTED_EOF_WHILE_READING", server_window)
        self.assertIn("tls_client_disconnect", server_window)
        self.assertIn("super().handle_error", server_window)

    def _case_web_runtime_logs_every_request_with_correlation_id(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("def _begin_request", src)
        self.assertIn("uuid.uuid4().hex[:12]", src)
        self.assertIn("http_request_start", src)
        self.assertIn("http_request_end", src)
        self.assertIn("X-Request-ID", src)
        self.assertIn("duration_ms", src)
        self.assertIn("bytes=getattr(self, \"_response_bytes\", None)", src)

    def _case_handler_errors_are_structured_not_raw_traceback_prints(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        dispatch_window = src.split("def _dispatch", 1)[1].split("def do_GET", 1)[0]
        self.assertIn("http_handler_exception", dispatch_window)
        self.assertIn("traceback=traceback.format_exc()", dispatch_window)
        self.assertIn('"request_id": getattr(self, "_request_id", "")', dispatch_window)
        self.assertNotIn("traceback.print_exc()", dispatch_window)

    def _case_json_error_responses_include_request_id(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        json_window = src.split("def _json_response", 1)[1].split("# --- Phase 1", 1)[0]
        self.assertIn('if isinstance(data, dict) and "error" in data and "request_id" not in data:', json_window)
        self.assertIn('data["request_id"] = getattr(self, "_request_id", "")', json_window)

    def _case_runtime_exception_hooks_are_installed(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("def _install_runtime_exception_hooks", src)
        self.assertIn("runtime_uncaught_exception", src)
        self.assertIn("runtime_thread_exception", src)
        self.assertIn("threading.excepthook = _thread_excepthook", src)
        self.assertIn("_install_runtime_exception_hooks()", src.split("def start_background_cache", 1)[1].split("# These imports intentionally", 1)[0])

    def _case_auth_helper_attaches_actor_for_request_logs(self):
        src = (REPO_ROOT / "freq" / "api" / "auth.py").read_text()
        self.assertIn("handler._session_user = session[\"user\"]", src)
        self.assertIn("handler._session_role = session[\"role\"]", src)

    def _case_domain_api_errors_include_request_id(self):
        src = (REPO_ROOT / "freq" / "api" / "helpers.py").read_text()
        self.assertIn('if isinstance(data, dict) and "error" in data and "request_id" not in data:', src)
        self.assertIn('request_id = getattr(handler, "_request_id", "")', src)
        self.assertIn('data["request_id"] = request_id', src)

    def _case_runtime_log_api_exposes_local_structured_logs(self):
        src = (REPO_ROOT / "freq" / "api" / "logs.py").read_text()
        self.assertIn("def handle_logs_runtime", src)
        self.assertIn('routes["/api/logs/runtime"] = handle_logs_runtime', src)
        self.assertIn('with open(cfg.log_file, "r"', src)
        self.assertIn('request_id and row.get("request_id") != request_id', src)
        self.assertIn('"entries": rows', src)

    def _case_fleet_overview_uses_device_appropriate_physical_reachability(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        window = src.split("def _bg_probe_fleet_overview", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("def _physical_reachable(dev):", window)
        self.assertIn('dtype in {"pfsense", "opnsense"}', window)
        self.assertIn("return _tcp_check(dev.ip, (443, 80, 22)) or _icmp_check(dev.ip)", window)
        self.assertIn('["ping", "-c", "1", "-W", "1", ip]', window)
        self.assertNotIn('["ping", "-c", "1", "-W", "1", dev.ip]', window)

    def _case_fleet_overview_enriches_physical_identity_with_bounded_snmp(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        window = src.split("def _bg_probe_fleet_overview", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("SNMP_IDENTITY_CACHE_TTL", src)
        self.assertIn("def _snmp_identity_for_physical(dev, reachable):", window)
        self.assertIn('timeout=2', window)
        self.assertIn('if not auth.get("user") and dtype not in {"idrac", "bmc", "ilo", "ipmi"}:', window)
        self.assertIn('"display_label": display_label', window)
        self.assertIn('"identity_label": identity_label', window)
        self.assertIn('item["snmp_identity"] = identity', window)
        self.assertIn('item["identity_source"] = "snmp"', window)
        self.assertIn('re.match(r"^(bmc|idrac|ilo|ipmi)[-_]?\\d+$", label)', window)

    def _case_frontend_does_not_count_stale_as_down(self):
        src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        self.assertIn("function _healthIsLive", src)
        self.assertIn("function _healthIsBad", src)
        self.assertIn("function _healthLabel", src)
        self.assertIn("if(_healthIsLive(h))up++;else if(_healthIsBad(h))down++;", src)
        self.assertIn("if(_healthIsLive(h))totalUp++;else if(_healthIsBad(h))totalDown++;", src)
        self.assertNotIn("var psBad=(ps==='stale'", src)
        self.assertNotIn("var fpsBad=(fps==='stale'", src)
        self.assertNotIn("status==='healthy'", src)
        self.assertNotIn('status === "healthy"', src)

    def _case_frontend_health_change_toast_keeps_stale_out_of_down(self):
        src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        self.assertIn("ns==='stale'?'STALE'", src)
        self.assertIn("(ns==='stale'||ns==='degraded')?'warn':'error'", src)
        self.assertIn("_recordBackgroundProbeEvent(d.host+': SSH probe '+label+detail,kind", src)
        self.assertNotIn("var label=d['new']==='healthy'?'UP':'DOWN';", src)

    def _case_background_probe_events_do_not_corner_toast(self):
        src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        self.assertIn("function _recordBackgroundProbeEvent", src)
        health_window = src.split("_evtSource.addEventListener('health_change'", 1)[1].split("_evtSource.addEventListener('probe_error'", 1)[0]
        probe_window = src.split("_evtSource.addEventListener('probe_error'", 1)[1].split("_evtSource.addEventListener('vm_state'", 1)[0]
        fleet_window = src.split("/* Fleet data freshness", 1)[1].split("}).catch(function()", 1)[0]
        self.assertNotIn("toast(", health_window)
        self.assertNotIn("toast(", probe_window)
        self.assertNotIn("toast(", fleet_window)

    def _case_legacy_rate_limit_health_changes_are_not_toast_events(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("def _is_routine_legacy_health_change", src)
        self.assertIn("def _reuse_skipped_health", src)
        self.assertIn('htype: str = ""', src)
        self.assertIn('"legacy-device rate limit" in prev_reason', src)
        self.assertIn('"legacy-device rate limit" in (skip_reason or "")', src)
        self.assertIn('reused["freshness"] = "rate_limited"', src)
        self.assertIn('reused["freshness_reason"] = skip_reason', src)
        self.assertIn("metrics_probe_noise", src)
        self.assertIn('"probe parse error" in cur_reason', src)
        self.assertIn("h_e.get(\"type\", \"\")", src)
        self.assertIn("health_change_suppressed", src)
        self.assertIn("continue", src.split("health_change_suppressed", 1)[1].split("_sse_broadcast(\"health_change\"", 1)[0])

    def _case_legacy_command_timeout_keeps_network_truth(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        window = src.split("def _bg_probe_health", 1)[1].split("\ndef _bg_probe_update", 1)[0]
        self.assertIn("def _legacy_network_reachable(h):", window)
        self.assertIn("socket.create_connection((h.ip, 22)", window)
        self.assertIn('["ping", "-c", "1", "-W", "1", h.ip]', window)
        self.assertIn("if htype in LEGACY_HTYPES and state == STATE_UNREACHABLE and _legacy_network_reachable(h):", window)
        self.assertIn("state = STATE_DEGRADED", window)
        self.assertIn("legacy device reachable; metrics probe failed", window)

    def _case_infra_quick_reuses_recent_legacy_success(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        window = src.split("def _bg_probe_infra", 1)[1].split("\ndef _bg_probe_health", 1)[0]
        self.assertIn("def _reuse_recent_infra_device_success", src)
        self.assertIn('reused["probe_method"] = "recent_success_reused"', src)
        self.assertIn("previous_devices", window)
        self.assertIn('item.setdefault("probed_at", previous_probed_at)', window)
        self.assertIn("def _reuse_recent_device(reason):", window)
        self.assertIn("except subprocess.TimeoutExpired as e:", window)
        self.assertIn("return reused", window)

    def _case_api_doctor_is_serialized_and_short_cached(self):
        import json
        import sys
        from ast import Attribute, Call, FunctionDef, Import, ImportFrom, Name, parse, walk
        from unittest.mock import MagicMock

        from freq.services import dashboard_doctor
        from tests.test_parity import _get_json, _make_handler

        def attribute_path(node):
            if isinstance(node, Name):
                return node.id
            if isinstance(node, Attribute):
                parent = attribute_path(node.value)
                return f"{parent}.{node.attr}" if parent else node.attr
            return ""

        serve_tree = parse((REPO_ROOT / "freq/modules/serve.py").read_text())
        service_tree = parse(
            (REPO_ROOT / "freq/services/dashboard_doctor.py").read_text()
        )
        service_imports = set()
        for node in walk(service_tree):
            if isinstance(node, Import):
                service_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ImportFrom) and node.module:
                service_imports.add(node.module)
        self.assertEqual(
            service_imports,
            {
                "contextlib",
                "freq.core.config",
                "freq.core",
                "io",
                "json",
                "threading",
                "time",
            },
        )
        handler_node = next(
            node
            for node in walk(serve_tree)
            if isinstance(node, FunctionDef) and node.name == "_serve_doctor"
        )
        self.assertEqual(len(handler_node.body), 2)
        handler_calls = {
            attribute_path(node.func)
            for node in walk(handler_node)
            if isinstance(node, Call)
        }
        self.assertIn("_dashboard_doctor.run_dashboard_doctor", handler_calls)
        self.assertNotIn("doctor.run", handler_calls)
        self.assertNotIn("time.monotonic", handler_calls)

        warm = {"status": "ok", "reason": "cached"}
        warm_lock = MagicMock()
        with (
            patch.object(dashboard_doctor, "_cache", warm),
            patch.object(dashboard_doctor, "_cache_ts", 90),
            patch.object(dashboard_doctor, "_CACHE_TTL", 15),
            patch.object(dashboard_doctor, "_CACHE_LOCK", warm_lock),
            patch(
                "freq.services.dashboard_doctor.time.monotonic",
                return_value=100,
            ) as monotonic,
            patch("freq.services.dashboard_doctor.load_config") as load_config,
            patch("freq.core.doctor.run") as doctor_run,
        ):
            handler = _make_handler("/api/doctor")
            handler._serve_doctor()
            self.assertEqual((_get_json(handler), handler._status_code), (warm, 200))
            monotonic.assert_called_once_with()
            warm_lock.__enter__.assert_not_called()
            load_config.assert_not_called()
            doctor_run.assert_not_called()

        raced = {"status": "degraded", "reason": "published while waiting"}

        class PublishCacheOnEnter:
            def __enter__(self):
                dashboard_doctor._cache = raced
                dashboard_doctor._cache_ts = 95

            def __exit__(self, exc_type, exc, traceback):
                return False

        with (
            patch.object(dashboard_doctor, "_cache", None),
            patch.object(dashboard_doctor, "_cache_ts", 0),
            patch.object(dashboard_doctor, "_CACHE_TTL", 15),
            patch.object(dashboard_doctor, "_CACHE_LOCK", PublishCacheOnEnter()),
            patch(
                "freq.services.dashboard_doctor.time.monotonic",
                side_effect=(100, 101),
            ) as monotonic,
            patch("freq.services.dashboard_doctor.load_config") as load_config,
            patch("freq.core.doctor.run") as doctor_run,
        ):
            handler = _make_handler("/api/doctor")
            handler._serve_doctor()
            self.assertEqual((_get_json(handler), handler._status_code), (raced, 200))
            self.assertEqual(monotonic.call_count, 2)
            load_config.assert_not_called()
            doctor_run.assert_not_called()

        cfg = object()
        parsed = {
            "status": "ok",
            "reason": "all checks passed",
            "checked_at": 123.5,
        }

        def emit_json(actual_cfg, *, json_output=False):
            self.assertIs(actual_cfg, cfg)
            self.assertIs(json_output, True)
            sys.stdout.write(json.dumps(parsed))
            return 0

        parse_lock = MagicMock()
        with (
            patch.object(dashboard_doctor, "_cache", None),
            patch.object(dashboard_doctor, "_cache_ts", 0),
            patch.object(dashboard_doctor, "_CACHE_TTL", 15),
            patch.object(dashboard_doctor, "_CACHE_LOCK", parse_lock),
            patch(
                "freq.services.dashboard_doctor.time.monotonic",
                side_effect=(200, 201, 202),
            ) as monotonic,
            patch(
                "freq.services.dashboard_doctor.load_config",
                return_value=cfg,
            ) as load_config,
            patch(
                "freq.core.doctor.run",
                side_effect=emit_json,
            ) as doctor_run,
        ):
            handler = _make_handler("/api/doctor")
            handler._serve_doctor()
            self.assertEqual((_get_json(handler), handler._status_code), (parsed, 200))
            self.assertEqual(dashboard_doctor._cache, parsed)
            self.assertEqual(dashboard_doctor._cache_ts, 202)
            self.assertEqual(monotonic.call_count, 3)
            parse_lock.__enter__.assert_called_once_with()
            load_config.assert_called_once_with()
            doctor_run.assert_called_once_with(cfg, json_output=True)

        raw_output = "doctor emitted non-json output\n"
        for result, expected_ok in ((0, True), (7, False)):
            def emit_invalid(actual_cfg, *, json_output=False, exit_code=result):
                self.assertIs(actual_cfg, cfg)
                self.assertIs(json_output, True)
                sys.stdout.write(raw_output)
                return exit_code

            with (
                patch.object(dashboard_doctor, "_cache", None),
                patch.object(dashboard_doctor, "_cache_ts", 0),
                patch.object(dashboard_doctor, "_CACHE_TTL", 15),
                patch.object(dashboard_doctor, "_CACHE_LOCK", MagicMock()),
                patch(
                    "freq.services.dashboard_doctor.time.monotonic",
                    side_effect=(300, 301, 302),
                ),
                patch("freq.services.dashboard_doctor.load_config", return_value=cfg),
                patch(
                    "freq.core.doctor.run",
                    side_effect=emit_invalid,
                ),
            ):
                handler = _make_handler("/api/doctor")
                handler._serve_doctor()
                expected = {
                    "ok": expected_ok,
                    "output": raw_output,
                    "exit_code": result,
                }
                self.assertEqual(
                    (_get_json(handler), handler._status_code),
                    (expected, 200),
                )
                self.assertEqual(dashboard_doctor._cache, expected)
                self.assertEqual(dashboard_doctor._cache_ts, 302)

        with (
            patch.object(dashboard_doctor, "_cache", None),
            patch.object(dashboard_doctor, "_cache_ts", 0),
            patch.object(dashboard_doctor, "_CACHE_TTL", 15),
            patch.object(dashboard_doctor, "_CACHE_LOCK", MagicMock()),
            patch(
                "freq.services.dashboard_doctor.time.monotonic",
                side_effect=(400, 401),
            ),
            patch("freq.services.dashboard_doctor.load_config", return_value=cfg),
            patch(
                "freq.core.doctor.run",
                side_effect=RuntimeError("doctor unavailable"),
            ),
        ):
            handler = _make_handler("/api/doctor")
            handler._serve_doctor()
            self.assertEqual(
                (_get_json(handler), handler._status_code),
                (
                    {
                        "error": "Doctor failed: doctor unavailable",
                        "request_id": "",
                    },
                    500,
                ),
            )
            self.assertIsNone(dashboard_doctor._cache)
            self.assertEqual(dashboard_doctor._cache_ts, 0)

    def _case_fleet_doctor_is_cross_process_serialized(self):
        src = (REPO_ROOT / "freq" / "core" / "doctor.py").read_text()
        window = src.split("def _check_fleet_connectivity", 1)[1].split("\ndef _check_service_account", 1)[0]
        self.assertIn("def _doctor_fleet_lock", src)
        self.assertIn("fcntl.flock", src)
        self.assertIn("doctor-fleet-connectivity.lock", src)
        self.assertIn("with _doctor_fleet_lock(cfg):", window)

    def _case_ui_toasts_are_logged_to_server(self):
        src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        serve_src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("function _uiLog", src)
        self.assertIn("fetch('/api/ui/event'", src)
        self.assertIn("_uiLog('toast'", src)
        self.assertIn('"/api/ui/event": "_serve_ui_event"', serve_src)
        self.assertIn("logger.info(\n            \"ui_event\"", serve_src)
        self.assertIn("ui_level=level", serve_src)
        self.assertNotIn("\n            level=level,", serve_src)
        serve_window = serve_src.split("def _serve_ui_event", 1)[1].split("    # \u2500\u2500 Topology", 1)[0]
        self.assertNotIn("_activity_add(\"ui_toast\"", serve_window)
        self.assertIn("function _activityShouldToast", src)
        self.assertIn("t==='ui_toast'||t==='health_change'||t==='probe_error'", src)

    def _case_core_system_cards_open_infra_detail_without_cache_lookup(self):
        src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        self.assertIn('data-action="openInfraDevice"', src)
        self.assertIn("data-infra-type", src)
        self.assertIn(
            "openCard('infra',{label:da.dataset.label,display_name:da.dataset.displayName||'',display_label:da.dataset.displayLabel||'',raw_label:da.dataset.rawLabel||da.dataset.label,infraType:da.dataset.infraType,ip:da.dataset.ip})",
            src,
        )
        self.assertIn("if(!ph&&config.ip)ph={label:label,type:infraType,ip:config.ip", src)

    def _case_infra_quick_reconciles_reachability_with_fleet_overview(self):
        src = (REPO_ROOT / "freq" / "api" / "fleet.py").read_text()
        window = src.split("def handle_infra_quick", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('fleet_overview = _bg_cache.get("fleet_overview")', window)
        self.assertIn("physical_reachability", window)
        self.assertIn('item["reachable"] = True', window)
        self.assertIn('item["network_reachable"] = True', window)
        self.assertIn('item["reachability_source"] = "fleet_overview"', window)
        self.assertIn("auth_failed=bool(item.get(\"auth_failed\"))", window)
        self.assertIn("infra_quick_reachability_reconciled", window)

    def _case_truenas_quick_card_uses_api_key_truth(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        web_src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        helper_src = (REPO_ROOT / "freq" / "core" / "truenas_api.py").read_text()
        self.assertIn("from freq.core import", src)
        self.assertIn("truenas_api", src)
        self.assertIn('truenas_api.request(api_settings, "pools"', src)
        self.assertIn('d["probe_method"] = "truenas_api_key"', src)
        self.assertIn('d["probe_method"] = "ssh"', src)
        self.assertIn('resolve_staged_device_ssh_auth(cfg, "truenas")', src)
        self.assertIn("TrueNAS API key missing", helper_src)
        self.assertIn("pool_metrics", helper_src)
        self.assertIn("_m('REACHABLE','NETWORK','var(--green)')", web_src)
        self.assertIn("METRICS UNAVAILABLE", web_src)
        self.assertIn("dev.type==='truenas'?'API':'SSH'", web_src)

    def _case_status_api_uses_device_aware_health_cache(self):
        src = (REPO_ROOT / "freq" / "api" / "fleet.py").read_text()
        block = src.split("def handle_status", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('cached_health = _bg_cache.get("health")', block)
        self.assertIn('"source": "health_cache"', block)
        self.assertIn("STATE_AUTH_FAILED", block)
        self.assertIn("STATE_UNREACHABLE", block)

    def _case_truenas_settings_can_read_api_key_file(self):
        from freq.core import truenas_api

        with tempfile.TemporaryDirectory(prefix="freq-truenas-key-") as tmp:
            tmp_path = Path(tmp)
            key_path = tmp_path / "truenas.key"
            key_path.write_text("tn-test-secret\n")
            (tmp_path / "freq.toml").write_text(
                "\n".join(
                    [
                        "[truenas]",
                        'type = "api_key"',
                        'url = "https://10.0.0.25/api/v2.0"',
                        f'api_key_file = "{key_path}"',
                        'api_key_ref = "secrets://should-not-win"',
                    ]
                )
            )
            cfg = SimpleNamespace(conf_dir=str(tmp_path), vault_file=str(tmp_path / "vault.enc"))
            target = SimpleNamespace(ip="10.0.0.25", label="truenas", key="truenas")

            settings = truenas_api.settings(cfg, target)

        self.assertEqual(settings["api_key"], "tn-test-secret")
        self.assertEqual(settings["api_key_file"], str(key_path))
        self.assertEqual(settings["secret_ns"], "should-not-win")

    def _case_infra_overview_does_not_probe_physical_devices_as_linux(self):
        src = (REPO_ROOT / "freq" / "api" / "fleet.py").read_text()
        self.assertIn('physical_types = {"truenas", "switch", "idrac"}', src)
        self.assertIn("shell_hosts = [h for h in cfg.hosts if h.htype not in physical_types]", src)
        self.assertIn("quick_by_label", src)
        self.assertIn("quick_by_ip", src)
        self.assertIn('"hostname": h.label', src)
        self.assertIn('"status": status', src)

    def _case_core_physical_hosts_cannot_hide_as_unmanaged(self):
        doctor_src = (REPO_ROOT / "freq" / "core" / "doctor.py").read_text()
        init_src = (REPO_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        hosts_src = (REPO_ROOT / "freq" / "modules" / "hosts.py").read_text()
        self.assertIn("core physical host(s) marked unmanaged", doctor_src)
        self.assertNotIn('if dev_type == "truenas":\n                continue', doctor_src)
        self.assertIn("is core physical infrastructure", init_src)
        self.assertIn("leaving managed so doctor/verify must fail", init_src)
        self.assertIn('"managed": dev.scope != "lab"', hosts_src)
        self.assertIn('managed=d.get("managed", True)', hosts_src)

    def _case_truenas_action_endpoint_is_action_aware_and_truthful(self):
        src = (REPO_ROOT / "freq" / "api" / "store.py").read_text()
        helper_src = (REPO_ROOT / "freq" / "core" / "truenas_api.py").read_text()
        self.assertIn("read_actions = {", src)
        self.assertIn('"pools": "zpool list -v"', src)
        self.assertIn("truenas_api.settings(cfg, target)", src)
        self.assertIn("truenas_api.request(api_settings, action)", src)
        self.assertIn("api_action_supported = truenas_api.action_endpoint(action) is not None", src)
        self.assertIn("if api_action_supported and", src)
        self.assertIn('{"system": "status", "log": "syslog"}.get(action, action)', src)
        self.assertIn("resolve_staged_device_ssh_auth", src)
        self.assertIn("sudo_password_file=auth.get", src)
        self.assertIn("truenas_api_key", helper_src + src)
        self.assertIn('"snapshots": ("GET", "/pool/snapshot")', helper_src)
        self.assertNotIn("/zfs/snapshot", helper_src)
        self.assertIn('if action == "snapshots" and isinstance(data, list):', helper_src)
        self.assertIn("Showing first 120 snapshots", helper_src)
        self.assertIn("ssh_auth_failed_ping", src)
        self.assertIn('"ssh_available": False', src)
        self.assertIn('failure_log_level="warn"', src)
        self.assertIn("use_sudo=True", src)

    def _case_doctor_checks_truenas_api_key_path(self):
        src = (REPO_ROOT / "freq" / "core" / "doctor.py").read_text()
        helper_src = (REPO_ROOT / "freq" / "core" / "truenas_api.py").read_text()
        self.assertIn("def _check_truenas_api_credentials", src)
        self.assertIn("_check_truenas_api_credentials", src)
        self.assertIn("TrueNAS API key missing", src)
        self.assertIn("truenas_api.settings(cfg, dev)", src)
        self.assertIn('vault_get(cfg, secret_ns, "api_key")', helper_src)

    def _case_init_device_credentials_can_carry_truenas_api_key(self):
        from freq.modules.init_cmd import _load_device_credentials

        with tempfile.TemporaryDirectory(prefix="freq-init-tn-creds-") as tmp:
            tmp_path = Path(tmp)
            key_path = tmp_path / "truenas-api.key"
            key_path.write_text("tn-init-secret\n")
            creds_path = tmp_path / "device-creds.toml"
            creds_path.write_text(
                "\n".join(
                    [
                        "[truenas]",
                        'user = "root"',
                        f'api_key_file = "{key_path}"',
                    ]
                )
            )

            creds = _load_device_credentials(str(creds_path))

        self.assertIn("truenas", creds)
        self.assertEqual(creds["truenas"]["api_key"], "tn-init-secret")
        self.assertTrue(creds["truenas"]["api_key_only"])

    def _case_init_persists_truenas_api_key_to_runtime_vault(self):
        src = (REPO_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("def _seed_truenas_api_key_from_device_creds", src)
        self.assertIn('vault_set(cfg, namespace, "api_key", api_key)', src)
        self.assertIn("_seed_truenas_api_key_from_device_creds(cfg, device_creds)", src)


FLEET_OPERATOR_TRUTH_CASES = (
    "_case_doctor_uses_managed_hosts_only",
    "_case_operator_doctor_does_not_fake_fleet_outage_without_service_key",
    "_case_api_health_fallback_uses_managed_hosts_only",
    "_case_init_deploy_phase_uses_managed_hosts_only",
    "_case_optional_dashboard_enrichment_downgrades_ssh_log_severity",
    "_case_health_probe_completion_logs_state_counts_not_catchall_unreachable",
    "_case_tls_client_disconnects_do_not_print_tracebacks",
    "_case_web_runtime_logs_every_request_with_correlation_id",
    "_case_handler_errors_are_structured_not_raw_traceback_prints",
    "_case_json_error_responses_include_request_id",
    "_case_runtime_exception_hooks_are_installed",
    "_case_auth_helper_attaches_actor_for_request_logs",
    "_case_domain_api_errors_include_request_id",
    "_case_runtime_log_api_exposes_local_structured_logs",
    "_case_fleet_overview_uses_device_appropriate_physical_reachability",
    "_case_fleet_overview_enriches_physical_identity_with_bounded_snmp",
    "_case_frontend_does_not_count_stale_as_down",
    "_case_frontend_health_change_toast_keeps_stale_out_of_down",
    "_case_background_probe_events_do_not_corner_toast",
    "_case_legacy_rate_limit_health_changes_are_not_toast_events",
    "_case_legacy_command_timeout_keeps_network_truth",
    "_case_infra_quick_reuses_recent_legacy_success",
    "_case_api_doctor_is_serialized_and_short_cached",
    "_case_fleet_doctor_is_cross_process_serialized",
    "_case_ui_toasts_are_logged_to_server",
    "_case_core_system_cards_open_infra_detail_without_cache_lookup",
    "_case_infra_quick_reconciles_reachability_with_fleet_overview",
    "_case_truenas_quick_card_uses_api_key_truth",
    "_case_status_api_uses_device_aware_health_cache",
    "_case_truenas_settings_can_read_api_key_file",
    "_case_infra_overview_does_not_probe_physical_devices_as_linux",
    "_case_core_physical_hosts_cannot_hide_as_unmanaged",
    "_case_truenas_action_endpoint_is_action_aware_and_truthful",
    "_case_doctor_checks_truenas_api_key_path",
    "_case_init_device_credentials_can_carry_truenas_api_key",
    "_case_init_persists_truenas_api_key_to_runtime_vault",
)

class TestFleetOperatorTruthMatrix(unittest.TestCase):
    def test_fleet_operator_truth_matrix(self):
        self.assertEqual(len(FLEET_OPERATOR_TRUTH_CASES), 36)
        run_case_matrix(self, TestFleetProbeNoiseContract, FLEET_OPERATOR_TRUTH_CASES)


if __name__ == "__main__":
    unittest.main()
