"""SSL lifecycle onboarding product contract.

The SSL Manager must be a product surface, not a DC01-specific TOML helper.
Operators can adopt existing SSL, provision direct target certs, use an
existing reverse proxy, or create a managed reverse-proxy VM from templates.
"""

from types import SimpleNamespace
import io
import json
import os
import tempfile
from unittest.mock import patch

from freq.api import cert_lifecycle
from freq.modules.cert_management import _ssl_onboarding_contract


def _cfg(**overrides):
    base = {
        "certificates": {},
        "cert_targets": [],
        "dashboard_port": 8888,
        "vm_cpu": "x86-64-v2-AES",
        "vm_machine": "q35",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_ssl_onboarding_never_requires_manual_toml_editing():
    contract = _ssl_onboarding_contract(_cfg())

    assert contract["manual_toml_edit_required"] is False
    assert contract["truth_source"] == "per_target_sni_tls_probe"
    assert "reverse_proxy_config_as_hint_only" in contract["auto_detect"]
    assert "reverse_proxy_exists" in contract["never_assume"]


def test_ssl_onboarding_exposes_managed_reverse_proxy_vm_path():
    contract = _ssl_onboarding_contract(_cfg())
    paths = {item["id"]: item for item in contract["paths"]}

    proxy_vm = paths["create_managed_reverse_proxy_vm"]
    assert proxy_vm["mutates_on_preview"] is False
    assert proxy_vm["vm_defaults"]["source"] == "pve_template"
    assert proxy_vm["vm_defaults"]["template_selection"] == "operator_selected"
    assert proxy_vm["vm_defaults"]["cpu"] == "x86-64-v2-AES"
    assert proxy_vm["vm_defaults"]["machine"] == "q35"
    assert proxy_vm["vm_defaults"]["migration_safe"] is True
    assert "template_vmid" in proxy_vm["requires"]
    assert "network_profile" in proxy_vm["requires"]
    assert "create_vm" in proxy_vm["apply_mutations"]


def test_ssl_onboarding_provider_is_pluggable_with_cloudflare_first_class():
    contract = _ssl_onboarding_contract(_cfg())
    providers = {provider["id"]: provider for provider in contract["dns_providers"]}

    assert "cloudflare" in providers
    assert providers["cloudflare"]["status"] == "first_class"
    assert providers["cloudflare"]["credential_mode"] == "token_path"
    assert providers["cloudflare"]["inline_secret_allowed"] is False
    assert contract["credential_policy"]["browser_secret_intake_allowed"] is True
    assert contract["credential_policy"]["store_endpoint"] == "/api/cert/lifecycle/cloudflare-token"
    assert contract["credential_policy"]["secret_response_policy"] == "never_echo_secret_value"
    assert "dns_provider_and_token_path_when_provisioning" in contract["ask_user"]
    assert "dns_provider_token_paste_or_path_when_provisioning" in contract["ask_user"]


def test_ssl_onboarding_adopt_existing_is_base_domain_wide_not_per_target():
    contract = _ssl_onboarding_contract(_cfg())
    detection = contract["current_detection"]

    assert detection["adopt_existing_scope"]["mode"] == "wildcard_base_domain"
    assert detection["adopt_existing_scope"]["single_apply_registers_all_inferred_targets"] is True
    assert detection["adopt_existing_scope"]["infer_targets_default"] is True
    assert "reverse_proxy_upstream_scheme" in detection
    assert "reverse_proxy_upstream_tls_verify" in detection
    assert "reverse_proxy_upstream_protocol_when_adopting_existing_proxy" in contract["ask_user"]


def test_ssl_onboarding_dashboard_https_gap_is_explicit():
    contract = _ssl_onboarding_contract(_cfg())

    assert contract["dashboard_https"]["state"] == "gap"
    assert "create_managed_reverse_proxy_vm" in contract["dashboard_https"]["recommended_actions"]
    assert contract["trusted_proxy"]["configured"] is False
    assert contract["trusted_proxy"]["configure_endpoint"] == "/api/cert/lifecycle/trusted-proxy"


def test_ssl_onboarding_detects_dashboard_cert_target_as_managed():
    contract = _ssl_onboarding_contract(
        _cfg(
            cert_targets=[
                {
                    "label": "freq",
                    "target_type": "freq_dashboard",
                    "hostname": "freq.example.com",
                    "ip": "10.0.0.50",
                    "port": 443,
                    "deploy_driver": "reverse_proxy",
                }
            ]
        )
    )

    assert contract["dashboard_https"]["state"] == "managed"
    assert contract["dashboard_https"]["managed_targets"][0]["hostname"] == "freq.example.com"


def test_ssl_onboarding_detects_existing_proxy_dashboard_https():
    with patch("freq.modules.cert_management._verify_tls_target") as verify:
        verify.return_value = {
            "ok": True,
            "hostname": "pve-freq.dc01.lowfreqlabs.com",
            "issuer": "Let's Encrypt",
            "sans": ["*.dc01.lowfreqlabs.com", "dc01.lowfreqlabs.com"],
            "expires": "Sep 18 00:39:31 2026 GMT",
        }
        contract = _ssl_onboarding_contract(
            _cfg(
                certificates={
                    "base_domain": "dc01.lowfreqlabs.com",
                    "management_mode": "adopted_existing",
                    "reverse_proxy_host": "10.25.255.38",
                }
            )
        )

    assert contract["dashboard_https"]["state"] == "managed"
    assert contract["dashboard_https"]["managed_targets"][0]["hostname"] == "pve-freq.dc01.lowfreqlabs.com"
    assert contract["dashboard_https"]["probes"][0]["issuer"] == "Let's Encrypt"


def test_adopt_existing_records_reverse_proxy_upstream_contract():
    from freq.modules.cert_management import _cert_targets_from_catalog, _render_cert_config_block

    settings = {
        "base_domain": "dc01.lowfreqlabs.com",
        "management_mode": "adopted_existing",
        "issuer": "existing",
        "record_strategy": "existing-dns",
        "reverse_proxy_host": "10.25.255.38",
        "reverse_proxy_upstream_scheme": "https",
        "reverse_proxy_upstream_tls_verify": False,
        "dashboard_origin_host": "10.25.255.50",
        "dashboard_origin_port": 8888,
        "renewal_owner": "external",
    }
    targets = _cert_targets_from_catalog(
        [
            {
                "name": "pve-freq",
                "hostname": "pve-freq.dc01.lowfreqlabs.com",
                "mode": "behind-proxy",
                "origin_ip": "10.25.255.50",
                "origin_port": 8888,
                "origin_scheme": "https",
                "origin_tls_verify": False,
            }
        ],
        "dc01.lowfreqlabs.com",
        reverse_proxy_host="10.25.255.38",
    )
    block = _render_cert_config_block(settings, targets)

    assert targets[0]["origin_scheme"] == "https"
    assert targets[0]["origin_tls_verify"] is False
    assert 'reverse_proxy_upstream_scheme = "https"' in block
    assert "reverse_proxy_upstream_tls_verify = false" in block
    assert 'dashboard_origin_host = "10.25.255.50"' in block
    assert "dashboard_origin_port = 8888" in block
    assert 'origin_scheme = "https"' in block
    assert "origin_tls_verify = false" in block


def test_inferred_dashboard_target_uses_submitted_proxy_upstream_truth():
    from freq.modules.cert_management import _infer_cert_targets

    cfg = _cfg(
        certificates={
            "base_domain": "dc01.lowfreqlabs.com",
            "management_mode": "adopted_existing",
            "reverse_proxy_host": "10.25.255.38",
            "reverse_proxy_upstream_scheme": "https",
            "reverse_proxy_upstream_tls_verify": False,
            "dashboard_origin_host": "10.25.255.50",
            "dashboard_origin_port": 8888,
        }
    )
    target = next(t for t in _infer_cert_targets(cfg, "dc01.lowfreqlabs.com") if t["label"] == "pve-freq-dashboard")

    assert target["hostname"] == "pve-freq.dc01.lowfreqlabs.com"
    assert target["ip"] == "10.25.255.38"
    assert target["origin_ip"] == "10.25.255.50"
    assert target["origin_port"] == 8888
    assert target["origin_scheme"] == "https"
    assert target["origin_tls_verify"] is False


def test_cert_lifecycle_registers_onboarding_endpoint():
    routes = {}
    cert_lifecycle.register(routes)

    assert "/api/cert/lifecycle/onboarding" in routes


def test_cert_lifecycle_registers_trusted_proxy_endpoint():
    routes = {}
    cert_lifecycle.register(routes)

    assert "/api/cert/lifecycle/trusted-proxy" in routes


def test_cert_lifecycle_registers_cloudflare_token_endpoint():
    routes = {}
    cert_lifecycle.register(routes)

    assert "/api/cert/lifecycle/cloudflare-token" in routes


def test_cloudflare_token_value_is_staged_without_value_exposure():
    from freq.modules.cert_management import _cloudflare_token_status, _stage_cloudflare_token_value

    with tempfile.TemporaryDirectory() as td:
        cfg = _cfg(conf_dir=td)
        path = _stage_cloudflare_token_value(cfg, "cf-token-value-1234567890", os.path.join(td, "secrets", "cf"))
        status = _cloudflare_token_status(cfg, {"dns_provider": "cloudflare", "dns_token_path": path})

        with open(path) as f:
            stored = f.read().strip()

    assert stored == "cf-token-value-1234567890"
    assert status["ready"] is True
    assert status["stored"] is True
    assert status["mode"] == "0o600"
    assert status["secret_ref"] == "cloudflare_dns_token"
    assert status["value_exposed"] is False
    assert "cf-token" not in json.dumps(status)


def test_cloudflare_token_handler_never_echoes_pasted_secret():
    secret = "cf-secret-token-value-1234567890"
    body = json.dumps(
        {
            "cloudflare_token": secret,
            "base_domain": "dc01.lowfreqlabs.com",
            "dry_run": False,
            "confirm": True,
        }
    ).encode()

    class Handler:
        command = "POST"
        headers = {"Content-Length": str(len(body))}
        rfile = io.BytesIO(body)
        wfile = io.BytesIO()
        _headers_buffer = []
        _request_id = "test"

        def send_response(self, code, msg=None):
            self.status = code

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

    with tempfile.TemporaryDirectory() as td:
        cfg = _cfg(conf_dir=td, certificates={}, cert_targets=[])
        with patch.object(cert_lifecycle, "_check_session_role", return_value=("admin", "")):
            with patch.object(cert_lifecycle, "load_config", return_value=cfg):
                with patch.object(
                    cert_lifecycle,
                    "_discover_cloudflare_zone_id_for_token",
                    return_value={"zone_id": "zone-id", "zone_name": "lowfreqlabs.com", "errors": []},
                ):
                    h = Handler()
                    cert_lifecycle.handle_cert_cloudflare_token(h)

        payload = h.wfile.getvalue().decode()

    assert h.status == 200
    assert secret not in payload
    data = json.loads(payload)
    assert data["ok"] is True
    assert data["stored"] is True
    assert data["token_status"]["value_exposed"] is False
    assert data["token_status"]["ready"] is True


def test_trusted_proxy_writer_updates_dashboard_section_without_toml_editing():
    with tempfile.TemporaryDirectory() as td:
        cfg = _cfg(conf_dir=td)
        path = cert_lifecycle._write_dashboard_trusted_proxy_cidrs(
            cfg,
            cert_lifecycle._normalize_cidrs(["10.25.255.38/32"]),
        )

        with open(path) as f:
            text = f.read()

    assert "[dashboard]" in text
    assert 'trusted_proxy_cidrs = ["10.25.255.38/32"]' in text


def test_trusted_proxy_writer_replaces_existing_dashboard_key_only_once():
    with tempfile.TemporaryDirectory() as td:
        cfg = _cfg(conf_dir=td)
        with open(f"{td}/freq.toml", "w") as f:
            f.write('[services]\ndashboard_port = 8888\n\n[dashboard]\ntrusted_proxy_cidrs = ["10.0.0.1/32"]\n')

        cert_lifecycle._write_dashboard_trusted_proxy_cidrs(
            cfg,
            cert_lifecycle._normalize_cidrs(["10.25.255.38/32", "10.25.255.38"]),
        )
        with open(f"{td}/freq.toml") as f:
            text = f.read()

    assert text.count("trusted_proxy_cidrs") == 1
    assert 'trusted_proxy_cidrs = ["10.25.255.38/32"]' in text


def test_trusted_proxy_cidr_validation_rejects_bad_values():
    try:
        cert_lifecycle._normalize_cidrs(["not-a-cidr"])
    except ValueError as exc:
        assert "invalid trusted proxy CIDR" in str(exc)
    else:
        raise AssertionError("invalid CIDR was accepted")
