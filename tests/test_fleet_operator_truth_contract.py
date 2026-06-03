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

from freq.core.config import load_fleet_boundaries


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
        self.assertIn("corePhysicals", src)
        self.assertIn("labPhysicals", src)
        self.assertIn("infraLabels", src)
        self.assertIn("var corePhysical=fo.physical?fo.physical.filter(function(p){return !_isLabPhysical(p);}):[];", src)
        self.assertIn("var tnDev=corePhysical.find(function(p){return p.type==='truenas'})||null;", src)
        self.assertIn("(fo.physical||[]).filter(function(p){return !_isLabPhysical(p);}).forEach(function(p)", src)


class TestFleetProbeNoiseContract(unittest.TestCase):
    """Probe/log code must preserve operator truth."""

    def test_doctor_uses_managed_hosts_only(self):
        src = (REPO_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("hosts = [h for h in cfg.hosts if getattr(h, \"managed\", True)]", src)
        self.assertIn("hosts_for_check = [h for h in cfg.hosts if getattr(h, \"managed\", True)]", src)

    def test_operator_doctor_does_not_fake_fleet_outage_without_service_key(self):
        src = (REPO_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("service-owned keys live in", src)
        self.assertIn("Run `sudo -u {svc} freq doctor` or use /api/doctor", src)
        self.assertIn("Service account '{svc}': not checked from", src)

    def test_api_health_fallback_uses_managed_hosts_only(self):
        src = (REPO_ROOT / "freq" / "api" / "fleet.py").read_text()
        self.assertIn("active_hosts = [h for h in cfg.hosts if getattr(h, \"managed\", True)]", src)
        self.assertIn("pool.submit(_probe_host, h): h for h in active_hosts", src)
        self.assertIn("hosts = [h for h in cfg.hosts if getattr(h, \"managed\", True)]", src)

    def test_init_deploy_phase_uses_managed_hosts_only(self):
        src = (REPO_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("managed_hosts = [h for h in cfg.hosts if getattr(h, \"managed\", True)]", src)
        self.assertIn("linux_hosts = [h for h in managed_hosts", src)

    def test_optional_dashboard_enrichment_downgrades_ssh_log_severity(self):
        ssh_src = (REPO_ROOT / "freq" / "core" / "ssh.py").read_text()
        serve_src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("failure_log_level: str = \"error\"", ssh_src)
        self.assertIn("optional=normalized_failure_log_level not in", ssh_src)
        self.assertGreaterEqual(serve_src.count('failure_log_level="warn"'), 2)

    def test_health_probe_completion_logs_state_counts_not_catchall_unreachable(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("state_counts = {", src)
        self.assertIn("stale=state_counts[STATE_STALE]", src)
        self.assertIn("auth_failed=state_counts[STATE_AUTH_FAILED]", src)
        self.assertIn("unreachable=state_counts[STATE_UNREACHABLE]", src)
        self.assertIn('f"{h_e[\'label\']} is now {cur_state}"', src)
        self.assertNotIn('unreachable_count = sum(1 for h in host_data if h.get("status") != "healthy")', src)

    def test_tls_client_disconnects_do_not_print_tracebacks(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        server_window = src.split("class ThreadedHTTPServer", 1)[1].split("# ── CONSTANTS", 1)[0]
        self.assertIn("def handle_error", server_window)
        self.assertIn("ssl.SSLError", server_window)
        self.assertIn("UNEXPECTED_EOF_WHILE_READING", server_window)
        self.assertIn("tls_client_disconnect", server_window)
        self.assertIn("super().handle_error", server_window)

    def test_fleet_overview_uses_device_appropriate_physical_reachability(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        window = src.split("def _bg_probe_fleet_overview", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("def _physical_reachable(dev):", window)
        self.assertIn('dtype in {"pfsense", "opnsense"}', window)
        self.assertIn("return _tcp_check(dev.ip, (443, 80, 22)) or _icmp_check(dev.ip)", window)
        self.assertIn('["ping", "-c", "1", "-W", "1", ip]', window)
        self.assertNotIn('["ping", "-c", "1", "-W", "1", dev.ip]', window)

    def test_frontend_does_not_count_stale_as_down(self):
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

    def test_frontend_health_change_toast_keeps_stale_out_of_down(self):
        src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        self.assertIn("ns==='stale'?'STALE'", src)
        self.assertIn("(ns==='stale'||ns==='degraded')?'warn':'error'", src)
        self.assertNotIn("var label=d['new']==='healthy'?'UP':'DOWN';", src)

    def test_legacy_rate_limit_health_changes_are_not_toast_events(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("def _is_routine_legacy_health_change", src)
        self.assertIn('htype: str = ""', src)
        self.assertIn('"legacy-device rate limit" in prev_reason', src)
        self.assertIn("metrics_probe_noise", src)
        self.assertIn("h_e.get(\"type\", \"\")", src)
        self.assertIn("health_change_suppressed", src)
        self.assertIn("continue", src.split("health_change_suppressed", 1)[1].split("_sse_broadcast(\"health_change\"", 1)[0])

    def test_legacy_command_timeout_keeps_network_truth(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        window = src.split("def _bg_probe_health", 1)[1].split("\ndef _bg_probe_update", 1)[0]
        self.assertIn("def _legacy_network_reachable(h):", window)
        self.assertIn("socket.create_connection((h.ip, 22)", window)
        self.assertIn('["ping", "-c", "1", "-W", "1", h.ip]', window)
        self.assertIn("if htype in LEGACY_HTYPES and state == STATE_UNREACHABLE and _legacy_network_reachable(h):", window)
        self.assertIn("state = STATE_DEGRADED", window)
        self.assertIn("legacy device reachable; metrics probe failed", window)

    def test_ui_toasts_are_logged_to_server(self):
        src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        serve_src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("function _uiLog", src)
        self.assertIn("fetch('/api/ui/event'", src)
        self.assertIn("_uiLog('toast'", src)
        self.assertIn('"/api/ui/event": "_serve_ui_event"', serve_src)
        self.assertIn("logger.info(\n            \"ui_event\"", serve_src)
        self.assertIn("ui_level=level", serve_src)
        self.assertNotIn("\n            level=level,", serve_src)

    def test_core_system_cards_open_infra_detail_without_cache_lookup(self):
        src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        self.assertIn('data-action="openInfraDevice"', src)
        self.assertIn("data-infra-type", src)
        self.assertIn("openCard('infra',{label:da.dataset.label,infraType:da.dataset.infraType,ip:da.dataset.ip})", src)
        self.assertIn("if(!ph&&config.ip)ph={label:label,type:infraType,ip:config.ip", src)

    def test_infra_quick_reconciles_reachability_with_fleet_overview(self):
        src = (REPO_ROOT / "freq" / "api" / "fleet.py").read_text()
        window = src.split("def handle_infra_quick", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('fleet_overview = _bg_cache.get("fleet_overview")', window)
        self.assertIn("physical_reachability", window)
        self.assertIn('item["reachable"] = True', window)
        self.assertIn('item["network_reachable"] = True', window)
        self.assertIn('item["reachability_source"] = "fleet_overview"', window)
        self.assertIn("auth_failed=bool(item.get(\"auth_failed\"))", window)
        self.assertIn("infra_quick_reachability_reconciled", window)

    def test_truenas_quick_card_uses_api_key_truth(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        web_src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        helper_src = (REPO_ROOT / "freq" / "core" / "truenas_api.py").read_text()
        self.assertIn("from freq.core import truenas_api", src)
        self.assertIn('truenas_api.request(api_settings, "pools"', src)
        self.assertIn('d["probe_method"] = "truenas_api_key"', src)
        self.assertIn("TrueNAS API key missing", helper_src)
        self.assertIn("pool_metrics", helper_src)
        self.assertIn("_m('REACHABLE','NETWORK','var(--green)')", web_src)
        self.assertIn("METRICS UNAVAILABLE", web_src)
        self.assertIn("dev.type==='truenas'?'API':'SSH'", web_src)

    def test_truenas_settings_can_read_api_key_file(self):
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

    def test_infra_overview_does_not_probe_physical_devices_as_linux(self):
        src = (REPO_ROOT / "freq" / "api" / "fleet.py").read_text()
        self.assertIn('physical_types = {"truenas", "switch", "idrac"}', src)
        self.assertIn("shell_hosts = [h for h in cfg.hosts if h.htype not in physical_types]", src)
        self.assertIn("quick_by_label", src)
        self.assertIn("quick_by_ip", src)
        self.assertIn('"hostname": h.label', src)
        self.assertIn('"status": status', src)

    def test_core_physical_hosts_cannot_hide_as_unmanaged(self):
        doctor_src = (REPO_ROOT / "freq" / "core" / "doctor.py").read_text()
        init_src = (REPO_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        hosts_src = (REPO_ROOT / "freq" / "modules" / "hosts.py").read_text()
        self.assertIn("core physical host(s) marked unmanaged", doctor_src)
        self.assertIn('getattr(dev, "device_type", "") == "truenas"', doctor_src)
        self.assertIn("is core physical infrastructure", init_src)
        self.assertIn("leaving managed so doctor/verify must fail", init_src)
        self.assertIn('"managed": dev.scope != "lab" and dev.device_type != "truenas"', hosts_src)
        self.assertIn('managed=d.get("managed", True)', hosts_src)

    def test_truenas_action_endpoint_is_action_aware_and_truthful(self):
        src = (REPO_ROOT / "freq" / "api" / "store.py").read_text()
        helper_src = (REPO_ROOT / "freq" / "core" / "truenas_api.py").read_text()
        self.assertIn("read_actions = {", src)
        self.assertIn('"pools": "zpool list -v"', src)
        self.assertIn("truenas_api.settings(cfg, target)", src)
        self.assertIn("truenas_api.request(api_settings, action)", src)
        self.assertIn("truenas_api_key", helper_src + src)
        self.assertIn("ssh_auth_failed_ping", src)
        self.assertIn('"ssh_available": False', src)
        self.assertIn('failure_log_level="warn"', src)
        self.assertIn("use_sudo=True", src)

    def test_doctor_checks_truenas_api_key_path(self):
        src = (REPO_ROOT / "freq" / "core" / "doctor.py").read_text()
        helper_src = (REPO_ROOT / "freq" / "core" / "truenas_api.py").read_text()
        self.assertIn("def _check_truenas_api_credentials", src)
        self.assertIn("_check_truenas_api_credentials", src)
        self.assertIn("TrueNAS API key missing", src)
        self.assertIn("truenas_api.settings(cfg, dev)", src)
        self.assertIn('vault_get(cfg, secret_ns, "api_key")', helper_src)

    def test_init_device_credentials_can_carry_truenas_api_key(self):
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

    def test_init_persists_truenas_api_key_to_runtime_vault(self):
        src = (REPO_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("def _seed_truenas_api_key_from_device_creds", src)
        self.assertIn('vault_set(cfg, namespace, "api_key", api_key)', src)
        self.assertIn("_seed_truenas_api_key_from_device_creds(cfg, device_creds)", src)


if __name__ == "__main__":
    unittest.main()
