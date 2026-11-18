"""Dashboard terminal browser contract.

The terminal API correctly rejects GET for mutating session operations.
The browser client must therefore call those endpoints with POST too;
otherwise the first operator click fails even though backend enforcement
tests pass.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).parent.parent


def _endpoint_snippet(source: str, endpoint: str) -> str:
    index = source.find(endpoint)
    assert index != -1, f"{endpoint} is missing from app.js"
    return source[index:index + 800]


def test_terminal_dashboard_mutations_use_post():
    source = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()

    for endpoint in (
        "/api/terminal/open",
        "/api/terminal/resize",
        "/api/terminal/close",
    ):
        snippet = _endpoint_snippet(source, endpoint)
        assert "method:'POST'" in snippet or 'method:"POST"' in snippet


def test_infra_terminal_buttons_use_host_mode_not_vmid_resolution():
    source = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()

    assert "openTerminal(\\'host\\'" in source
    assert "through VMID resolution" in source
    assert "type='+type+'&target='" in source
    assert "var termType=(type==='pfsense'||type==='truenas'||type==='idrac'||type==='switch'||type==='host')?'host':type;" in source
    assert "openTerminal(\\'vm\\',\\''+_esc(termIp)" not in source


def test_terminal_api_supports_direct_host_targets_and_device_credentials():
    source = (REPO_ROOT / "freq" / "api" / "terminal.py").read_text()

    assert "host: SSH directly to a host/device IP" in source
    assert 'term_type = params.get("type", ["vm"])[0]  # vm, host, ct, node' in source
    assert "def _terminal_ssh_auth" in source
    assert 'if htype in ("pfsense", "idrac", "switch", "truenas")' in source
    assert "resolve_staged_device_ssh_auth(cfg, htype)" in source
    assert "from freq.core.ssh import _build_ssh_cmd" in source
    assert "cmd = shlex.join(" in source
    assert "password_file=password_file" in source
    assert "sudo_password_file=sudo_password_file" in source
    assert "extra_opts=[\"-tt\"]" in source
    assert "local_user=local_user" in source
    assert 'if term_type == "vm" and target.isdigit()' in source
    assert "def _terminal_preflight" in source


def test_host_tool_restart_service_is_real_button_not_cli_hint():
    source = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()

    assert "if(a==='hdRestart'){hdRestart(da);return;}" in source
    assert "function hdRestart(btn)" in source
    assert "Use CLI: freq fleet exec" not in source
    assert "sudo systemctl restart '+svc" in source
    assert "API.EXEC+'?target='+encodeURIComponent(_cardState.host)" in source
    assert "method:'POST'" in source.split("function hdRestart", 1)[1].split("function hdRunCmd", 1)[0]
    assert "Invalid service name" in source


def test_vm_add_disk_ui_uses_backend_storage_default_not_hardcoded_local_lvm():
    source = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()

    assert "VM_WIZARD_DEFAULTS:'/api/vm/wizard-defaults'" in source
    add_disk_panel = source.split("} else if(tab==='vmadddisk')", 1)[1].split("} else if(tab==='vmtag')", 1)[0]
    assert "auto from PVE storage config" in add_disk_panel
    assert 'value="local-lvm"' not in add_disk_panel
    add_disk_fn = source.split("function vmtAddDisk()", 1)[1].split("function vmtTag()", 1)[0]
    assert "||'local-lvm'" not in add_disk_fn
    assert "API.VM_WIZARD_DEFAULTS" in add_disk_panel


def test_vm_card_host_tools_prefer_resolved_guest_ip():
    source = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
    render_vm = source.split("function renderVmCard", 1)[1].split("/* Snapshot info section */", 1)[0]

    assert "_cardState.host=(subtitleIp&&subtitleIp!=='?')?subtitleIp:label;" in render_vm
    assert 'data-action="hdExec"' in source or "hdExec(this)" in source
    assert 'data-action="hdLogs"' in source or "hdLogs(this)" in source
    assert 'data-action="hdDiagnose"' in source or "hdDiagnose(this)" in source
    assert 'data-action="hdRestart"' in source or "hdRestart(this)" in source


def test_host_diagnostic_route_accepts_direct_guest_ip():
    from ast import Attribute, Call, FunctionDef, Import, ImportFrom, Name, parse, walk

    from freq.modules import serve
    from freq.services import host_diagnostic

    def attribute_path(node):
        if isinstance(node, Name):
            return node.id
        if isinstance(node, Attribute):
            parent = attribute_path(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return ""

    serve_tree = parse((REPO_ROOT / "freq/modules/serve.py").read_text())
    service_tree = parse((REPO_ROOT / "freq/services/host_diagnostic.py").read_text())
    service_imports = set()
    for node in walk(service_tree):
        if isinstance(node, Import):
            service_imports.update(alias.name for alias in node.names)
        elif isinstance(node, ImportFrom) and node.module:
            service_imports.add(node.module)
    assert service_imports == {"re", "freq.core", "freq.core.ssh", "freq.core.types"}
    assert "run_host_diagnostic" in {
        node.name for node in walk(service_tree) if isinstance(node, FunctionDef)
    }
    diagnostic_handler = next(
        node
        for node in walk(serve_tree)
        if isinstance(node, FunctionDef) and node.name == "_serve_host_diagnostic"
    )
    assert len(diagnostic_handler.body) == 7
    handler_calls = {
        attribute_path(node.func)
        for node in walk(diagnostic_handler)
        if isinstance(node, Call)
    }
    assert "_host_diagnostic.run_host_diagnostic" in handler_calls
    assert "ssh_single" not in handler_calls
    assert "resolve.by_target" not in handler_calls

    diagnostic_command = (
        'echo "=== SYSTEM ===" && hostname -f && cat /etc/os-release 2>/dev/null | grep PRETTY && uname -r '
        '&& echo "=== RESOURCES ===" && nproc && free -h | head -2 && df -h / && cat /proc/loadavg '
        '&& echo "=== NETWORK ===" && ip -4 addr show | grep inet | grep -v 127 && ip route show default '
        '&& echo "=== DOCKER ===" && docker ps --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "not installed" '
        '&& echo "=== SECURITY ===" && systemctl --failed --no-legend 2>/dev/null | head -5 || echo "ok" '
        '&& echo "=== LISTENING ===" && ss -tlnp 2>/dev/null | grep LISTEN | head -10'
    )
    known = SimpleNamespace(ip="10.0.0.10", label="known", htype="linux", vmid=0)
    known_vm = SimpleNamespace(ip="10.0.0.20", label="known-vm", htype="docker", vmid=217)
    cfg = SimpleNamespace(hosts=[known, known_vm], ssh_key_path="/keys/fleet")

    with (
        patch.object(serve, "load_config", return_value=cfg) as load_config,
        patch.object(serve, "_parse_query") as parse_query,
        patch.object(host_diagnostic.resolve, "by_target") as by_target,
        patch.object(host_diagnostic, "ssh_single") as ssh_run,
        patch("freq.api.terminal._find_live_vm_node_ip") as find_live_vm,
        patch("freq.api.terminal._guest_agent_network_json") as guest_network,
        patch("freq.api.terminal._extract_guest_ipv4") as extract_ipv4,
        patch.object(serve.logger, "warn") as warn,
    ):
        handler = SimpleNamespace(_json_response=Mock())
        parse_query.return_value = {"target": [""]}
        serve.FreqHandler._serve_host_diagnostic(handler)
        handler._json_response.assert_called_once_with({"error": "target required"}, 400)
        load_config.assert_called_once_with()
        parse_query.assert_called_once_with(handler)
        by_target.assert_not_called()
        ssh_run.assert_not_called()
        find_live_vm.assert_not_called()

        for mocked in (
            load_config,
            parse_query,
            by_target,
            ssh_run,
            find_live_vm,
            guest_network,
            extract_ipv4,
            warn,
        ):
            mocked.reset_mock()
        handler._json_response.reset_mock()
        parse_query.return_value = {"target": ["known"]}
        by_target.return_value = known
        ssh_run.return_value = SimpleNamespace(returncode=0, stdout="diagnostic output\n")
        serve.FreqHandler._serve_host_diagnostic(handler)
        by_target.assert_called_once_with(cfg.hosts, "known")
        find_live_vm.assert_not_called()
        ssh_run.assert_called_once_with(
            host="10.0.0.10",
            command=diagnostic_command,
            key_path="/keys/fleet",
            connect_timeout=5,
            command_timeout=15,
            htype="linux",
            use_sudo=True,
            cfg=cfg,
        )
        assert ssh_run.call_args.kwargs["cfg"] is cfg
        handler._json_response.assert_called_once_with(
            {"host": "known", "output": "diagnostic output\n", "ok": True}
        )

        ssh_run.reset_mock()
        handler._json_response.reset_mock()
        ssh_run.return_value = SimpleNamespace(returncode=7, stdout="partial output\n")
        serve.FreqHandler._serve_host_diagnostic(handler)
        handler._json_response.assert_called_once_with(
            {"host": "known", "output": "partial output\n", "ok": False}
        )

        ssh_run.reset_mock()
        handler._json_response.reset_mock()
        ssh_run.return_value = None
        serve.FreqHandler._serve_host_diagnostic(handler)
        handler._json_response.assert_called_once_with(
            {"host": "known", "output": "", "ok": False}
        )

        for mocked in (by_target, ssh_run, find_live_vm, guest_network, extract_ipv4, warn):
            mocked.reset_mock()
        handler._json_response.reset_mock()
        parse_query.return_value = {"target": ["vm:217"]}
        by_target.return_value = None
        ssh_run.return_value = SimpleNamespace(returncode=0, stdout="registry vm\n")
        serve.FreqHandler._serve_host_diagnostic(handler)
        find_live_vm.assert_not_called()
        ssh_run.assert_called_once()
        assert ssh_run.call_args.kwargs["host"] == "10.0.0.20"
        assert ssh_run.call_args.kwargs["htype"] == "docker"
        assert ssh_run.call_args.kwargs["cfg"] is cfg
        handler._json_response.assert_called_once_with(
            {"host": "vm:217", "output": "registry vm\n", "ok": True}
        )

        for mocked in (by_target, ssh_run, find_live_vm, guest_network, extract_ipv4, warn):
            mocked.reset_mock()
        handler._json_response.reset_mock()
        empty_cfg = SimpleNamespace(hosts=[], ssh_key_path="/keys/empty")
        load_config.return_value = empty_cfg
        parse_query.return_value = {"target": ["vm:318"]}
        by_target.return_value = None
        find_live_vm.return_value = ("10.0.0.31", "pve-3")
        guest_network.return_value = ("guest-agent-json", True, "pve_api")
        extract_ipv4.return_value = "10.0.0.38"
        ssh_run.return_value = SimpleNamespace(returncode=0, stdout="guest vm\n")
        serve.FreqHandler._serve_host_diagnostic(handler)
        by_target.assert_called_once_with(empty_cfg.hosts, "vm:318")
        find_live_vm.assert_called_once_with(empty_cfg, 318, "")
        guest_network.assert_called_once_with(empty_cfg, 318, "10.0.0.31", "pve-3")
        extract_ipv4.assert_called_once_with("guest-agent-json")
        assert ssh_run.call_args.kwargs == {
            "host": "10.0.0.38",
            "command": diagnostic_command,
            "key_path": "/keys/empty",
            "connect_timeout": 5,
            "command_timeout": 15,
            "htype": "linux",
            "use_sudo": True,
            "cfg": empty_cfg,
        }
        handler._json_response.assert_called_once_with(
            {"host": "vm:318", "output": "guest vm\n", "ok": True}
        )

        for mocked in (by_target, ssh_run, find_live_vm, guest_network, extract_ipv4, warn):
            mocked.reset_mock()
        handler._json_response.reset_mock()
        parse_query.return_value = {"target": ["10.25.255.55"]}
        ssh_run.return_value = None
        serve.FreqHandler._serve_host_diagnostic(handler)
        find_live_vm.assert_not_called()
        assert ssh_run.call_args.kwargs == {
            "host": "10.25.255.55",
            "command": diagnostic_command,
            "key_path": "/keys/empty",
            "connect_timeout": 5,
            "command_timeout": 15,
            "htype": "linux",
            "use_sudo": True,
            "cfg": empty_cfg,
        }
        handler._json_response.assert_called_once_with(
            {"host": "10.25.255.55", "output": "", "ok": False}
        )

        for mocked in (by_target, ssh_run, find_live_vm, guest_network, extract_ipv4, warn):
            mocked.reset_mock()
        handler._json_response.reset_mock()
        parse_query.return_value = {"target": ["missing"]}
        serve.FreqHandler._serve_host_diagnostic(handler)
        handler._json_response.assert_called_once_with(
            {"error": "Host not found: missing"}, 404
        )
        ssh_run.assert_not_called()

        for mocked in (by_target, ssh_run, find_live_vm, guest_network, extract_ipv4, warn):
            mocked.reset_mock()
        handler._json_response.reset_mock()
        parse_query.return_value = {"target": ["vm:999"]}
        find_live_vm.side_effect = RuntimeError("inventory unavailable")
        serve.FreqHandler._serve_host_diagnostic(handler)
        warn.assert_called_once_with(
            "host diagnostic VM target resolve failed for VMID 999: inventory unavailable"
        )
        handler._json_response.assert_called_once_with(
            {"error": "Host not found: vm:999"}, 404
        )
        ssh_run.assert_not_called()


def test_infra_detail_cards_have_single_output_target():
    source = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()

    assert "function _infraOutputHtml" in source
    panel = source.split("function _infraPanelHtml", 1)[1].split("function _infraOutputHtml", 1)[0]
    assert "id=\"hd-infra-out\"" not in panel
    assert source.count("_infraOutputHtml()") >= 2
    assert "_infraOutputTarget='hd-infra-out'" in source


def test_known_dashboard_write_actions_use_post():
    source = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()

    for endpoint in (
        "/api/rules/create",
        "/api/rules/update",
        "/api/rules/delete",
        "/api/playbooks/step",
        "API.PLAYBOOKS_CREATE",
        "API.BACKUP_CREATE",
        "API.TREND_SNAPSHOT",
        "/api/vm/resize?vmid=",
        "/api/containers/action?host=docker-dev",
        "/api/containers/action?host='+encodeURIComponent(host)",
    ):
        snippet = _endpoint_snippet(source, endpoint)
        assert "method:'POST'" in snippet or 'method:\"POST\"' in snippet


def test_known_dashboard_read_views_do_not_use_post():
    source = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()

    for endpoint in (
        "var urls={show:API.SWITCH_SHOW",
        "var url=type==='health'?API.STACK_HEALTH:API.STACK_STATUS",
    ):
        snippet = _endpoint_snippet(source, endpoint)
        assert "method:'POST'" not in snippet and 'method:"POST"' not in snippet


def test_terminal_vm_resolution_uses_live_pve_inventory_not_host_discover():
    source = (REPO_ROOT / "freq" / "api" / "terminal.py").read_text()
    assert "def _find_live_vm_node_ip" in source
    assert "from freq.services.pve_inventory import _get_fleet_vms" in source
    assert "def _guest_agent_network_json" in source
    assert "/agent/network-get-interfaces" in source
    assert "pve_api" in source
    assert "The VM is visible in PVE" in source
    assert "Run 'freq host discover' to populate hosts.toml with VMIDs" not in source


def test_terminal_truenas_ssh_auth_failure_is_explicit_not_blank_session():
    source = (REPO_ROOT / "freq" / "api" / "terminal.py").read_text()

    assert "TrueNAS SSH credentials were rejected" in source
    assert "stage working SSH credentials to open an interactive shell" in source
    assert "json_response(handler, {\"error\": preflight_error}, 400)" in source


def test_terminal_guest_agent_ipv4_parser_accepts_raw_and_wrapped_json():
    from freq.api.terminal import _extract_guest_ipv4

    raw = '[{"name":"lo","ip-addresses":[{"ip-address-type":"ipv4","ip-address":"127.0.0.1"}]},{"name":"ens18","ip-addresses":[{"ip-address-type":"ipv4","ip-address":"10.25.255.201"}]}]'
    wrapped = '{"result":' + raw + "}"
    api_wrapped = '{"result":[{"name":"lo","ip-addresses":[{"ip-address-type":"ipv4","ip-address":"127.0.0.1"}]},{"name":"eth0","ip-addresses":[{"prefix":24,"ip-address-type":"ipv4","ip-address":"10.25.255.30"}]}]}'
    assert _extract_guest_ipv4(raw) == "10.25.255.201"
    assert _extract_guest_ipv4(wrapped) == "10.25.255.201"
    assert _extract_guest_ipv4(api_wrapped) == "10.25.255.30"
    assert _extract_guest_ipv4("{}") == ""


def test_terminal_live_node_ref_resolves_from_discovered_nodes(monkeypatch):
    from freq.api import terminal

    monkeypatch.setattr(
        terminal,
        "_get_fleet_vms",
        lambda cfg: [{"vmid": 201, "node": "pve02", "name": "plex"}],
    )
    monkeypatch.setattr(terminal, "_get_discovered_nodes", lambda: [
        {"name": "pve01", "ip": "10.25.255.26"},
        {"name": "pve02", "ip": "10.25.255.27"},
    ])
    cfg = Mock()
    cfg.pve_node_names = []
    cfg.pve_nodes = []
    cfg.fleet_boundaries = None
    assert terminal._find_live_vm_node_ip(cfg, 201) == ("10.25.255.27", "pve02")
