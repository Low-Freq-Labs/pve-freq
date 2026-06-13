"""Dashboard terminal browser contract.

The terminal API correctly rejects GET for mutating session operations.
The browser client must therefore call those endpoints with POST too;
otherwise the first operator click fails even though backend enforcement
tests pass.
"""

from pathlib import Path
from unittest.mock import Mock


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
    source = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
    window = source.split("def _serve_host_diagnostic", 1)[1].split("def _request_body", 1)[0]

    assert "from freq.core.types import Host" in window
    assert "Host(ip=target, label=target, htype=\"linux\", groups=\"ad-hoc-vm\")" in window
    assert "Host not found" in window


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
    assert "from freq.modules.serve import _get_fleet_vms" in source
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
    import sys
    import types

    from freq.api.terminal import _find_live_vm_node_ip

    fake_serve = types.ModuleType("freq.modules.serve")
    fake_serve._get_fleet_vms = lambda cfg: [{"vmid": 201, "node": "pve02", "name": "plex"}]
    fake_serve._get_discovered_nodes = lambda: [
        {"name": "pve01", "ip": "10.25.255.26"},
        {"name": "pve02", "ip": "10.25.255.27"},
    ]
    monkeypatch.setitem(sys.modules, "freq.modules.serve", fake_serve)

    cfg = Mock()
    cfg.pve_node_names = []
    cfg.pve_nodes = []
    cfg.fleet_boundaries = None
    assert _find_live_vm_node_ip(cfg, 201) == ("10.25.255.27", "pve02")
