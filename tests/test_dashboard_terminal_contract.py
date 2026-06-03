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
    assert "The VM is visible in PVE" in source
    assert "Run 'freq host discover' to populate hosts.toml with VMIDs" not in source


def test_terminal_guest_agent_ipv4_parser_accepts_raw_and_wrapped_json():
    from freq.api.terminal import _extract_guest_ipv4

    raw = '[{"name":"lo","ip-addresses":[{"ip-address-type":"ipv4","ip-address":"127.0.0.1"}]},{"name":"ens18","ip-addresses":[{"ip-address-type":"ipv4","ip-address":"10.25.255.201"}]}]'
    wrapped = '{"result":' + raw + "}"
    assert _extract_guest_ipv4(raw) == "10.25.255.201"
    assert _extract_guest_ipv4(wrapped) == "10.25.255.201"
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
