"""Tests for Phase 2 — The Gateway: firewall, DNS, VPN, certs, proxy.

Covers: Module imports, CLI registration, DHCP parser, WireGuard parser,
        DNS inventory CRUD, proxy backend detection.
"""
import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Mock Config
# ---------------------------------------------------------------------------

@dataclass
class MockHost:
    ip: str
    label: str
    htype: str
    groups: str = ""
    hostname: str = ""
    service_tag: str = ""
    identity_source: str = ""


class MockConfig:
    def __init__(self, tmpdir=None):
        self.conf_dir = tmpdir or tempfile.mkdtemp()
        self.data_dir = os.path.join(self.conf_dir, "data")
        self.hosts = [
            MockHost("10.25.255.5", "switch", "switch"),
            MockHost("10.25.255.1", "pfsense", "pfsense"),
        ]
        self.pfsense_ip = "10.25.255.1"
        self.truenas_ip = "10.25.255.25"
        self.pve_nodes = ["10.25.255.26", "10.25.255.27", "10.25.255.28"]
        self.pve_node_names = ["pve01", "pve02", "pve03"]
        self.switch_ip = "10.25.255.5"
        self.ssh_key_path = "/tmp/test"
        self.ssh_rsa_key_path = "/tmp/test_rsa"
        self.ssh_connect_timeout = 5
        self.ssh_service_account = "dc01-admin"
        self.certificates = {}
        self.cert_targets = []


# ---------------------------------------------------------------------------
# Firewall Tests
# ---------------------------------------------------------------------------

DHCP_LEASES = """
lease 10.25.255.100 {
  starts 2 2026/04/01 12:00:00;
  ends 2 2026/04/01 20:00:00;
  hardware ethernet aa:bb:cc:dd:ee:01;
  client-hostname "desktop-01";
}
lease 10.25.255.101 {
  starts 2 2026/04/01 13:00:00;
  ends 2 2026/04/01 21:00:00;
  hardware ethernet aa:bb:cc:dd:ee:02;
  client-hostname "laptop-02";
}
"""


class TestDHCPParser(unittest.TestCase):
    """Test DHCP lease parsing."""

    def setUp(self):
        from freq.modules.firewall import _parse_dhcp_leases
        self.parse = _parse_dhcp_leases

    def test_parse_leases(self):
        leases = self.parse(DHCP_LEASES)
        self.assertEqual(len(leases), 2)

    def test_lease_fields(self):
        leases = self.parse(DHCP_LEASES)
        l = leases[0]
        self.assertEqual(l["ip"], "10.25.255.100")
        self.assertEqual(l["mac"], "aa:bb:cc:dd:ee:01")
        self.assertEqual(l["hostname"], "desktop-01")

    def test_empty_input(self):
        self.assertEqual(self.parse(""), [])


class TestFirewallImports(unittest.TestCase):
    """Test firewall module imports."""

    def test_all_commands(self):
        from freq.modules.firewall import (
            cmd_fw_status, cmd_fw_rules, cmd_fw_nat,
            cmd_fw_states, cmd_fw_interfaces, cmd_fw_gateways,
            cmd_fw_dhcp,
        )
        self.assertTrue(callable(cmd_fw_status))


# ---------------------------------------------------------------------------
# DNS Tests
# ---------------------------------------------------------------------------

class TestDNSInventory(unittest.TestCase):
    """Test DNS internal record CRUD."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = MockConfig(self.tmpdir)

    def test_add_and_list(self):
        from freq.modules.dns_management import _load_dns_inventory, _save_dns_inventory
        data = _load_dns_inventory(self.cfg)
        data["records"].append({"hostname": "test.local", "ip": "10.0.0.1", "type": "A"})
        _save_dns_inventory(self.cfg, data)
        reloaded = _load_dns_inventory(self.cfg)
        self.assertEqual(len(reloaded["records"]), 1)

    def test_empty_load(self):
        from freq.modules.dns_management import _load_dns_inventory
        data = _load_dns_inventory(self.cfg)
        self.assertEqual(data["records"], [])


class TestDNSImports(unittest.TestCase):
    """Test DNS management module imports."""

    def test_all_commands(self):
        from freq.modules.dns_management import (
            cmd_dns_internal_list, cmd_dns_internal_add,
            cmd_dns_internal_remove, cmd_dns_internal_sync,
            cmd_dns_internal_audit,
        )
        self.assertTrue(callable(cmd_dns_internal_list))


# ---------------------------------------------------------------------------
# VPN Tests
# ---------------------------------------------------------------------------

WG_SHOW_OUTPUT = """interface: wg0
  public key: abcdef1234567890abcdef1234567890abcdef123456=
  private key: (hidden)
  listening port: 51820

peer: QRSTUVWXYZ1234567890abcdef1234567890abcdef12=
  endpoint: 203.0.113.50:51820
  allowed ips: 10.25.100.2/32
  latest handshake: 1 minute, 30 seconds ago
  transfer: 1.5 MiB received, 3.2 MiB sent
"""


class TestWGParser(unittest.TestCase):
    """Test WireGuard output parser."""

    def setUp(self):
        from freq.modules.vpn import _parse_wg_show
        self.parse = _parse_wg_show

    def test_parse_peers(self):
        peers = self.parse(WG_SHOW_OUTPUT)
        self.assertEqual(len(peers), 1)

    def test_peer_fields(self):
        peers = self.parse(WG_SHOW_OUTPUT)
        p = peers[0]
        self.assertEqual(p["interface"], "wg0")
        self.assertIn("QRSTUVWXYZ", p["public_key"])
        self.assertIn("203.0.113.50", p["endpoint"])

    def test_empty_input(self):
        self.assertEqual(self.parse(""), [])


class TestVPNImports(unittest.TestCase):
    """Test VPN module imports."""

    def test_all_commands(self):
        from freq.modules.vpn import (
            cmd_vpn_wg_status, cmd_vpn_wg_peers, cmd_vpn_wg_audit,
            cmd_vpn_ovpn_status,
        )
        self.assertTrue(callable(cmd_vpn_wg_status))


# ---------------------------------------------------------------------------
# Certificate Tests
# ---------------------------------------------------------------------------

class TestCertImports(unittest.TestCase):
    """Test cert management module imports."""

    def test_all_commands(self):
        from freq.modules.cert_management import (
            cmd_cert_inspect, cmd_cert_fleet_check,
            cmd_cert_acme_status, cmd_cert_issued_list,
            cmd_cert_plan, cmd_cert_bootstrap, cmd_cert_issue,
            cmd_cert_renew, cmd_cert_deploy, cmd_cert_dns_sync, cmd_cert_verify,
        )
        self.assertTrue(callable(cmd_cert_inspect))
        self.assertTrue(callable(cmd_cert_plan))
        self.assertTrue(callable(cmd_cert_bootstrap))
        self.assertTrue(callable(cmd_cert_issue))
        self.assertTrue(callable(cmd_cert_renew))
        self.assertTrue(callable(cmd_cert_deploy))
        self.assertTrue(callable(cmd_cert_dns_sync))
        self.assertTrue(callable(cmd_cert_verify))


class TestCertIssuedStorage(unittest.TestCase):
    """Test issued cert tracking."""

    def test_empty_load(self):
        from freq.modules.cert_management import _load_issued
        cfg = MockConfig(tempfile.mkdtemp())
        data = _load_issued(cfg)
        self.assertEqual(data["certs"], [])

    def test_save_and_load(self):
        from freq.modules.cert_management import _load_issued, _save_issued
        cfg = MockConfig(tempfile.mkdtemp())
        data = {"certs": [{"domain": "test.com", "type": "acme"}]}
        _save_issued(cfg, data)
        reloaded = _load_issued(cfg)
        self.assertEqual(len(reloaded["certs"]), 1)


class TestCertLifecyclePlan(unittest.TestCase):
    """Test TLS lifecycle planning without live mutation."""

    def test_plan_normalizes_dc01_target(self):
        from freq.modules.cert_management import _build_lifecycle_plan

        cfg = MockConfig(tempfile.mkdtemp())
        token_path = os.path.join(cfg.conf_dir, "cloudflare.token")
        with open(token_path, "w") as f:
            f.write("not-a-real-token")
        cfg.certificates = {
            "base_domain": "dc01.lowfreqlabs.com",
            "wildcard": True,
            "issuer": "acme.sh",
            "dns_provider": "cloudflare",
            "dns_token_path": token_path,
            "cloudflare_zone_id": "zone-id",
            "record_strategy": "public-private-a",
        }
        cfg.cert_targets = [
            {
                "label": "pve01",
                "target_type": "proxmox_ve_node",
                "hostname": "pve01.dc01.lowfreqlabs.com",
                "ip": "10.25.255.26",
                "port": 8006,
                "deploy_driver": "proxmox_pvenode",
                "restart_policy": "pveproxy_restart",
            }
        ]

        plan = _build_lifecycle_plan(cfg)

        self.assertEqual(plan["wildcard_name"], "*.dc01.lowfreqlabs.com")
        self.assertEqual(plan["targets"][0]["deploy_driver"], "proxmox_pvenode")
        self.assertIn("public-private-a publishes private IPs", " ".join(plan["warnings"]))

    def test_bootstrap_infers_default_targets_from_existing_config(self):
        from freq.modules.cert_management import _infer_cert_targets

        cfg = MockConfig(tempfile.mkdtemp())
        targets = _infer_cert_targets(cfg, "dc01.lowfreqlabs.com")

        self.assertEqual([t["label"] for t in targets[:3]], ["pve01", "pve02", "pve03"])
        self.assertIn("truenas", [t["label"] for t in targets])
        self.assertIn("pfsense", [t["label"] for t in targets])
        pfsense = next(t for t in targets if t["label"] == "pfsense")
        self.assertEqual(pfsense["deploy_driver"], "pfsense_config")
        self.assertTrue(pfsense["host_header_check"])
        self.assertTrue(pfsense["resolver_private_domain"])

    def test_adopt_existing_infers_proxy_routes_and_direct_management_targets(self):
        from freq.modules.cert_management import _infer_cert_targets

        cfg = MockConfig(tempfile.mkdtemp())
        cfg.certificates = {
            "base_domain": "dc01.lowfreqlabs.com",
            "management_mode": "adopted_existing",
            "record_strategy": "existing-dns",
            "reverse_proxy_host": "10.25.255.38",
            "renewal_owner": "external",
        }
        cfg.hosts = [
            MockHost("10.25.255.5", "switch", "switch"),
            MockHost(
                "10.25.255.10",
                "bmc-10",
                "idrac",
                hostname="idrac-truenas.dc01.lowfreqlabs.com",
                service_tag="B065ND2",
                identity_source="operator-curated",
            ),
            MockHost(
                "10.25.255.11",
                "bmc-11",
                "idrac",
                hostname="idrac-pve01.dc01.lowfreqlabs.com",
                service_tag="69MGVV1",
                identity_source="operator-curated",
            ),
            MockHost("10.25.255.1", "pfsense", "pfsense"),
        ]
        cfg.container_vms = {
            "media": SimpleNamespace(
                label="media",
                ip="10.25.255.30",
                containers={
                    "plex": SimpleNamespace(name="plex", port=32400),
                    "sonarr": SimpleNamespace(name="2e33fcf71920-sonarr", port=8989),
                    "radarr": SimpleNamespace(name="radarr", port=7878),
                    "prowlarr": SimpleNamespace(name="prowlarr", port=9696),
                    "bazarr": SimpleNamespace(name="bazarr", port=6767),
                    "overseerr": SimpleNamespace(name="overseerr", port=5055),
                    "tautulli": SimpleNamespace(name="tautulli", port=8181),
                    "huntarr": SimpleNamespace(name="huntarr", port=9705),
                    "tdarr": SimpleNamespace(name="tdarr", port=8265),
                    "tdarr-node": SimpleNamespace(name="tdarr-node", port=8266),
                    "sabnzbd": SimpleNamespace(name="sabnzbd", port=8080),
                },
            ),
            "qbit-01": SimpleNamespace(
                label="qbit-01",
                ip="10.25.255.31",
                containers={"qbittorrent": SimpleNamespace(name="qbittorrent", port=8080)},
            ),
            "qbit-02": SimpleNamespace(
                label="qbit-02",
                ip="10.25.255.32",
                containers={"qbittorrent": SimpleNamespace(name="qbittorrent", port=8080)},
            ),
        }

        targets = _infer_cert_targets(cfg, "dc01.lowfreqlabs.com")
        by_label = {t["label"]: t for t in targets}

        expected = {
            "pve-freq-dashboard",
            "plex",
            "sonarr",
            "radarr",
            "prowlarr",
            "bazarr",
            "overseerr",
            "tautulli",
            "huntarr",
            "tdarr",
            "qbit-01",
            "qbit-02",
            "sab",
            "pve01",
            "pve02",
            "pve03",
            "truenas",
            "pfsense",
            "switch",
            "idrac-truenas",
            "idrac-pve01",
        }
        self.assertEqual(set(by_label), expected)
        self.assertEqual(len(targets), 21)
        self.assertEqual(by_label["pve-freq-dashboard"]["deploy_driver"], "reverse_proxy")
        self.assertEqual(by_label["sonarr"]["hostname"], "sonarr.dc01.lowfreqlabs.com")
        self.assertEqual(by_label["sonarr"]["ip"], "10.25.255.38")
        self.assertEqual(by_label["sonarr"]["origin_port"], 8989)
        self.assertEqual(by_label["pfsense"]["port"], 4443)
        self.assertNotIn("bmc-10", by_label)
        self.assertNotIn("bmc-11", by_label)
        self.assertEqual(by_label["idrac-truenas"]["hostname"], "idrac-truenas.dc01.lowfreqlabs.com")
        self.assertEqual(by_label["idrac-pve01"]["hostname"], "idrac-pve01.dc01.lowfreqlabs.com")
        self.assertEqual(by_label["idrac-truenas"]["service_tag"], "B065ND2")
        self.assertEqual(by_label["idrac-pve01"]["service_tag"], "69MGVV1")
        self.assertEqual(by_label["idrac-truenas"]["identity_source"], "operator-curated")
        self.assertEqual(by_label["idrac-truenas"]["cert_source"], "wildcard_rsa")

    def test_bmc_cert_target_inference_never_synthesizes_ip_derived_labels(self):
        from freq.modules.cert_management import _infer_cert_targets

        cfg = MockConfig(tempfile.mkdtemp())
        cfg.hosts = [MockHost("10.25.255.12", "bmc-12", "idrac")]

        with patch("freq.modules.cert_management._snmp_device_identity", return_value={}):
            targets = _infer_cert_targets(cfg, "dc01.lowfreqlabs.com")
        labels = {t["label"] for t in targets}
        bmc_target = next(t for t in targets if t["ip"] == "10.25.255.12")

        self.assertNotIn("bmc-12", labels)
        self.assertEqual(bmc_target["label"], "10.25.255.12")
        self.assertEqual(bmc_target["hostname"], "")
        self.assertFalse(bmc_target["verify_hostname"])
        self.assertEqual(bmc_target["identity_source"], "unnamed_ip")

    def test_numeric_ptr_response_is_not_a_device_identity(self):
        from freq.modules.cert_management import _ptr_identity

        with patch("freq.modules.cert_management.socket.gethostbyaddr", return_value=("10.25.255.12", [], [])):
            self.assertEqual(_ptr_identity("10.25.255.12"), {})

    def test_bmc_cert_target_uses_snmp_identity_without_inventing_hostname(self):
        from freq.modules.cert_management import _infer_cert_targets

        cfg = MockConfig(tempfile.mkdtemp())
        cfg.hosts = [MockHost("10.25.255.10", "bmc-10", "idrac")]

        with patch(
            "freq.modules.cert_management._snmp_device_identity",
            return_value={
                "label": "idrac-b065nd2",
                "hostname": "",
                "service_tag": "B065ND2",
                "identity_source": "snmp",
            },
        ):
            targets = _infer_cert_targets(cfg, "dc01.lowfreqlabs.com")

        bmc_target = next(t for t in targets if t["ip"] == "10.25.255.10")
        self.assertEqual(bmc_target["label"], "idrac-b065nd2")
        self.assertEqual(bmc_target["hostname"], "")
        self.assertFalse(bmc_target["verify_hostname"])
        self.assertEqual(bmc_target["service_tag"], "B065ND2")
        self.assertEqual(bmc_target["identity_source"], "snmp")

    def test_service_catalog_expands_one_host_into_multiple_web_ui_targets(self):
        from freq.modules.cert_management import _build_lifecycle_plan, _cert_targets_from_catalog

        cfg = MockConfig(tempfile.mkdtemp())
        token_path = os.path.join(cfg.conf_dir, "cloudflare.token")
        with open(token_path, "w") as f:
            f.write("not-a-real-token")
        cfg.certificates = {
            "base_domain": "example.internal",
            "dns_provider": "cloudflare",
            "dns_token_path": token_path,
            "cloudflare_zone_id": "zone-id",
            "record_strategy": "public-private-a",
            "reverse_proxy_host": "proxy01",
        }
        cfg.cert_targets = _cert_targets_from_catalog(
            [
                {"name": "sonarr", "ip": "192.0.2.50", "port": 8989, "mode": "behind-proxy"},
                {"name": "radarr", "ip": "192.0.2.50", "port": 7878, "mode": "behind-proxy"},
                {"name": "router", "ip": "192.0.2.1", "port": 4443, "mode": "direct", "type": "pfsense"},
                {"name": "ignored", "ip": "192.0.2.99", "enabled": False},
            ],
            "example.internal",
            reverse_proxy_host="proxy01",
        )

        plan = _build_lifecycle_plan(cfg)
        targets = {t["label"]: t for t in plan["targets"]}

        self.assertEqual(len(targets), 3)
        self.assertEqual(targets["sonarr"]["hostname"], "sonarr.example.internal")
        self.assertEqual(targets["sonarr"]["deploy_driver"], "reverse_proxy")
        self.assertEqual(targets["sonarr"]["origin_ip"], "192.0.2.50")
        self.assertEqual(targets["sonarr"]["origin_port"], 8989)
        self.assertEqual(targets["radarr"]["origin_port"], 7878)
        self.assertEqual(targets["router"]["ip"], "192.0.2.1")

    def test_pfsense_plan_includes_rebind_and_unbound_actions(self):
        from freq.modules.cert_management import _build_lifecycle_plan

        cfg = MockConfig(tempfile.mkdtemp())
        token_path = os.path.join(cfg.conf_dir, "cloudflare.token")
        with open(token_path, "w") as f:
            f.write("not-a-real-token")
        cfg.certificates = {
            "base_domain": "dc01.lowfreqlabs.com",
            "dns_provider": "cloudflare",
            "dns_token_path": token_path,
            "cloudflare_zone_id": "zone-id",
            "record_strategy": "public-private-a",
        }
        cfg.cert_targets = [
            {
                "label": "pfsense",
                "target_type": "pfsense",
                "hostname": "pfsense.dc01.lowfreqlabs.com",
                "ip": "10.25.255.1",
                "port": 4443,
                "deploy_driver": "pfsense_config",
            }
        ]

        plan = _build_lifecycle_plan(cfg)
        actions = plan["targets"][0]["rebind_actions"]
        self.assertIn("webgui_althostname", [a["type"] for a in actions])
        self.assertIn("unbound_private_domain", [a["type"] for a in actions])
        deploy_command = " ".join(
            step.get("command", "") for step in plan["targets"][0]["deploy_steps"]
        )
        self.assertIn("althostnames", deploy_command)
        self.assertIn("private-domain", deploy_command)

    def test_bootstrap_dry_run_uses_single_cloudflare_token_file(self):
        from freq.modules.cert_management import cmd_cert_bootstrap

        cfg = MockConfig(tempfile.mkdtemp())
        token_path = os.path.join(cfg.conf_dir, "cf.token")
        with open(token_path, "w") as f:
            f.write("token-value")
        args = Namespace(
            base_domain="dc01.lowfreqlabs.com",
            cloudflare_token_file=token_path,
            token_dest="",
            replace=False,
            dry_run=True,
            json=True,
            yes=False,
        )

        with patch("freq.modules.cert_management._discover_cloudflare_zone_id") as discover:
            discover.return_value = {"zone_id": "zone-id", "zone_name": "lowfreqlabs.com", "errors": []}
            rc = cmd_cert_bootstrap(cfg, None, args)

        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(os.path.join(cfg.conf_dir, "freq.toml")))
        discover.assert_called_once_with(token_path, "dc01.lowfreqlabs.com")

    def test_issue_requires_bootstrap_config(self):
        from freq.modules.cert_management import cmd_cert_issue

        cfg = MockConfig(tempfile.mkdtemp())
        args = Namespace(dry_run=True, json=True)

        self.assertEqual(cmd_cert_issue(cfg, None, args), 1)

    def test_managed_ssl_uses_persistent_acme_and_install_paths(self):
        from freq.modules.cert_management import (
            _build_acme_install_command,
            _build_acme_issue_command,
            _cert_settings,
            _source_paths,
        )

        cfg = MockConfig(tempfile.mkdtemp())
        cfg.certificates = {
            "base_domain": "dc01.lowfreqlabs.com",
            "dns_provider": "cloudflare",
            "dns_token_path": "/run/secrets/cf-token",
        }

        settings = _cert_settings(cfg)
        source = _source_paths(settings)
        issue = _build_acme_issue_command(settings)
        install = _build_acme_install_command(settings)

        self.assertEqual(settings["acme_home"], os.path.join(cfg.data_dir, "acme"))
        self.assertTrue(source["fullchain"].startswith(cfg.data_dir))
        self.assertTrue(source["key"].startswith(cfg.data_dir))
        self.assertNotIn("--install-cert", issue)
        self.assertIn("--install-cert", install)
        self.assertIn("--fullchain-file", install)
        self.assertIn("--key-file", install)
        self.assertIn("--reloadcmd", install)
        self.assertIn("freq --yes cert deploy", install)

    def test_managed_ssl_reconcile_marks_supported_targets_renewal_hooked(self):
        from freq.modules.cert_management import _reconcile_lifecycle_targets

        cfg = MockConfig(tempfile.mkdtemp())
        cert_dir = os.path.join(cfg.data_dir, "certs", "managed", "dc01.lowfreqlabs.com")
        os.makedirs(cert_dir, exist_ok=True)
        fullchain = os.path.join(cert_dir, "fullchain.cer")
        key = os.path.join(cert_dir, "dc01.lowfreqlabs.com.key")
        Path(fullchain).write_text("not-a-real-cert")
        Path(key).write_text("not-a-real-key")
        cfg.certificates = {
            "base_domain": "dc01.lowfreqlabs.com",
            "management_mode": "managed",
            "dns_provider": "cloudflare",
            "dns_token_path": "/run/secrets/cf-token",
            "cert_fullchain_path": fullchain,
            "cert_key_path": key,
        }
        cfg.cert_targets = [
            {
                "label": "pve01",
                "target_type": "proxmox_ve_node",
                "hostname": "pve01.dc01.lowfreqlabs.com",
                "ip": "10.25.255.26",
                "port": 8006,
                "deploy_driver": "proxmox_pvenode",
            }
        ]
        with patch("freq.modules.cert_management._pem_cert_fingerprint", return_value="wire"), \
             patch("freq.modules.cert_management._verify_tls_target") as verify:
            verify.return_value = {
                "ok": True,
                "hostname": "pve01.dc01.lowfreqlabs.com",
                "issuer": "Let's Encrypt",
                "sans": ["*.dc01.lowfreqlabs.com"],
                "self_signed": False,
                "fingerprint_sha256": "wire",
            }
            result = _reconcile_lifecycle_targets(cfg)

        self.assertEqual(result["targets"][0]["classification"], "SERVING_MANAGED_WILDCARD")
        self.assertEqual(result["targets"][0]["renewal_status"], "hooked")
        self.assertTrue(result["targets"][0]["renewal_hooked"])
        self.assertFalse(result["targets"][0]["renewal_gap"])

    def test_adopted_existing_ssl_does_not_require_cloudflare_token(self):
        from freq.modules.cert_management import _build_lifecycle_plan

        cfg = MockConfig(tempfile.mkdtemp())
        cfg.certificates = {
            "base_domain": "dc01.lowfreqlabs.com",
            "management_mode": "adopted_existing",
            "issuer": "existing",
            "record_strategy": "existing-dns",
            "reverse_proxy_host": "dc01-proxy",
            "renewal_owner": "external",
        }
        cfg.cert_targets = [
            {
                "label": "pve01",
                "target_type": "proxmox_ve_node",
                "hostname": "pve01.dc01.lowfreqlabs.com",
                "ip": "10.25.255.26",
                "port": 8006,
                "deploy_driver": "proxmox_pvenode",
            }
        ]

        plan = _build_lifecycle_plan(cfg)
        warnings = " ".join(plan["warnings"])

        self.assertEqual(plan["settings"]["management_mode"], "adopted_existing")
        self.assertNotIn("dns_provider", warnings)
        self.assertNotIn("dns_token_path", warnings)
        self.assertNotIn("cloudflare_zone_id", warnings)
        self.assertNotIn("public-private-a publishes private IPs", warnings)
        self.assertEqual(plan["source_paths"]["source_mode"], "external_existing")
        self.assertNotIn(".acme.sh", warnings)
        self.assertEqual(plan["targets"][0]["deploy_steps"][0]["kind"], "adopt_existing")

    def test_served_cert_classifier_uses_sni_san_and_fingerprint(self):
        from freq.modules.cert_management import _classify_tls_probe

        settings = {"base_domain": "dc01.lowfreqlabs.com"}
        target = {"hostname": "pve01.dc01.lowfreqlabs.com"}
        probe = {
            "ok": True,
            "hostname": "pve01.dc01.lowfreqlabs.com",
            "issuer": "Let's Encrypt",
            "sans": ["*.dc01.lowfreqlabs.com"],
            "fingerprint_sha256": "abc",
            "self_signed": False,
        }

        self.assertEqual(
            _classify_tls_probe(settings, target, probe, managed_fingerprint="abc"),
            "SERVING_MANAGED_WILDCARD",
        )
        probe["fingerprint_sha256"] = "other"
        self.assertEqual(
            _classify_tls_probe(settings, target, probe, managed_fingerprint="abc"),
            "SERVING_MANAGED_WILDCARD",
        )
        probe["issuer"] = "Self Signed"
        probe["self_signed"] = True
        self.assertEqual(
            _classify_tls_probe(settings, target, probe, managed_fingerprint="abc"),
            "SELF_SIGNED_OR_OTHER",
        )
        probe["issuer"] = "YE1"
        probe["self_signed"] = False
        self.assertEqual(
            _classify_tls_probe(settings, target, probe, managed_fingerprint="abc"),
            "SERVING_MANAGED_WILDCARD",
        )
        self.assertEqual(
            _classify_tls_probe(settings, target, {"ok": False}, managed_fingerprint="abc"),
            "UNREACHABLE",
        )

    def test_adopted_existing_external_owner_is_not_counted_as_renewal_gap(self):
        from freq.modules.cert_management import _reconcile_lifecycle_targets

        cfg = MockConfig(tempfile.mkdtemp())
        cfg.certificates = {
            "base_domain": "dc01.lowfreqlabs.com",
            "management_mode": "adopted_existing",
            "issuer": "existing",
            "record_strategy": "existing-dns",
            "renewal_owner": "external",
        }
        cfg.cert_targets = [
            {
                "label": "pve01",
                "target_type": "proxmox_ve_node",
                "hostname": "pve01.dc01.lowfreqlabs.com",
                "ip": "10.25.255.26",
                "port": 8006,
                "deploy_driver": "proxmox_pvenode",
            }
        ]
        with patch("freq.modules.cert_management._verify_tls_target") as verify:
            verify.return_value = {
                "ok": True,
                "hostname": "pve01.dc01.lowfreqlabs.com",
                "issuer": "Let's Encrypt",
                "sans": ["*.dc01.lowfreqlabs.com"],
                "self_signed": False,
                "fingerprint_sha256": "wire",
            }
            result = _reconcile_lifecycle_targets(cfg)

        self.assertEqual(result["targets"][0]["classification"], "SERVING_MANAGED_WILDCARD")
        self.assertEqual(result["targets"][0]["renewal_status"], "external_owner")
        self.assertFalse(result["targets"][0]["renewal_gap"])
        self.assertEqual(result["summary"]["renewal_gaps"], 0)
        self.assertEqual(result["summary"]["external_renewal"], result["summary"]["total"])

    def test_adopted_existing_synthesizes_issued_and_inventory_from_probe_truth(self):
        from freq.modules.cert_management import _cert_inventory_from_reconcile, _issued_from_reconcile

        cfg = MockConfig(tempfile.mkdtemp())
        cfg.certificates = {
            "base_domain": "dc01.lowfreqlabs.com",
            "management_mode": "adopted_existing",
            "issuer": "existing",
            "record_strategy": "existing-dns",
            "renewal_owner": "external",
        }
        reconcile = {
            "generated_at": "2026-06-26T18:00:00-0500",
            "source_paths": {"source_mode": "external_existing"},
            "summary": {"total": 1, "serving_managed": 1, "pending": 0, "unreachable": 0},
            "targets": [
                {
                    "ok": True,
                    "label": "pve01",
                    "hostname": "pve01.dc01.lowfreqlabs.com",
                    "issuer": "Let's Encrypt",
                    "expires": "Sep 18 00:39:31 2026 GMT",
                    "classification": "SERVING_MANAGED_WILDCARD",
                    "sans": ["*.dc01.lowfreqlabs.com"],
                    "renewal_status": "external_owner",
                }
            ],
        }

        inventory = _cert_inventory_from_reconcile(cfg, {"certs": []}, reconcile=reconcile)
        issued = _issued_from_reconcile(cfg, {"certs": []}, reconcile=reconcile, inventory=inventory)

        self.assertEqual(inventory["source"], "reconcile_probe")
        self.assertEqual(len(inventory["certs"]), 1)
        self.assertEqual(inventory["certs"][0]["source"], "external_existing")
        self.assertEqual(issued["issued_at"], "external existing")
        self.assertEqual(issued["certs"][0]["status"], "externally managed")
        self.assertEqual(issued["certs"][0]["domain"], "*.dc01.lowfreqlabs.com")

    def test_dns_sync_upserts_cloudflare_records(self):
        from freq.modules.cert_management import cmd_cert_dns_sync

        cfg = MockConfig(tempfile.mkdtemp())
        token_path = os.path.join(cfg.conf_dir, "cf.token")
        with open(token_path, "w") as f:
            f.write("token-value")
        cfg.certificates = {
            "base_domain": "dc01.lowfreqlabs.com",
            "dns_provider": "cloudflare",
            "dns_token_path": token_path,
            "cloudflare_zone_id": "zone-id",
            "record_strategy": "public-private-a",
        }
        cfg.cert_targets = [
            {
                "label": "pve01",
                "target_type": "proxmox_ve_node",
                "hostname": "pve01.dc01.lowfreqlabs.com",
                "ip": "10.25.255.26",
                "port": 8006,
                "deploy_driver": "proxmox_pvenode",
            }
        ]
        args = Namespace(dry_run=False, json=True, yes=True)

        with patch("freq.modules.cert_management._cloudflare_upsert_dns_record") as upsert:
            upsert.return_value = {
                "action": "updated",
                "hostname": "pve01.dc01.lowfreqlabs.com",
                "value": "10.25.255.26",
            }
            rc = cmd_cert_dns_sync(cfg, None, args)

        self.assertEqual(rc, 0)
        upsert.assert_called_once()


# ---------------------------------------------------------------------------
# Proxy Tests
# ---------------------------------------------------------------------------

class TestProxyImports(unittest.TestCase):
    """Test proxy management module imports."""

    def test_all_commands(self):
        from freq.modules.proxy_management import (
            cmd_proxy_status, cmd_proxy_hosts, cmd_proxy_health,
        )
        self.assertTrue(callable(cmd_proxy_status))


# ---------------------------------------------------------------------------
# CLI Registration Tests
# ---------------------------------------------------------------------------

class TestPhase2CLIRegistration(unittest.TestCase):
    """Test that all Phase 2 commands are registered."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _parse(self, args_str):
        return self.parser.parse_args(args_str.split())

    # Firewall
    def test_fw_status(self):
        args = self._parse("fw status")
        self.assertTrue(hasattr(args, "func"))

    def test_fw_rules(self):
        args = self._parse("fw rules")
        self.assertTrue(hasattr(args, "func"))

    def test_fw_rules_audit(self):
        args = self._parse("fw rules audit")
        self.assertEqual(args.action, "audit")

    def test_fw_nat(self):
        args = self._parse("fw nat")
        self.assertTrue(hasattr(args, "func"))

    def test_fw_states(self):
        args = self._parse("fw states")
        self.assertTrue(hasattr(args, "func"))

    def test_fw_dhcp(self):
        args = self._parse("fw dhcp")
        self.assertTrue(hasattr(args, "func"))

    def test_fw_interfaces(self):
        args = self._parse("fw interfaces")
        self.assertTrue(hasattr(args, "func"))

    def test_fw_gateways(self):
        args = self._parse("fw gateways")
        self.assertTrue(hasattr(args, "func"))

    # DNS
    def test_dns_scan(self):
        args = self._parse("dns scan")
        self.assertTrue(hasattr(args, "func"))

    def test_dns_internal_list(self):
        args = self._parse("dns internal list")
        self.assertTrue(hasattr(args, "func"))

    def test_dns_internal_add(self):
        args = self._parse("dns internal add test.local 10.0.0.1")
        self.assertEqual(args.hostname, "test.local")
        self.assertEqual(args.ip, "10.0.0.1")

    def test_dns_internal_sync(self):
        args = self._parse("dns internal sync")
        self.assertTrue(hasattr(args, "func"))

    # VPN
    def test_vpn_domain_registered(self):
        import argparse
        registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertIn("vpn", registered)

    def test_vpn_wg_status(self):
        args = self._parse("vpn wg status")
        self.assertTrue(hasattr(args, "func"))

    def test_vpn_wg_peers(self):
        args = self._parse("vpn wg peers")
        self.assertTrue(hasattr(args, "func"))

    def test_vpn_wg_audit(self):
        args = self._parse("vpn wg audit")
        self.assertTrue(hasattr(args, "func"))

    def test_vpn_ovpn_status(self):
        args = self._parse("vpn ovpn status")
        self.assertTrue(hasattr(args, "func"))

    # Cert
    def test_cert_inspect(self):
        args = self._parse("cert inspect google.com:443")
        self.assertEqual(args.target, "google.com:443")

    def test_cert_fleet_check(self):
        args = self._parse("cert fleet-check")
        self.assertTrue(hasattr(args, "func"))

    def test_cert_acme(self):
        args = self._parse("cert acme")
        self.assertTrue(hasattr(args, "func"))

    def test_cert_issued(self):
        args = self._parse("cert issued")
        self.assertTrue(hasattr(args, "func"))

    def test_cert_plan(self):
        args = self._parse("cert plan --json")
        self.assertTrue(hasattr(args, "func"))
        self.assertTrue(args.json)

    def test_cert_bootstrap(self):
        args = self._parse("cert bootstrap --base-domain dc01.lowfreqlabs.com --cloudflare-token-file /tmp/cf --dry-run")
        self.assertEqual(args.base_domain, "dc01.lowfreqlabs.com")
        self.assertEqual(args.cloudflare_token_file, "/tmp/cf")
        self.assertTrue(args.dry_run)

    def test_cert_issue(self):
        args = self._parse("cert issue --dry-run")
        self.assertTrue(hasattr(args, "func"))
        self.assertTrue(args.dry_run)

    def test_cert_renew(self):
        args = self._parse("cert renew --deploy --dry-run")
        self.assertTrue(hasattr(args, "func"))
        self.assertTrue(args.deploy)

    def test_cert_deploy(self):
        args = self._parse("cert deploy pve01 --dry-run --json")
        self.assertEqual(args.target, "pve01")
        self.assertTrue(args.dry_run)
        self.assertTrue(args.json)

    def test_cert_dns_sync(self):
        args = self._parse("cert dns-sync --dry-run --json")
        self.assertTrue(hasattr(args, "func"))
        self.assertTrue(args.dry_run)
        self.assertTrue(args.json)

    def test_cert_verify(self):
        args = self._parse("cert verify pfsense --json")
        self.assertEqual(args.target, "pfsense")
        self.assertTrue(args.json)

    # Proxy
    def test_proxy_status(self):
        args = self._parse("proxy status")
        self.assertTrue(hasattr(args, "func"))

    def test_proxy_hosts(self):
        args = self._parse("proxy hosts")
        self.assertTrue(hasattr(args, "func"))

    def test_proxy_health(self):
        args = self._parse("proxy health")
        self.assertTrue(hasattr(args, "func"))


if __name__ == "__main__":
    unittest.main()
