"""Behavior owners for topology-aware multi-control-plane host sync."""

import json

from freq.core.config import load_hosts_toml
from freq.modules.hosts import _hosts_sync
from tests.test_hosts_sync import _fake_ssh_result, _make_cfg, _qm_agent_json


def _status(cluster: str | None, members: list[tuple[str, str]]) -> str:
    rows = []
    if cluster:
        rows.append({"type": "cluster", "name": cluster})
    rows.extend(
        {"type": "node", "name": name, "ip": ip} for name, ip in members
    )
    return json.dumps(rows)


def test_two_standalone_endpoints_with_reused_vmid_and_name_both_survive(
    tmp_path, monkeypatch
) -> None:
    endpoints = ["192.168.255.26", "172.20.0.26"]
    cfg = _make_cfg(
        str(tmp_path),
        pve_nodes=endpoints,
        pve_node_names=["pve", "pve"],
    )
    calls = []

    def fake_run(host, command, **kwargs):
        calls.append((host, command))
        if "/cluster/status" in command:
            return _fake_ssh_result(stdout=_status(None, [("pve", host)]))
        if "/cluster/resources" in command:
            return _fake_ssh_result(
                stdout=json.dumps(
                    [
                        {
                            "vmid": 101,
                            "name": "shared-name",
                            "node": "pve",
                            "status": "running",
                            "type": "qemu",
                        }
                    ]
                )
            )
        if "qm agent 101" in command:
            address = "192.168.255.41" if host == endpoints[0] else "172.20.0.41"
            return _fake_ssh_result(stdout=_qm_agent_json([address]))
        return _fake_ssh_result(returncode=1)

    monkeypatch.setattr("freq.core.ssh.run", fake_run)

    rc = _hosts_sync(cfg)

    assert rc == 0
    rows = load_hosts_toml(cfg.hosts_file)
    guest_ips = {row.ip for row in rows if row.vmid == 101}
    assert guest_ips == {"192.168.255.41", "172.20.0.41"}
    resource_hosts = [host for host, command in calls if "/cluster/resources" in command]
    agent_hosts = [host for host, command in calls if "qm agent 101" in command]
    assert resource_hosts == endpoints
    assert agent_hosts == endpoints


def test_positive_shared_cluster_identity_queries_resources_once_and_routes_by_node(
    tmp_path, monkeypatch
) -> None:
    endpoints = ["192.168.255.26", "192.168.255.27"]
    names = ["pve01", "pve02"]
    cfg = _make_cfg(
        str(tmp_path),
        pve_nodes=endpoints,
        pve_node_names=names,
    )
    calls = []

    def fake_run(host, command, **kwargs):
        calls.append((host, command))
        if "/cluster/status" in command:
            return _fake_ssh_result(
                stdout=_status("lab-cluster", list(zip(names, endpoints)))
            )
        if "/cluster/resources" in command:
            return _fake_ssh_result(
                stdout=json.dumps(
                    [
                        {
                            "vmid": 101,
                            "name": "one",
                            "node": "pve01",
                            "status": "running",
                            "type": "qemu",
                        },
                        {
                            "vmid": 202,
                            "name": "two",
                            "node": "pve02",
                            "status": "running",
                            "type": "qemu",
                        },
                    ]
                )
            )
        if "qm agent 101" in command:
            return _fake_ssh_result(stdout=_qm_agent_json(["192.168.255.41"]))
        if "qm agent 202" in command:
            return _fake_ssh_result(stdout=_qm_agent_json(["192.168.255.42"]))
        return _fake_ssh_result(returncode=1)

    monkeypatch.setattr("freq.core.ssh.run", fake_run)

    rc = _hosts_sync(cfg)

    assert rc == 0
    status_hosts = [host for host, command in calls if "/cluster/status" in command]
    resource_hosts = [host for host, command in calls if "/cluster/resources" in command]
    assert status_hosts == endpoints
    assert resource_hosts == [endpoints[0]]
    assert (endpoints[0], "qm agent 101 network-get-interfaces 2>/dev/null") in calls
    assert (endpoints[1], "qm agent 202 network-get-interfaces 2>/dev/null") in calls


def test_partial_control_plane_failure_keeps_successes_but_returns_nonzero(
    tmp_path, monkeypatch, capsys
) -> None:
    endpoints = ["192.168.255.26", "172.20.0.26"]
    cfg = _make_cfg(
        str(tmp_path),
        pve_nodes=endpoints,
        pve_node_names=["pve-a", "pve-b"],
    )

    def fake_run(host, command, **kwargs):
        if "/cluster/status" in command:
            return _fake_ssh_result(stdout=_status(None, [("pve", host)]))
        if "/cluster/resources" in command and host == endpoints[1]:
            return _fake_ssh_result(stderr="unreachable", returncode=255)
        if "/cluster/resources" in command:
            return _fake_ssh_result(
                stdout=json.dumps(
                    [
                        {
                            "vmid": 101,
                            "name": "reachable",
                            "node": "pve-a",
                            "status": "running",
                            "type": "qemu",
                        }
                    ]
                )
            )
        if "qm agent 101" in command:
            return _fake_ssh_result(stdout=_qm_agent_json(["192.168.255.41"]))
        return _fake_ssh_result(returncode=1)

    monkeypatch.setattr("freq.core.ssh.run", fake_run)

    rc = _hosts_sync(cfg)

    assert rc == 1
    assert any(row.ip == "192.168.255.41" for row in load_hosts_toml(cfg.hosts_file))
    output = capsys.readouterr().out
    assert "incomplete" in output.lower()
    assert endpoints[1] in output
