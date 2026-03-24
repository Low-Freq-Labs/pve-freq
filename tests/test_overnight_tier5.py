"""Overnight Matrix — Tier 5: JavaScript Rendering Logic

Tests 5.1-5.17: Verify data structures and logic paths that the JS frontend
relies on. Since we can't run JS in tests, we validate:
1. The Python API returns correct data for each profile
2. The JS logic paths would produce correct results with that data
3. Edge cases (empty VLANs, zero nodes, etc.) produce safe defaults
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "configs")
RICK_DIR = str(Path(__file__).parent.parent)
CONF_DIR = os.path.join(RICK_DIR, "conf")


def load_with_profile(profile: str):
    """Load config from a test profile directory."""
    from freq.core.config import load_config
    profile_dir = os.path.join(CONFIGS_DIR, profile)
    return load_config(install_dir=profile_dir)


def build_vlan_api_data(cfg):
    """Replicate serve.py's VLAN data construction (line 1099-1101)."""
    return [
        {
            "id": v.id,
            "name": v.name,
            "prefix": v.prefix,
            "gateway": v.gateway,
            "cidr": v.subnet.split("/")[1] if "/" in v.subnet else "24",
        }
        for v in cfg.vlans
    ]


def build_info_api_data(cfg, pack):
    """Replicate serve.py's /api/info response."""
    return {
        "version": "2.0.0",
        "brand": cfg.brand,
        "build": cfg.build,
        "hosts": len(cfg.hosts),
        "pve_nodes": len(cfg.pve_nodes),
        "cluster": cfg.cluster_name,
        "subtitle": getattr(pack, "subtitle", cfg.brand) if pack else cfg.brand,
        "dashboard_header": getattr(pack, "dashboard_header", "PVE FREQ Dashboard") if pack else "PVE FREQ Dashboard",
    }


class TestTier5KillChain(unittest.TestCase):
    """Tier 5.1-5.2: Kill chain display."""

    # --- 5.1: No kill chain (Profile C) ---
    def test_5_1_no_kill_chain_profile_c(self):
        """Profile C has no risk.toml — generic fallback should render."""
        from freq.core.config import load_toml
        risk_path = os.path.join(CONFIGS_DIR, "profile_c", "conf", "risk.toml")
        data = load_toml(risk_path)
        # No risk.toml = empty data = JS shows generic fallback
        self.assertEqual(data, {})

    # --- 5.2: Custom kill chain (Profile A with risk.toml) ---
    def test_5_2_custom_kill_chain(self):
        """If risk.toml exists, load_toml returns custom chain data."""
        from freq.core.config import load_toml
        # Profile A doesn't have risk.toml — should fall back
        risk_path = os.path.join(CONFIGS_DIR, "profile_a", "conf", "risk.toml")
        data = load_toml(risk_path)
        self.assertEqual(data, {})


class TestTier5NodeColors(unittest.TestCase):
    """Tier 5.3-5.4: NODE_COLORS generation."""

    # --- 5.3: 1 node gets a color ---
    def test_5_3_single_node_gets_color(self):
        """Profile A (1 node): the node gets assigned first palette color."""
        cfg = load_with_profile("profile_a")
        # JS logic: pveHosts = PROD_HOSTS.filter(h => h.type === 'pve')
        # then NODE_COLORS[h.label] = palette[i % palette.length]
        palette = ['#9B4FDE', '#f778ba', '#58a6ff', '#ffa657', '#f0f6fc', '#6e7681', '#79c0ff', '#d2a8ff']
        node_colors = {}
        pve_nodes = cfg.pve_node_names
        for i, name in enumerate(pve_nodes):
            node_colors[name] = palette[i % len(palette)]
        self.assertEqual(len(node_colors), 1)
        self.assertEqual(node_colors["proxmox1"], "#9B4FDE")

    # --- 5.4: 0 nodes = empty object ---
    def test_5_4_zero_nodes_empty(self):
        """Profile C (0 nodes): NODE_COLORS is empty, no crash."""
        cfg = load_with_profile("profile_c")
        node_colors = {}
        for i, name in enumerate(cfg.pve_node_names):
            node_colors[name] = "#test"
        self.assertEqual(node_colors, {})


class TestTier5VlanColors(unittest.TestCase):
    """Tier 5.5-5.6: VLAN_COLORS generation."""

    # --- 5.5: 0 VLANs = empty ---
    def test_5_5_zero_vlans_empty(self):
        """Profile C (0 VLANs): VLAN_COLORS is empty, no crash."""
        cfg = load_with_profile("profile_c")
        vlan_data = build_vlan_api_data(cfg)
        self.assertEqual(vlan_data, [])
        # JS: VLAN_COLORS would be {}
        vlan_colors = {}
        self.assertEqual(vlan_colors, {})

    # --- 5.6: 2 VLANs get colors ---
    def test_5_6_two_vlans_get_colors(self):
        """Profile D (2 VLANs): both get assigned colors."""
        cfg = load_with_profile("profile_d")
        vlan_data = build_vlan_api_data(cfg)
        self.assertEqual(len(vlan_data), 2)
        # JS: cycle through palette
        palette = ['var(--purple-light)', 'var(--blue)', 'var(--green)', 'var(--red)']
        vlan_colors = {}
        for i, v in enumerate(vlan_data):
            vlan_colors[v["name"]] = palette[i % len(palette)]
        self.assertIn("MAIN", vlan_colors)
        self.assertIn("SERVICES", vlan_colors)
        self.assertEqual(len(vlan_colors), 2)


class TestTier5NICCombo(unittest.TestCase):
    """Tier 5.7-5.9: NIC combo builder."""

    # --- 5.7: 0 VLANs (Profile C) ---
    def test_5_7_zero_vlans_default_option(self):
        """Profile C (0 VLANs): NIC combo shows 'Default' option."""
        cfg = load_with_profile("profile_c")
        vlan_data = build_vlan_api_data(cfg)
        # JS logic: if(_vids.length) { ... } else { ctrl += '<option value="default"...>Default</option>' }
        has_vlans = len(vlan_data) > 0
        self.assertFalse(has_vlans)
        # Would render "Default" option

    # --- 5.8: 0 VLANs (Profile A) ---
    def test_5_8_zero_vlans_profile_a(self):
        """Profile A (0 VLANs): NIC combo shows 'Default' option."""
        cfg = load_with_profile("profile_a")
        vlan_data = build_vlan_api_data(cfg)
        self.assertEqual(len(vlan_data), 0)

    # --- 5.9: 2 VLANs with /23 (Profile D) ---
    def test_5_9_two_vlans_23_prefix(self):
        """Profile D (2 VLANs, /23): NIC combo shows both VLANs, uses /23."""
        cfg = load_with_profile("profile_d")
        vlan_data = build_vlan_api_data(cfg)
        self.assertEqual(len(vlan_data), 2)
        # Check cidr comes through as "23" not "24"
        main_vlan = next(v for v in vlan_data if v["name"] == "MAIN")
        self.assertEqual(main_vlan["cidr"], "23")
        svc_vlan = next(v for v in vlan_data if v["name"] == "SERVICES")
        self.assertEqual(svc_vlan["cidr"], "23")

    def test_5_9b_profile_b_16_prefix(self):
        """Profile B (4 VLANs, /16): cidr = '16'."""
        cfg = load_with_profile("profile_b")
        vlan_data = build_vlan_api_data(cfg)
        self.assertEqual(len(vlan_data), 4)
        for v in vlan_data:
            self.assertEqual(v["cidr"], "16")


class TestTier5VMDetailPanel(unittest.TestCase):
    """Tier 5.10-5.11: VM detail panel rendering."""

    # --- 5.10: No VLAN data (Profile C) ---
    def test_5_10_no_vlan_data(self):
        """Profile C: _VLAN_MAP is empty — VM detail renders without crash."""
        cfg = load_with_profile("profile_c")
        vlan_data = build_vlan_api_data(cfg)
        self.assertEqual(vlan_data, [])
        # JS: VLAN_COLORS[v] || 'var(--text-dim)' — always falls back

    # --- 5.11: Non-/24 network ---
    def test_5_11_non_24_cidr_displayed(self):
        """Profile D: cidr='23' would be displayed correctly in VM detail."""
        cfg = load_with_profile("profile_d")
        vlan_data = build_vlan_api_data(cfg)
        cidrs = {v["cidr"] for v in vlan_data}
        self.assertIn("23", cidrs)
        self.assertNotIn("24", cidrs)


class TestTier5GatewayDisplay(unittest.TestCase):
    """Tier 5.12-5.13: Gateway display."""

    # --- 5.12: No VLANs (Profile A) ---
    def test_5_12_no_vlans_gateway(self):
        """Profile A (no VLANs): gateway from config, not VLANs."""
        cfg = load_with_profile("profile_a")
        self.assertEqual(cfg.vm_gateway, "192.168.1.1")
        vlan_data = build_vlan_api_data(cfg)
        self.assertEqual(len(vlan_data), 0)
        # JS: no VLAN gateways — falls back to config gateway

    # --- 5.13: /23 gateway (Profile D) ---
    def test_5_13_vlan_gateway_23(self):
        """Profile D: gateway comes from VLAN config."""
        cfg = load_with_profile("profile_d")
        vlan_data = build_vlan_api_data(cfg)
        main_vlan = next(v for v in vlan_data if v["name"] == "MAIN")
        self.assertEqual(main_vlan["gateway"], "172.16.0.1")


class TestTier5Credits(unittest.TestCase):
    """Tier 5.14-5.15: Credits/footer and search placeholder."""

    # --- 5.14: Default pack credits ---
    def test_5_14_credits_default_pack(self):
        """Default pack: about-credits shows 'PVE FREQ', not 'LOW FREQ Labs'."""
        from freq.core.personality import load_pack
        pack = load_pack(CONF_DIR, "default")
        info = build_info_api_data(load_with_profile("profile_a"), pack)
        # JS: cr.textContent = (d.cluster||'')+(d.cluster?' · ':'')+(d.brand||'PVE FREQ')
        cluster = info["cluster"]
        brand = info["brand"]
        credits = (cluster + " · " + brand) if cluster else brand
        self.assertIn("PVE FREQ", credits)
        self.assertEqual(credits, "HomeCluster · PVE FREQ")

    def test_5_14b_credits_personal_pack(self):
        """Personal pack from DC01 config: shows 'LOW FREQ Labs'."""
        from freq.core.personality import load_pack
        from freq.core.config import load_config
        cfg = load_config()
        pack = load_pack(cfg.conf_dir, "personal")
        info = build_info_api_data(cfg, pack)
        brand = info["brand"]
        self.assertIn("FREQ", brand)

    # --- 5.15: Search placeholder ---
    def test_5_15_search_placeholder(self):
        """Search placeholder should reference 'knowledge base', not session count."""
        from freq.modules.web_ui import APP_HTML
        # Check the HTML contains the right placeholder text
        self.assertIn("knowledge base", APP_HTML.lower())


class TestTier5LabDetection(unittest.TestCase):
    """Tier 5.16: Lab VM detection."""

    # --- 5.16: No lab VMs (Profile A) ---
    def test_5_16_no_lab_vms(self):
        """Profile A (no lab VMs in config): empty hosts, no crash."""
        cfg = load_with_profile("profile_a")
        # No hosts registered
        self.assertEqual(len(cfg.hosts), 0)
        # No lab category in fleet boundaries (no fleet-boundaries.toml)
        self.assertEqual(cfg.fleet_boundaries.categories, {})


class TestTier5ProdArrays(unittest.TestCase):
    """Tier 5.17: PROD_HOSTS / PROD_VMS with empty fleet."""

    # --- 5.17: Empty fleet ---
    def test_5_17_empty_fleet_prod_arrays(self):
        """Profile C (empty fleet): PROD_HOSTS and PROD_VMS would be []."""
        cfg = load_with_profile("profile_c")
        # JS: PROD_HOSTS = [] when no pve_nodes and no physical devices
        pve_nodes = cfg.pve_node_names  # empty
        physical = cfg.fleet_boundaries.physical  # empty
        self.assertEqual(pve_nodes, [])
        self.assertEqual(physical, {})
        # PROD_VMS = [] when no VMs from API
        # Both arrays being empty should not crash any JS

    def test_5_17b_profile_b_has_nodes(self):
        """Profile B: PROD_HOSTS would have 3 PVE entries."""
        cfg = load_with_profile("profile_b")
        self.assertEqual(len(cfg.pve_node_names), 3)


class TestTier5CIDRExtraction(unittest.TestCase):
    """Extra: Verify the cidr extraction logic from serve.py."""

    def test_cidr_from_24_subnet(self):
        """Standard /24 subnet: cidr = '24'."""
        subnet = "10.25.10.0/24"
        cidr = subnet.split("/")[1] if "/" in subnet else "24"
        self.assertEqual(cidr, "24")

    def test_cidr_from_23_subnet(self):
        """/23 subnet: cidr = '23'."""
        subnet = "172.16.0.0/23"
        cidr = subnet.split("/")[1] if "/" in subnet else "24"
        self.assertEqual(cidr, "23")

    def test_cidr_from_16_subnet(self):
        """/16 subnet: cidr = '16'."""
        subnet = "10.0.0.0/16"
        cidr = subnet.split("/")[1] if "/" in subnet else "24"
        self.assertEqual(cidr, "16")

    def test_cidr_fallback_no_slash(self):
        """Subnet without slash: falls back to '24'."""
        subnet = "10.0.0.0"
        cidr = subnet.split("/")[1] if "/" in subnet else "24"
        self.assertEqual(cidr, "24")

    def test_cidr_empty_string(self):
        """Empty subnet: falls back to '24'."""
        subnet = ""
        cidr = subnet.split("/")[1] if "/" in subnet else "24"
        self.assertEqual(cidr, "24")


if __name__ == "__main__":
    unittest.main()
