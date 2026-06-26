"""SSL lifecycle onboarding product contract.

The SSL Manager must be a product surface, not a DC01-specific TOML helper.
Operators can adopt existing SSL, provision direct target certs, use an
existing reverse proxy, or create a managed reverse-proxy VM from templates.
"""

from types import SimpleNamespace
import tempfile

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
    assert "dns_provider_and_token_path_when_provisioning" in contract["ask_user"]


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


def test_cert_lifecycle_registers_onboarding_endpoint():
    routes = {}
    cert_lifecycle.register(routes)

    assert "/api/cert/lifecycle/onboarding" in routes


def test_cert_lifecycle_registers_trusted_proxy_endpoint():
    routes = {}
    cert_lifecycle.register(routes)

    assert "/api/cert/lifecycle/trusted-proxy" in routes


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
