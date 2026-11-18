"""Characterization for the Phase-3 PVE VM-tag service seam."""

from types import SimpleNamespace

import pytest

from freq.services import pve_tags


@pytest.fixture(autouse=True)
def _restore_vm_tag_cache():
    missing = object()
    with pve_tags._bg_lock:
        old_cache = pve_tags._bg_cache.get("vm_tags", missing)
        old_ts = pve_tags._bg_cache_ts.get("vm_tags", missing)
    try:
        yield
    finally:
        with pve_tags._bg_lock:
            if old_cache is missing:
                pve_tags._bg_cache.pop("vm_tags", None)
            else:
                pve_tags._bg_cache["vm_tags"] = old_cache
            if old_ts is missing:
                pve_tags._bg_cache_ts.pop("vm_tags", None)
            else:
                pve_tags._bg_cache_ts["vm_tags"] = old_ts


def _result(returncode=0, stdout=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout)


def _set_tag_state(cache, timestamp):
    with pve_tags._bg_lock:
        pve_tags._bg_cache["vm_tags"] = cache
        pve_tags._bg_cache_ts["vm_tags"] = timestamp


def test_fresh_tag_cache_short_circuits_without_dependencies(monkeypatch):
    _set_tag_state({"tags": {101: ["prod"]}}, 900.0)
    monkeypatch.setattr(pve_tags.time, "time", lambda: 1000.0)
    monkeypatch.setattr(pve_tags, "load_config", lambda: pytest.fail("fresh cache loaded config"))
    monkeypatch.setattr(
        pve_tags,
        "_get_discovered_node_ips",
        lambda: pytest.fail("fresh cache read discovery"),
    )
    monkeypatch.setattr(pve_tags, "ssh_single", lambda **kwargs: pytest.fail(f"fresh cache used SSH: {kwargs}"))

    assert pve_tags._bg_fetch_vm_tags() is None


@pytest.mark.parametrize("failure", ["no_nodes", "cluster_failure"])
def test_early_return_preserves_cache_and_timestamp(monkeypatch, failure):
    previous = {"tags": {101: ["old"]}}
    _set_tag_state(previous, 7.0)
    cfg = SimpleNamespace(ssh_key_path="/credentials/freq-admin")
    monkeypatch.setattr(pve_tags, "load_config", lambda: cfg)
    monkeypatch.setattr(pve_tags.time, "time", lambda: 1000.0)
    if failure == "no_nodes":
        monkeypatch.setattr(pve_tags, "_get_discovered_node_ips", lambda: [])
        monkeypatch.setattr(pve_tags, "ssh_single", lambda **kwargs: pytest.fail(f"no nodes used SSH: {kwargs}"))
    else:
        monkeypatch.setattr(pve_tags, "_get_discovered_node_ips", lambda: ["192.0.2.10"])
        monkeypatch.setattr(pve_tags, "ssh_single", lambda **kwargs: _result(1))

    pve_tags._bg_fetch_vm_tags()

    with pve_tags._bg_lock:
        assert pve_tags._bg_cache["vm_tags"] is previous
        assert pve_tags._bg_cache_ts["vm_tags"] == 7.0


def test_fetch_preserves_commands_grouping_skips_and_tag_parsing(monkeypatch):
    cfg = SimpleNamespace(ssh_key_path="/credentials/freq-admin")
    calls = []
    cluster_rows = (
        '[{"type":"qemu","node":"pve02","vmid":101},'
        '{"type":"lxc","node":"pve02","vmid":201},'
        '{"type":"qemu","node":"missing","vmid":102},'
        '{"type":"qemu","node":"pve02","vmid":103}]'
    )

    def fake_ssh(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _result(stdout=cluster_rows)
        return _result(stdout="VMID:101\ntags: prod, critical ; protected\nVMID:103\ntags: lab; test , edge\n")

    _set_tag_state({"tags": {999: ["old"]}}, 0.0)
    monkeypatch.setattr(pve_tags, "load_config", lambda: cfg)
    monkeypatch.setattr(pve_tags, "_get_discovered_node_ips", lambda: ["192.0.2.10", "192.0.2.11"])
    monkeypatch.setattr(
        pve_tags,
        "_get_discovered_nodes",
        lambda: [
            {"name": "pve01", "ip": "192.0.2.26"},
            {"name": "pve02", "ip": "192.0.2.27"},
            {"name": "", "ip": "192.0.2.99"},
        ],
    )
    monkeypatch.setattr(pve_tags, "ssh_single", fake_ssh)
    monkeypatch.setattr(pve_tags.time, "time", lambda: 1000.0)

    pve_tags._bg_fetch_vm_tags()

    assert calls[0] == {
        "host": "192.0.2.10",
        "command": "pvesh get /cluster/resources --type vm --output-format json",
        "key_path": "/credentials/freq-admin",
        "command_timeout": 15,
        "htype": "pve",
        "use_sudo": True,
        "cfg": cfg,
    }
    assert calls[1] == {
        "host": "192.0.2.27",
        "command": (
            "echo VMID:101; grep '^tags' /etc/pve/qemu-server/101.conf 2>/dev/null || true; "
            "echo VMID:103; grep '^tags' /etc/pve/qemu-server/103.conf 2>/dev/null || true"
        ),
        "key_path": "/credentials/freq-admin",
        "command_timeout": 30,
        "htype": "pve",
        "use_sudo": True,
        "cfg": cfg,
        "failure_log_level": "warn",
    }
    assert len(calls) == 2
    with pve_tags._bg_lock:
        assert pve_tags._bg_cache["vm_tags"] == {
            "tags": {
                101: ["prod", "critical", "protected"],
                103: ["lab", "test", "edge"],
            },
            "fetched_at": 1000.0,
        }
        assert pve_tags._bg_cache_ts["vm_tags"] == 1000.0


def test_fetch_exception_caches_none_and_updates_timestamp(monkeypatch):
    _set_tag_state({"tags": {101: ["old"]}}, 0.0)
    monkeypatch.setattr(
        pve_tags,
        "load_config",
        lambda: (_ for _ in ()).throw(RuntimeError("config unavailable")),
    )
    monkeypatch.setattr(pve_tags.time, "time", lambda: 1100.0)

    pve_tags._bg_fetch_vm_tags()

    with pve_tags._bg_lock:
        assert pve_tags._bg_cache["vm_tags"] is None
        assert pve_tags._bg_cache_ts["vm_tags"] == 1100.0


def test_accessors_preserve_list_reference_miss_and_membership():
    tags = ["prod", "critical"]
    _set_tag_state({"tags": {101: tags}}, 1.0)

    assert pve_tags.get_vm_tags(101) is tags
    assert pve_tags.get_vm_tags(999) == []
    assert pve_tags.is_vm_tagged(101, "prod") is True
    assert pve_tags.is_vm_tagged(101, "lab") is False


def test_cli_vm_safety_uses_stable_tag_patch_point(monkeypatch):
    from freq.modules import vm

    cfg = SimpleNamespace(protected_vmids=[], protected_ranges=[])
    monkeypatch.setattr(vm, "get_vm_tags", lambda vmid: ["prod"])
    assert vm._safety_check(cfg, 101, "destroy") is False
    monkeypatch.setattr(vm, "get_vm_tags", lambda vmid: ["lab"])
    assert vm._safety_check(cfg, 101, "destroy") is True


def test_cli_pve_power_uses_stable_tag_patch_point(monkeypatch):
    from freq.modules import pve

    cfg = SimpleNamespace(protected_vmids=[], protected_ranges=[], pve_api_token_id="", pve_api_token_secret="")
    args = SimpleNamespace(action="stop", target="101")
    monkeypatch.setattr(pve, "get_vm_tags", lambda vmid: ["prod"])
    assert pve.cmd_power(cfg, None, args) == 1

    monkeypatch.setattr(pve, "get_vm_tags", lambda vmid: ["lab"])
    monkeypatch.setattr(pve, "_find_reachable_node", lambda cfg: "192.0.2.10")
    monkeypatch.setattr(pve, "_find_vm_node", lambda cfg, vmid, node_ip: node_ip)
    monkeypatch.setattr(pve, "_pve_cmd", lambda cfg, node_ip, command, timeout=60: ("ok", True))
    assert pve.cmd_power(cfg, None, args) == 0
