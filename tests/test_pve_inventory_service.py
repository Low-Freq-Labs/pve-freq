"""Characterization for the Phase-3 PVE VM inventory service seam."""

import json
from types import SimpleNamespace

import pytest

from freq.services import pve_inventory


class _Boundaries:
    def __init__(self):
        self.calls = []

    def categorize(self, vmid):
        self.calls.append(("categorize", vmid))
        return "production", "operator"

    def allowed_actions(self, vmid):
        self.calls.append(("allowed_actions", vmid))
        return ["view"]

    def is_prod(self, vmid):
        self.calls.append(("is_prod", vmid))
        return False


def _cfg():
    return SimpleNamespace(fleet_boundaries=_Boundaries())


def _patch_basics(monkeypatch, *, nodes=None, transport=None, visible=None, tags=None):
    monkeypatch.setattr(
        pve_inventory,
        "_get_discovered_node_ips",
        lambda: [] if nodes is None else nodes,
    )
    monkeypatch.setattr(pve_inventory, "_dashboard_vm_scope", lambda cfg: {"scope": True})
    monkeypatch.setattr(
        pve_inventory,
        "_dashboard_vm_visible",
        visible or (lambda vm, scope: True),
    )
    monkeypatch.setattr(pve_inventory, "get_vm_tags", tags or (lambda vmid: []))
    if transport is not None:
        monkeypatch.setattr(pve_inventory, "_pve_call", transport)


def test_empty_discovery_returns_fresh_empty_lists(monkeypatch):
    _patch_basics(monkeypatch)
    first = pve_inventory._get_fleet_vms(_cfg())
    second = pve_inventory._get_fleet_vms(_cfg())
    assert first == second == []
    assert first is not second


@pytest.mark.parametrize(
    "returned",
    [("failed", False), ("", True), ("not-json", True)],
)
def test_first_returned_node_always_stops_even_on_failure_empty_or_malformed(monkeypatch, returned):
    calls = []

    def transport(cfg, node_ip, **kwargs):
        calls.append((node_ip, kwargs))
        return returned

    _patch_basics(monkeypatch, nodes=["192.0.2.10", "192.0.2.11"], transport=transport)
    assert pve_inventory._get_fleet_vms(_cfg()) == []
    assert calls == [
        (
            "192.0.2.10",
            {
                "api_endpoint": "/cluster/resources?type=vm",
                "ssh_command": "pvesh get /cluster/resources --type vm --output-format json",
                "timeout": 15,
            },
        )
    ]


def test_discovery_scope_and_transport_exceptions_propagate(monkeypatch):
    cfg = _cfg()
    monkeypatch.setattr(
        pve_inventory,
        "_dashboard_vm_scope",
        lambda cfg: (_ for _ in ()).throw(RuntimeError("scope failed")),
    )
    with pytest.raises(RuntimeError, match="scope failed"):
        pve_inventory._get_fleet_vms(cfg)

    monkeypatch.setattr(pve_inventory, "_dashboard_vm_scope", lambda cfg: {})
    monkeypatch.setattr(pve_inventory, "_get_discovered_node_ips", lambda: ["192.0.2.10"])
    monkeypatch.setattr(
        pve_inventory,
        "_pve_call",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("transport failed")),
    )
    with pytest.raises(RuntimeError, match="transport failed"):
        pve_inventory._get_fleet_vms(cfg)


@pytest.mark.parametrize("as_json", [False, True])
def test_direct_list_and_json_results_preserve_raw_dependency_calls(monkeypatch, as_json):
    vmid = "101"
    rows = [{"vmid": vmid, "name": " plex ", "node": "pve01", "type": "qemu"}]
    tags_seen = []

    _patch_basics(
        monkeypatch,
        nodes=["192.0.2.10"],
        transport=lambda *args, **kwargs: (json.dumps(rows) if as_json else rows, True),
        tags=lambda value: tags_seen.append(value) or ["prod"],
    )
    cfg = _cfg()
    result = pve_inventory._get_fleet_vms(cfg)

    assert result[0]["vmid"] == vmid
    assert result[0]["name"] == "plex"
    assert result[0]["category"] == "production"
    assert result[0]["tier"] == "operator"
    assert result[0]["tags"] == ["prod"]
    assert result[0]["is_prod"] is True
    assert tags_seen == [vmid]
    assert cfg.fleet_boundaries.calls == [
        ("categorize", vmid),
        ("allowed_actions", vmid),
        ("is_prod", vmid),
    ]


def test_truthy_template_flag_short_circuits_invalid_vmid_and_visibility(monkeypatch):
    visible_calls = []
    row = {"vmid": "not-an-int", "template": "yes", "name": "template"}
    _patch_basics(
        monkeypatch,
        nodes=["192.0.2.10"],
        transport=lambda *args, **kwargs: ([row], True),
        visible=lambda *args: visible_calls.append(args) or False,
    )
    cfg = _cfg()
    result = pve_inventory._get_fleet_vms(cfg)

    assert result[0]["category"] == "templates"
    assert result[0]["tier"] == "protected"
    assert visible_calls == []
    assert not any(call[0] == "categorize" for call in cfg.fleet_boundaries.calls)


@pytest.mark.parametrize(
    ("vmid", "is_template"),
    [(8999, False), (9000, True), (9999, True), (10000, False)],
)
def test_template_range_boundaries(monkeypatch, vmid, is_template):
    _patch_basics(
        monkeypatch,
        nodes=["192.0.2.10"],
        transport=lambda *args, **kwargs: ([{"vmid": vmid, "name": "row"}], True),
    )
    result = pve_inventory._get_fleet_vms(_cfg())
    assert (result[0]["category"] == "templates") is is_template


def test_visibility_rejection_precedes_category_and_tags(monkeypatch):
    tag_calls = []
    _patch_basics(
        monkeypatch,
        nodes=["192.0.2.10"],
        transport=lambda *args, **kwargs: ([{"vmid": 101, "name": "hidden"}], True),
        visible=lambda vm, scope: False,
        tags=lambda vmid: tag_calls.append(vmid) or [],
    )
    cfg = _cfg()
    assert pve_inventory._get_fleet_vms(cfg) == []
    assert tag_calls == []
    assert cfg.fleet_boundaries.calls == []


@pytest.mark.parametrize(
    ("config_result", "config_ok", "expected"),
    [
        ({"name": " from dict "}, True, "from dict"),
        ('{"name":" from json "}', True, "from json"),
        ("not-json", True, "vm-101"),
        ({"name": "ignored"}, False, "vm-101"),
        ({"name": ""}, True, "vm-101"),
    ],
)
def test_blank_name_config_recovery_and_fallback(monkeypatch, config_result, config_ok, expected):
    calls = []

    def transport(cfg, node_ip, **kwargs):
        calls.append((node_ip, kwargs))
        if len(calls) == 1:
            return [{"vmid": 101, "name": " ", "node": "pve02"}], True
        return config_result, config_ok

    _patch_basics(monkeypatch, nodes=["192.0.2.10"], transport=transport)
    result = pve_inventory._get_fleet_vms(_cfg())
    assert result[0]["name"] == expected
    assert calls[1] == (
        "192.0.2.10",
        {
            "api_endpoint": "/nodes/pve02/qemu/101/config",
            "ssh_command": "pvesh get /nodes/pve02/qemu/101/config --output-format json",
            "timeout": 10,
        },
    )


def test_metrics_preserve_numeric_bool_string_float_and_upper_only_cap(monkeypatch):
    mib = 1024 * 1024
    rows = [
        {"vmid": 101, "name": "a", "cpu": 0.126, "maxcpu": 4, "mem": 3 * mib, "maxmem": 2 * mib},
        {"vmid": 102, "name": "b", "cpu": True, "mem": -1 * mib, "maxmem": 2 * mib},
        {"vmid": 103, "name": "c", "cpu": "0.5", "mem": 1.5 * mib, "maxmem": 4.0 * mib},
    ]
    _patch_basics(
        monkeypatch,
        nodes=["192.0.2.10"],
        transport=lambda *args, **kwargs: (rows, True),
    )
    result = pve_inventory._get_fleet_vms(_cfg())
    assert [(row["cpu_pct"], row["ram_mb"], row["ram_used_mb"], row["ram_pct"]) for row in result] == [
        (12.6, 2, 3, 100.0),
        (100, 2, -1, -50.0),
        (0, 4.0, 1.0, 37.5),
    ]


def test_outer_type_error_preserves_prior_rows_but_other_errors_propagate(monkeypatch):
    rows = [
        {"vmid": 101, "name": "first"},
        {"vmid": 102, "name": "second", "maxmem": "bad", "mem": 1},
        {"vmid": 103, "name": "never"},
    ]
    _patch_basics(
        monkeypatch,
        nodes=["192.0.2.10"],
        transport=lambda *args, **kwargs: (rows, True),
    )
    assert [row["vmid"] for row in pve_inventory._get_fleet_vms(_cfg())] == [101]

    _patch_basics(
        monkeypatch,
        nodes=["192.0.2.10"],
        transport=lambda *args, **kwargs: ([{"vmid": "invalid", "name": "row"}], True),
    )
    with pytest.raises(ValueError):
        pve_inventory._get_fleet_vms(_cfg())

    _patch_basics(
        monkeypatch,
        nodes=["192.0.2.10"],
        transport=lambda *args, **kwargs: ([object()], True),
    )
    with pytest.raises(AttributeError):
        pve_inventory._get_fleet_vms(_cfg())
