"""Characterization for the Phase-3 dashboard VM visibility policy seam."""

from types import SimpleNamespace

from freq.services import vm_visibility


def _cfg(*, hosts=None, categories=None):
    return SimpleNamespace(
        hosts=hosts or [],
        fleet_boundaries=SimpleNamespace(categories=categories or {}),
    )


def test_label_normalization_preserves_existing_shape():
    assert vm_visibility._label_key("  Plex_Server  ") == "plex-server"
    assert vm_visibility._label_key(None) == ""
    assert vm_visibility._label_key(101) == "101"


def test_managed_identities_preserve_defaults_exclusions_and_int_coercion():
    hosts = [
        SimpleNamespace(label="Default_Managed", htype="docker", vmid="101"),
        SimpleNamespace(label="Unmanaged", htype="docker", vmid=102, managed=False),
        SimpleNamespace(label="PVE_Node", htype="pve", vmid=103, managed=True),
        SimpleNamespace(label="Negative", htype="vm", vmid=-7, managed=True),
        SimpleNamespace(label="Bad", htype="vm", vmid="not-an-id", managed=True),
        SimpleNamespace(label="Zero", htype="vm", vmid=0, managed=True),
        SimpleNamespace(label="", htype="vm", vmid=104, managed=True),
    ]

    labels, vmids = vm_visibility._managed_dashboard_vm_identities(_cfg(hosts=hosts))

    assert labels == {"default-managed", "negative", "bad", "zero"}
    assert vmids == {101, -7, 104}


def test_category_vmids_coerces_explicit_values_and_normalizes_ranges():
    assert vm_visibility._category_vmids(
        {
            "vmids": ["101", -7, 0, "bad", None],
            "range_start": "105",
            "range_end": 103,
        }
    ) == {-7, 0, 101, 103, 104, 105}
    assert vm_visibility._category_vmids(
        {"vmids": ["201", "bad"], "range_start": "invalid", "range_end": 203}
    ) == {201}


def test_scope_exact_names_tiers_templates_and_hidden_precedence():
    scope = vm_visibility._dashboard_vm_scope(
        _cfg(
            categories={
                "production": {"vmids": [101, 102]},
                "custom_admin": {"tier": "admin", "vmids": [201]},
                "custom_operator": {"tier": "operator", "vmids": [202]},
                "custom_case": {"tier": "Operator", "vmids": [203]},
                "Production": {"vmids": [204]},
                "templates": {"tier": "admin", "vmids": [9000]},
                "out_of_contract": {"tier": "admin", "vmids": [102, 400]},
                "Inventory_Only": {"tier": "admin", "vmids": [401]},
            }
        )
    )

    assert scope["visible_vmids"] == {101, 102, 201, 202, 401}
    assert scope["hidden_vmids"] == {102, 400}
    assert 9000 not in scope["visible_vmids"]
    assert 203 not in scope["visible_vmids"]
    assert 204 not in scope["visible_vmids"]
    assert scope["has_boundary_contract"] is True
    assert vm_visibility._dashboard_vm_visible({"vmid": 102}, scope) is False


def test_empty_recognized_categories_leave_managed_fallback_active():
    scope = vm_visibility._dashboard_vm_scope(
        _cfg(
            hosts=[SimpleNamespace(label="Plex_Server", htype="docker", vmid="101")],
            categories={"production": {"vmids": []}, "out_of_contract": {}},
        )
    )

    assert scope["has_boundary_contract"] is False
    assert vm_visibility._dashboard_vm_visible({"vmid": "101", "name": "other"}, scope) is True
    assert vm_visibility._dashboard_vm_visible({"vmid": "bad", "name": " plex_server "}, scope) is True
    assert vm_visibility._dashboard_vm_visible({"vmid": 999, "name": "unknown"}, scope) is False


def test_nonempty_contract_fails_unknown_ids_closed_before_managed_fallback():
    scope = vm_visibility._dashboard_vm_scope(
        _cfg(
            hosts=[SimpleNamespace(label="Plex", htype="docker", vmid=101)],
            categories={"production": {"vmids": [201]}},
        )
    )

    assert vm_visibility._dashboard_vm_visible({"vmid": 201}, scope) is True
    assert vm_visibility._dashboard_vm_visible({"vmid": 101, "name": "plex"}, scope) is False
    assert vm_visibility._dashboard_vm_visible(None, scope) is False
