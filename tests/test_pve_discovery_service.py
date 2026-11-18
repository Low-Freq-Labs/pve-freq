"""Characterization for the Phase-3 PVE node-discovery service seam."""

from types import SimpleNamespace

import pytest

from freq.services import pve_discovery


@pytest.fixture(autouse=True)
def _restore_pve_discovery_cache():
    missing = object()
    with pve_discovery._bg_lock:
        old_cache = pve_discovery._bg_cache.get("pve_nodes", missing)
        old_ts = pve_discovery._bg_cache_ts.get("pve_nodes", missing)
    try:
        yield
    finally:
        with pve_discovery._bg_lock:
            if old_cache is missing:
                pve_discovery._bg_cache.pop("pve_nodes", None)
            else:
                pve_discovery._bg_cache["pve_nodes"] = old_cache
            if old_ts is missing:
                pve_discovery._bg_cache_ts.pop("pve_nodes", None)
            else:
                pve_discovery._bg_cache_ts["pve_nodes"] = old_ts


def _result(returncode=0, stdout=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout)


def _assert_backup_schedule_transport(monkeypatch, serve, cfg):
    handler = serve.FreqHandler.__new__(serve.FreqHandler)
    responses = []
    handler._json_response = lambda payload, status=200: responses.append((payload, status))

    loaded = []
    resolved = []
    ssh_calls = []

    monkeypatch.setattr(
        serve,
        "load_config",
        lambda: loaded.append(cfg) or cfg,
    )
    monkeypatch.setattr(
        pve_discovery,
        "find_reachable_pve_node",
        lambda actual_cfg: resolved.append(actual_cfg) or None,
    )
    monkeypatch.setattr(
        pve_discovery,
        "ssh_single",
        lambda **kwargs: pytest.fail(f"unreachable schedule must not SSH: {kwargs}"),
    )

    handler._serve_backup_schedules()

    assert responses.pop() == (
        {"schedules": [], "error": "No PVE node reachable"},
        200,
    )
    assert loaded == [cfg]
    assert resolved == [cfg]
    assert resolved[0] is cfg

    raw = "backup: vzdump\n\tschedule daily\n"
    result = _result(0, raw)
    expected_ssh = {
        "host": "192.0.2.26",
        "command": "cat /etc/pve/jobs.cfg 2>/dev/null || echo ''",
        "key_path": "/credentials/freq-admin",
        "connect_timeout": 3,
        "command_timeout": 10,
        "htype": "pve",
        "use_sudo": True,
        "cfg": cfg,
    }

    monkeypatch.setattr(
        pve_discovery,
        "find_reachable_pve_node",
        lambda actual_cfg: resolved.append(actual_cfg) or "192.0.2.26",
    )
    monkeypatch.setattr(
        pve_discovery,
        "ssh_single",
        lambda **kwargs: ssh_calls.append(kwargs) or result,
    )

    handler._serve_backup_schedules()

    payload, status = responses.pop()
    assert payload == {"raw": raw, "ok": True}
    assert payload["raw"] is raw
    assert payload["ok"] is True
    assert status == 200
    assert ssh_calls == [expected_ssh]
    assert ssh_calls[0]["cfg"] is cfg

    ssh_calls.clear()
    failed = _result(23, "stale output")
    monkeypatch.setattr(
        pve_discovery,
        "ssh_single",
        lambda **kwargs: ssh_calls.append(kwargs) or failed,
    )
    handler._serve_backup_schedules()
    payload, status = responses.pop()
    assert payload == {"raw": "", "ok": False}
    assert payload["ok"] is False
    assert status == 200
    assert ssh_calls == [expected_ssh]
    assert ssh_calls[0]["cfg"] is cfg

    ssh_calls.clear()
    monkeypatch.setattr(
        pve_discovery,
        "ssh_single",
        lambda **kwargs: ssh_calls.append(kwargs) or None,
    )
    handler._serve_backup_schedules()
    payload, status = responses.pop()
    assert payload == {"raw": "", "ok": False}
    assert payload["ok"] is False
    assert status == 200
    assert ssh_calls == [expected_ssh]
    assert ssh_calls[0]["cfg"] is cfg

    assert loaded == [cfg, cfg, cfg, cfg]
    assert resolved == [cfg, cfg, cfg, cfg]
    assert all(actual_cfg is cfg for actual_cfg in resolved)


def test_fresh_discovery_cache_short_circuits_without_config_or_ssh(monkeypatch):
    with pve_discovery._bg_lock:
        pve_discovery._bg_cache_ts["pve_nodes"] = 900.0

    monkeypatch.setattr(pve_discovery.time, "time", lambda: 1000.0)
    monkeypatch.setattr(
        pve_discovery,
        "load_config",
        lambda: pytest.fail("fresh cache must not load config"),
    )
    monkeypatch.setattr(
        pve_discovery,
        "ssh_single",
        lambda **kwargs: pytest.fail(f"fresh cache must not SSH: {kwargs}"),
    )

    assert pve_discovery._bg_discover_pve_nodes() is None


def test_discovery_preserves_seed_order_commands_and_parsed_cache(monkeypatch):
    cfg = SimpleNamespace(
        pve_nodes=["192.0.2.10", "192.0.2.11", "192.0.2.12"],
        ssh_key_path="/credentials/freq-admin",
    )
    calls = []
    node_json = (
        '[{"node":"pve02","status":"online","maxcpu":16,"maxmem":34359738368},'
        '{"node":"pve01","status":"offline","maxcpu":8,"maxmem":17179869184}]'
    )
    corosync = """
node {
    name: pve01
    ring0_addr: 192.0.2.26
}
node {
    name: pve02
    ring0_addr: 192.0.2.27
}
"""

    def fake_ssh(**kwargs):
        calls.append(kwargs)
        if kwargs["command"] == "echo ok":
            return _result(0 if kwargs["host"] == "192.0.2.11" else 1)
        if kwargs["command"].startswith("pvesh get"):
            return _result(stdout=node_json)
        return _result(stdout=corosync)

    with pve_discovery._bg_lock:
        pve_discovery._bg_cache.pop("pve_nodes", None)
        pve_discovery._bg_cache_ts["pve_nodes"] = 0.0
    monkeypatch.setattr(pve_discovery, "load_config", lambda: cfg)
    monkeypatch.setattr(pve_discovery, "ssh_single", fake_ssh)
    monkeypatch.setattr(pve_discovery.time, "time", lambda: 1000.0)

    pve_discovery._bg_discover_pve_nodes()

    assert [call["host"] for call in calls[:2]] == ["192.0.2.10", "192.0.2.11"]
    assert calls[0] == {
        "host": "192.0.2.10",
        "command": "echo ok",
        "key_path": "/credentials/freq-admin",
        "connect_timeout": 3,
        "command_timeout": 5,
        "htype": "pve",
        "use_sudo": False,
        "cfg": cfg,
    }
    assert calls[2] == {
        "host": "192.0.2.11",
        "command": "pvesh get /cluster/resources --type node --output-format json",
        "key_path": "/credentials/freq-admin",
        "command_timeout": 15,
        "htype": "pve",
        "use_sudo": True,
        "cfg": cfg,
    }
    assert calls[3] == {
        "host": "192.0.2.11",
        "command": "cat /etc/pve/corosync.conf 2>/dev/null",
        "key_path": "/credentials/freq-admin",
        "command_timeout": 10,
        "htype": "pve",
        "use_sudo": True,
        "cfg": cfg,
    }
    with pve_discovery._bg_lock:
        assert pve_discovery._bg_cache["pve_nodes"] == {
            "nodes": [
                {
                    "name": "pve02",
                    "ip": "192.0.2.27",
                    "status": "online",
                    "cores": 16,
                    "ram_gb": 32,
                },
                {
                    "name": "pve01",
                    "ip": "192.0.2.26",
                    "status": "offline",
                    "cores": 8,
                    "ram_gb": 16,
                },
            ],
            "discovered_at": 1000.0,
        }
        assert pve_discovery._bg_cache_ts["pve_nodes"] == 1000.0


def test_no_reachable_seed_updates_only_timestamp(monkeypatch):
    cfg = SimpleNamespace(
        pve_nodes=["192.0.2.10", "192.0.2.11"],
        ssh_key_path="/credentials/freq-admin",
    )
    previous = {"nodes": [{"name": "old", "ip": "192.0.2.9"}]}
    with pve_discovery._bg_lock:
        pve_discovery._bg_cache["pve_nodes"] = previous
        pve_discovery._bg_cache_ts["pve_nodes"] = 0.0
    monkeypatch.setattr(pve_discovery, "load_config", lambda: cfg)
    monkeypatch.setattr(pve_discovery, "ssh_single", lambda **kwargs: _result(1))
    monkeypatch.setattr(pve_discovery.time, "time", lambda: 2000.0)

    pve_discovery._bg_discover_pve_nodes()

    with pve_discovery._bg_lock:
        assert pve_discovery._bg_cache["pve_nodes"] is previous
        assert pve_discovery._bg_cache_ts["pve_nodes"] == 2000.0


def test_discovery_error_caches_none_and_updates_timestamp(monkeypatch):
    previous = {"nodes": [{"name": "old", "ip": "192.0.2.9"}]}
    with pve_discovery._bg_lock:
        pve_discovery._bg_cache["pve_nodes"] = previous
        pve_discovery._bg_cache_ts["pve_nodes"] = 0.0
    monkeypatch.setattr(
        pve_discovery,
        "load_config",
        lambda: (_ for _ in ()).throw(RuntimeError("config unavailable")),
    )
    monkeypatch.setattr(pve_discovery.time, "time", lambda: 2100.0)

    pve_discovery._bg_discover_pve_nodes()

    with pve_discovery._bg_lock:
        assert pve_discovery._bg_cache["pve_nodes"] is None
        assert pve_discovery._bg_cache_ts["pve_nodes"] == 2100.0


def test_discovered_ip_lookup_preserves_reference_order_and_config_fallback(monkeypatch):
    from freq.modules import serve

    cfg = SimpleNamespace(
        pve_nodes=["192.0.2.30", "192.0.2.31"],
        ssh_key_path="/credentials/freq-admin",
        ssh_connect_timeout=7,
    )
    monkeypatch.setattr(pve_discovery, "load_config", lambda: cfg)
    with pve_discovery._bg_lock:
        pve_discovery._bg_cache["pve_nodes"] = {
            "nodes": [
                {"name": "pve02", "ip": "192.0.2.27"},
                {"name": "missing", "ip": ""},
                {"name": "pve01", "ip": "192.0.2.26"},
            ]
        }

    assert pve_discovery._get_discovered_node_ips() == ["192.0.2.27", "192.0.2.26"]

    with pve_discovery._bg_lock:
        pve_discovery._bg_cache["pve_nodes"] = {"nodes": [{"name": "missing", "ip": ""}]}
    assert pve_discovery._get_discovered_node_ips() == ["192.0.2.30", "192.0.2.31"]

    discovered_ips = ["192.0.2.27", "192.0.2.26", "192.0.2.25"]
    calls = []

    def expected_probe(host):
        return {
            "host": host,
            "command": "sudo pvesh get /version --output-format json",
            "key_path": "/credentials/freq-admin",
            "connect_timeout": 3,
            "command_timeout": 10,
            "htype": "pve",
            "use_sudo": False,
            "cfg": cfg,
        }

    def second_node_reachable(**kwargs):
        calls.append(kwargs)
        return _result(0 if kwargs["host"] == "192.0.2.26" else 1)

    monkeypatch.setattr(pve_discovery, "_get_discovered_node_ips", lambda: discovered_ips)
    monkeypatch.setattr(pve_discovery, "ssh_single", second_node_reachable)

    assert serve._find_reachable_pve_node is pve_discovery.find_reachable_pve_node
    assert serve._find_reachable_pve_node(cfg) == "192.0.2.26"
    assert calls == [expected_probe("192.0.2.27"), expected_probe("192.0.2.26")]
    assert all(call["cfg"] is cfg for call in calls)

    calls.clear()
    monkeypatch.setattr(
        pve_discovery,
        "ssh_single",
        lambda **kwargs: calls.append(kwargs) or _result(1),
    )
    assert serve._find_reachable_pve_node(cfg) is None
    assert calls == [expected_probe(host) for host in discovered_ips]
    assert all(call["cfg"] is cfg for call in calls)

    calls.clear()
    monkeypatch.setattr(pve_discovery, "_get_discovered_node_ips", lambda: [])
    assert serve._find_reachable_pve_node(cfg) is None
    assert calls == []

    _assert_backup_schedule_transport(monkeypatch, serve, cfg)


def test_discovered_rows_preserve_cached_reference_and_fleet_boundary_fallback(monkeypatch):
    cached_rows = [{"name": "pve02", "ip": "192.0.2.27", "cores": 16}]
    with pve_discovery._bg_lock:
        pve_discovery._bg_cache["pve_nodes"] = {"nodes": cached_rows}

    assert pve_discovery._get_discovered_nodes() is cached_rows

    cfg = SimpleNamespace(
        fleet_boundaries=SimpleNamespace(
            pve_nodes={
                "pve02": SimpleNamespace(name="pve02", ip="192.0.2.27", detail="secondary"),
                "pve01": SimpleNamespace(name="pve01", ip="192.0.2.26"),
            }
        )
    )
    monkeypatch.setattr(pve_discovery, "load_config", lambda: cfg)
    with pve_discovery._bg_lock:
        pve_discovery._bg_cache["pve_nodes"] = None

    assert pve_discovery._get_discovered_nodes() == [
        {"name": "pve02", "ip": "192.0.2.27", "detail": "secondary"},
        {"name": "pve01", "ip": "192.0.2.26", "detail": ""},
    ]
