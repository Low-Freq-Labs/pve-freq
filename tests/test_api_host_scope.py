import json
from types import SimpleNamespace
from unittest.mock import patch

from freq.core.types import CmdResult, Host


def test_keys_probes_only_managed_hosts_but_reports_inventory_rows():
    from freq.api import host as host_api

    pve = Host(ip="10.0.0.1", label="pve01", htype="pve")
    excluded = Host(ip="10.0.0.2", label="operator-box", htype="linux", managed=False)
    cfg = SimpleNamespace(hosts=[pve, excluded], ssh_key_path="/tmp/key", pve_nodes=[])
    response = {}

    def capture(_handler, data, status=200):
        response.update(data)
        response["status"] = status

    def fake_run_many(**kwargs):
        response["probed_hosts"] = list(kwargs["hosts"])
        return {pve.ip: CmdResult(stdout="4\n", stderr="", returncode=0)}

    with patch.object(host_api, "load_config", return_value=cfg), patch.object(
        host_api, "ssh_run_many", side_effect=fake_run_many
    ), patch.object(host_api, "json_response", side_effect=capture):
        host_api.handle_keys(object())

    assert [item.label for item in response["probed_hosts"]] == ["pve01"]
    assert json.loads(json.dumps(response["hosts"])) == [
        {"host": "pve01", "ip": "10.0.0.1", "reachable": True, "probe_status": "probed", "key_count": 4},
        {"host": "operator-box", "ip": "10.0.0.2", "reachable": False, "probe_status": "unprobed", "key_count": 0},
    ]


def test_log_query_probes_only_managed_hosts():
    from freq.api import logs as logs_api

    managed = Host(ip="10.0.0.1", label="managed", htype="linux")
    excluded = Host(ip="10.0.0.2", label="excluded", htype="linux", managed=False)
    cfg = SimpleNamespace(hosts=[managed, excluded], ssh_key_path="/tmp/key",
                          ssh_connect_timeout=3, ssh_max_parallel=2)
    seen = {}

    def fake_run_many(**kwargs):
        seen["hosts"] = kwargs["hosts"]
        return {managed.ip: CmdResult(stdout="error line\n", stderr="", returncode=0)}

    with patch.object(logs_api, "ssh_run_many", side_effect=fake_run_many):
        result = logs_api._log_query(cfg, "journalctl --priority err")

    assert [host.label for host in seen["hosts"]] == ["managed"]
    assert result == [{"host": "managed", "ip": "10.0.0.1", "output": "error line", "lines": 1}]
