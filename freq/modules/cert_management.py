"""Certificate lifecycle management for FREQ — ACME, CA, fleet deployment.

Domain: freq cert <acme|ca|inspect|deploy> <action>
What: Issue certificates via ACME (Let's Encrypt), manage private CA,
      inspect certs on endpoints, deploy certs to fleet hosts.
      Extends existing cert.py scan/list/check with write operations.
Replaces: Manual certbot runs, step-ca CLI, SCP cert files, cert tracking
Architecture:
    - ACME: shells to acme.sh for issuance, parses output
    - CA: shells to step-ca for private CA operations
    - Deploy: SCP via ssh.py to push certs to target hosts
    - Inventory: extends conf/certs/ with issued cert tracking
Design decisions:
    - Shell to certbot/step-ca, not implement ACME protocol. Zero deps.
    - Track issued certs in JSON for renewal/expiry monitoring.
    - Deploy is SCP + service reload via SSH — works everywhere.
"""

import hashlib
import ipaddress
import json
import os
import shlex
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.request

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig

# ---------------------------------------------------------------------------
# Data Storage
# ---------------------------------------------------------------------------

CERT_DIR = "certs"

DEFAULT_CERT_SETTINGS = {
    "base_domain": "",
    "wildcard": True,
    "management_mode": "managed",
    "issuer": "acme.sh",
    "acme_home": "",
    "acme_binary": "",
    "acme_auto_install": True,
    "acme_install_url": "https://get.acme.sh",
    "acme_keylength": "ec-256",
    "cert_fullchain_path": "",
    "cert_key_path": "",
    "dns_provider": "",
    "dns_token_path": "",
    "cloudflare_zone_id": "",
    "record_strategy": "public-private-a",
    "reverse_proxy_host": "",
    "reverse_proxy_upstream_scheme": "http",
    "reverse_proxy_upstream_tls_verify": True,
    "dashboard_hostname": "",
    "dashboard_origin_host": "",
    "dashboard_origin_port": 8888,
    "renewal_owner": "",
}

SSL_ONBOARDING_DNS_PROVIDERS = [
    {
        "id": "cloudflare",
        "label": "Cloudflare",
        "status": "first_class",
        "credential_mode": "token_path",
        "required_fields": ["api_token_path"],
        "optional_fields": ["zone_id"],
        "inline_secret_allowed": False,
    }
]

SSL_PROXY_VM_DEFAULTS = {
    "engine": "caddy",
    "source": "pve_template",
    "template_selection": "operator_selected",
    "cores": 2,
    "memory_mb": 2048,
    "disk_gb": 16,
    "cpu": "x86-64-v2-AES",
    "machine": "q35",
    "onboot": True,
    "migration_safe": True,
}

DRIVER_CAPABILITIES = {
    "proxmox_pvenode": {
        "mutates": ["pveproxy certificate"],
        "reload": "pveproxy restart only; guests unaffected",
        "verify": "TLS handshake with SNI hostname",
    },
    "truenas_api": {
        "mutates": ["TrueNAS UI certificate"],
        "reload": "web UI/nginx reload only; pools/NFS unaffected",
        "verify": "TLS handshake with SNI hostname",
    },
    "pfsense_config": {
        "mutates": ["pfSense webGUI certificate", "webGUI alternate hostnames", "Unbound private-domain allowlist"],
        "reload": "webGUI restart and Unbound restart; routing/firewall state untouched",
        "verify": "TLS handshake plus Host-header login-page probe",
    },
    "reverse_proxy": {
        "mutates": ["reverse proxy route/certificate binding"],
        "reload": "proxy reload only; application guests unaffected",
        "verify": "TLS handshake with SNI hostname",
    },
}


def _ssl_dashboard_status(cfg, settings, targets):
    """Return the product's own dashboard HTTPS onboarding state."""
    dashboard_port = int(getattr(cfg, "dashboard_port", 8888) or 8888)
    dashboard_targets = []
    for target in targets:
        service_name = str(target.get("service_name") or target.get("label") or "").lower()
        target_type = str(target.get("target_type") or "").lower()
        if service_name in ("freq", "pve-freq", "dashboard") or target_type in (
            "freq_dashboard",
            "pve_freq_dashboard",
            "dashboard",
        ):
            dashboard_targets.append(target)
    if dashboard_targets:
        state = "managed"
        message = "Dashboard HTTPS is covered by a configured cert target."
        probes = []
    else:
        state = "gap"
        message = "Dashboard HTTPS is not covered yet; choose direct certs or a reverse-proxy route."
        probes = []
        base_domain = str(settings.get("base_domain") or "").strip().lower()
        reverse_proxy_host = str(settings.get("reverse_proxy_host") or "").strip()
        candidate = str(settings.get("dashboard_hostname") or "").strip().lower()
        if not candidate and base_domain:
            candidate = f"pve-freq.{base_domain}"
        if candidate and reverse_proxy_host:
            probe_target = {
                "label": "pve-freq-dashboard",
                "service_name": "pve-freq",
                "target_type": "freq_dashboard",
                "hostname": candidate,
                "ip": reverse_proxy_host,
                "port": 443,
                "deploy_driver": "reverse_proxy",
            }
            probe = _verify_tls_target(probe_target)
            probes.append(probe)
            if probe.get("ok"):
                state = "managed"
                message = "Dashboard HTTPS is served by the configured reverse proxy."
                dashboard_targets = [probe_target]
    return {
        "state": state,
        "plain_http_port": dashboard_port,
        "managed_targets": dashboard_targets,
        "probes": probes,
        "message": message,
        "recommended_actions": [
            "adopt_existing_route",
            "add_dashboard_to_existing_proxy",
            "create_managed_reverse_proxy_vm",
            "serve_dashboard_tls_directly",
        ],
    }


def _ssl_onboarding_contract(cfg):
    """Provider-agnostic SSL Manager contract for UI and setup surfaces.

    This is deliberately product-shaped instead of DC01-shaped. The UI should
    render choices from this contract and never ask operators to edit TOML.
    """
    settings = _cert_settings(cfg)
    targets = _cert_targets(cfg)
    provider_ids = {p["id"] for p in SSL_ONBOARDING_DNS_PROVIDERS}
    detected_provider = settings.get("dns_provider") if settings.get("dns_provider") in provider_ids else ""
    base_domain = settings.get("base_domain", "")
    existing_acme_hint = bool(base_domain and _acme_available(settings))
    proxy_vm_defaults = dict(SSL_PROXY_VM_DEFAULTS)
    proxy_vm_defaults["cpu"] = getattr(cfg, "vm_cpu", proxy_vm_defaults["cpu"]) or proxy_vm_defaults["cpu"]
    proxy_vm_defaults["machine"] = getattr(cfg, "vm_machine", proxy_vm_defaults["machine"]) or proxy_vm_defaults["machine"]

    return {
        "schema_version": 1,
        "manual_toml_edit_required": False,
        "truth_source": "per_target_sni_tls_probe",
        "credential_policy": {
            "inline_secret_allowed": False,
            "browser_secret_intake_allowed": True,
            "secret_inputs": "path_or_secret_store_reference",
            "store_endpoint": "/api/cert/lifecycle/cloudflare-token",
            "secret_response_policy": "never_echo_secret_value",
        },
        "auto_detect": [
            "dns_provider_credentials_by_path_or_env",
            "existing_acme_store_acmesh_or_certbot",
            "reverse_proxy_config_as_hint_only",
            "per_target_served_certificate_via_sni",
        ],
        "ask_user": [
            "base_domain_when_not_detected_or_ambiguous",
            "dns_provider_and_token_path_when_provisioning",
            "dns_provider_token_paste_or_path_when_provisioning",
            "wildcard_or_explicit_san_set",
            "deploy_model",
            "targets_to_cover",
            "reverse_proxy_vm_template_node_storage_network_when_creating_proxy",
            "reverse_proxy_upstream_protocol_when_adopting_existing_proxy",
            "reverse_proxy_upstream_tls_verification_when_upstream_is_https",
        ],
        "never_assume": [
            "reverse_proxy_exists",
            "one_proxy_fronts_everything",
            "proxy_product_or_config_format",
            "proxy_terminates_tls",
            "management_uis_are_proxied",
            "dashboard_is_already_https",
        ],
        "unsafe_mutations_require_apply": [
            "dns_record_write",
            "certificate_issue_or_reissue",
            "reverse_proxy_create_or_reconfigure",
            "target_service_reload_or_restart",
            "firewall_or_nat_change",
        ],
        "paths": [
            {
                "id": "adopt_existing",
                "label": "Adopt existing SSL",
                "intent": "Register and verify SSL that already works without reissuing certificates.",
                "auto_detect": [
                    "acme_store",
                    "certbot_store",
                    "dns_provider_credentials",
                    "reverse_proxy_hints",
                    "served_certificates",
                ],
                "requires": ["base_domain"],
                "mutates_on_preview": False,
                "apply_mutations": ["register_targets", "record_renewal_owner"],
            },
            {
                "id": "provision_direct",
                "label": "Provision direct target certs",
                "intent": "Issue wildcard/SAN certs and deploy them directly to selected targets.",
                "requires": ["dns_provider", "api_token_path", "base_domain", "target_selection"],
                "secret_store_endpoint": "/api/cert/lifecycle/cloudflare-token",
                "mutates_on_preview": False,
                "apply_mutations": ["issue_cert", "deploy_to_targets", "reload_selected_services"],
            },
            {
                "id": "use_existing_reverse_proxy",
                "label": "Use existing reverse proxy",
                "intent": "Use a proxy the operator already runs; probe it as a hint, then verify served TLS.",
                "requires": ["base_domain", "proxy_host_or_route", "target_selection"],
                "mutates_on_preview": False,
                "apply_mutations": ["write_proxy_routes_if_operator_confirms", "reload_proxy_if_operator_confirms"],
            },
            {
                "id": "create_managed_reverse_proxy_vm",
                "label": "Create managed reverse-proxy VM",
                "intent": "Create a small proxy VM from an operator-selected PVE template and bind wildcard app routes.",
                "requires": [
                    "dns_provider",
                    "api_token_path",
                    "base_domain",
                    "pve_node",
                    "template_vmid",
                    "storage_profile",
                    "network_profile",
                    "target_selection",
                ],
                "secret_store_endpoint": "/api/cert/lifecycle/cloudflare-token",
                "mutates_on_preview": False,
                "apply_mutations": ["create_vm", "install_proxy", "issue_cert", "write_routes", "start_proxy"],
                "vm_defaults": proxy_vm_defaults,
            },
            {
                "id": "mixed",
                "label": "Mixed proxy and direct certs",
                "intent": "Proxy app-tier services while deploying direct certs to management appliances.",
                "requires": ["dns_provider", "api_token_path", "base_domain", "target_selection"],
                "secret_store_endpoint": "/api/cert/lifecycle/cloudflare-token",
                "mutates_on_preview": False,
                "apply_mutations": ["issue_cert", "configure_proxy_routes", "deploy_direct_targets"],
            },
        ],
        "dns_providers": SSL_ONBOARDING_DNS_PROVIDERS,
        "current_detection": {
            "base_domain": base_domain,
            "dns_provider": detected_provider,
            "acme_available": _acme_available(settings),
            "existing_acme_hint": existing_acme_hint,
            "configured_targets": len(targets),
            "reverse_proxy_host": settings.get("reverse_proxy_host", ""),
            "reverse_proxy_upstream_scheme": settings.get("reverse_proxy_upstream_scheme", "http"),
            "reverse_proxy_upstream_tls_verify": settings.get("reverse_proxy_upstream_tls_verify", True),
            "dashboard_origin_host": settings.get("dashboard_origin_host", ""),
            "dashboard_origin_port": settings.get("dashboard_origin_port", 8888),
            "management_mode": settings.get("management_mode") or "managed",
            "cloudflare_token": _cloudflare_token_status(cfg, settings),
            "adopt_existing_scope": {
                "mode": "wildcard_base_domain",
                "single_apply_registers_all_inferred_targets": True,
                "infer_targets_default": True,
            },
        },
        "dashboard_https": _ssl_dashboard_status(cfg, settings, targets),
        "trusted_proxy": {
            "cidrs": list(getattr(cfg, "trusted_proxy_cidrs", []) or []),
            "configured": bool(getattr(cfg, "trusted_proxy_cidrs", []) or []),
            "configure_endpoint": "/api/cert/lifecycle/trusted-proxy",
        },
    }


def _cert_dir(cfg):
    """Return cert data directory."""
    path = os.path.join(cfg.conf_dir, CERT_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_issued(cfg):
    """Load issued certificate inventory."""
    filepath = os.path.join(_cert_dir(cfg), "issued.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return {"certs": []}


def _save_issued(cfg, data):
    """Save issued certificate inventory."""
    filepath = os.path.join(_cert_dir(cfg), "issued.json")
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def _cert_settings(cfg):
    """Return normalized fleet certificate lifecycle settings."""
    raw = getattr(cfg, "certificates", {}) or {}
    settings = dict(DEFAULT_CERT_SETTINGS)
    if isinstance(raw, dict):
        settings.update({k: v for k, v in raw.items() if v is not None})
    settings["wildcard"] = str(settings.get("wildcard", "true")).lower() not in ("0", "false", "no", "off")
    scheme = str(settings.get("reverse_proxy_upstream_scheme") or "http").strip().lower()
    settings["reverse_proxy_upstream_scheme"] = scheme if scheme in ("http", "https") else "http"
    settings["reverse_proxy_upstream_tls_verify"] = _as_bool(
        settings.get("reverse_proxy_upstream_tls_verify"),
        settings["reverse_proxy_upstream_scheme"] == "https",
    )
    try:
        settings["dashboard_origin_port"] = int(settings.get("dashboard_origin_port") or 8888)
    except (TypeError, ValueError):
        settings["dashboard_origin_port"] = 8888
    data_dir = getattr(cfg, "data_dir", "") or os.path.join(getattr(cfg, "conf_dir", "."), "data")
    if settings.get("management_mode") != "adopted_existing":
        if not settings.get("acme_home"):
            settings["acme_home"] = os.path.join(data_dir, "acme")
        base_domain = str(settings.get("base_domain", "") or "").strip()
        if base_domain:
            managed_dir = os.path.join(data_dir, "certs", "managed", base_domain)
            settings["cert_fullchain_path"] = settings.get("cert_fullchain_path") or os.path.join(managed_dir, "fullchain.cer")
            settings["cert_key_path"] = settings.get("cert_key_path") or os.path.join(managed_dir, f"{base_domain}.key")
    return settings


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).lower() not in ("0", "false", "no", "off")


def _slug(value):
    text = str(value or "").strip().lower()
    text = "".join(ch if ch.isalnum() else "-" for ch in text)
    text = "-".join(part for part in text.split("-") if part)
    return text


def _public_container_route_name(container_name, vm_label=""):
    """Return a public route slug for a container, or "" for private sidecars."""
    raw = str(container_name or "").strip().lower().replace("_", "-")
    # Docker Compose prefixes often look like "2e33fcf71920-radarr"; strip
    # opaque hash prefixes so the public route is the product/service name.
    parts = [p for p in raw.split("-") if p]
    if len(parts) > 1 and len(parts[0]) >= 8 and all(ch in "0123456789abcdef" for ch in parts[0]):
        raw = "-".join(parts[1:])
    sidecars = {
        "gluetun",
        "flaresolverr",
        "kometa",
        "recyclarr",
        "qbit-port-sync",
        "qbit-port-manager",
        "tdarr-node",
        "tdarr-node-cpu",
    }
    if raw in sidecars or raw.endswith("-node") or raw.endswith("-node-cpu"):
        return ""
    if raw in ("qbittorrent", "qbit"):
        vm = str(vm_label or "").lower()
        if "2" in vm or vm.endswith("-02"):
            return "qbit-02"
        return "qbit-01"
    aliases = {"sabnzbd": "sab"}
    return aliases.get(raw, raw)


def _is_generic_bmc_label(label):
    slug = _slug(label)
    if slug in ("bmc", "idrac", "ilo", "ipmi", "redfish"):
        return True
    parts = slug.split("-")
    return len(parts) == 2 and parts[0] in ("bmc", "idrac", "ilo", "ipmi", "redfish") and parts[1].isdigit()


def _domain_from_hostname(hostname):
    parts = str(hostname or "").strip().lower().split(".")
    return ".".join(parts[1:]) if len(parts) > 1 else ""


def _identity_value(source, *names):
    for name in names:
        if isinstance(source, dict):
            value = source.get(name)
        else:
            value = getattr(source, name, "")
        value = str(value or "").strip()
        if value:
            return value
    return ""


def _identity_record(source, default_type=""):
    ip = _identity_value(source, "ip", "address")
    htype = (
        _identity_value(source, "device_type", "target_type", "type", "htype")
        or default_type
    ).lower()
    label = _identity_value(source, "label", "name", "key")
    hostname = _identity_value(source, "hostname", "fqdn", "dns_name", "manual_dns_entry").lower()
    service_tag = _identity_value(source, "service_tag", "svctag", "serial").upper()
    dns_rac_name = _identity_value(source, "dns_rac_name", "dnsracname").lower()
    identity_source = _identity_value(source, "identity_source", "source")
    return {
        "ip": ip,
        "type": htype,
        "label": label,
        "hostname": hostname,
        "service_tag": service_tag,
        "dns_rac_name": dns_rac_name,
        "identity_source": identity_source,
    }


def _inventory_identity_records(cfg):
    records = []
    for dev in (getattr(getattr(cfg, "fleet_boundaries", None), "physical", {}) or {}).values():
        rec = _identity_record(dev)
        if rec["ip"]:
            rec["identity_source"] = rec["identity_source"] or "fleet-boundaries"
            records.append(rec)
    for host in getattr(cfg, "hosts", []) or []:
        rec = _identity_record(host)
        if rec["ip"]:
            rec["identity_source"] = rec["identity_source"] or "hosts"
            records.append(rec)
    return records


def _usable_identity_label(record):
    hostname = record.get("hostname", "")
    if hostname and not _is_generic_bmc_label(hostname.split(".")[0]):
        return hostname.split(".")[0], hostname
    label = record.get("label", "")
    if label and not _is_generic_bmc_label(label):
        return _slug(label), ""
    dns_rac_name = record.get("dns_rac_name", "")
    if dns_rac_name and not _is_generic_bmc_label(dns_rac_name):
        return _slug(dns_rac_name), ""
    return "", ""


def _curated_device_identity(cfg, ip, service_tag=""):
    ip = str(ip or "").strip()
    service_tag = str(service_tag or "").strip().upper()
    for rec in _inventory_identity_records(cfg):
        if rec.get("type") not in ("idrac", "ilo", "ipmi", "bmc", "redfish"):
            continue
        if ip and rec.get("ip") != ip:
            continue
        if service_tag and rec.get("service_tag") and rec.get("service_tag") != service_tag:
            continue
        label, hostname = _usable_identity_label(rec)
        if label:
            return {
                "label": label,
                "hostname": hostname,
                "service_tag": rec.get("service_tag", ""),
                "identity_source": rec.get("identity_source") or "curated_inventory",
            }
    return {}


def _ptr_identity(ip):
    try:
        hostname = socket.gethostbyaddr(ip)[0].strip().lower()
    except (OSError, socket.herror, socket.gaierror):
        return {}
    # musl/Alpine may return the numeric address itself when no PTR exists.
    # That is not a DNS identity and must never become a certificate label.
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return {}
    if hostname and not _is_generic_bmc_label(hostname.split(".")[0]):
        return {"label": hostname.split(".")[0], "hostname": hostname, "identity_source": "ptr"}
    return {}


def _snmp_device_identity(cfg, ip):
    """Return bounded SNMP self-report identity for generic device labels."""
    try:
        from freq.modules.snmp import get_snmp_identity

        ident = get_snmp_identity(
            ip,
            community=getattr(cfg, "snmp_community", "public") or "public",
            auth=None,
            timeout=2,
        )
    except Exception:
        return {}
    if not ident.get("reachable"):
        return {}
    label = _slug(ident.get("sys_name", ""))
    if not label or _is_generic_bmc_label(label):
        label = ""
    service_tag = str(ident.get("serial", "") or "").strip().upper()
    result = {
        "label": label,
        "hostname": "",
        "service_tag": service_tag,
        "identity_source": "snmp",
        "model": str(ident.get("model", "") or "").strip(),
        "description": str(ident.get("sys_descr", "") or "").strip(),
    }
    return result if label or service_tag or result["model"] or result["description"] else {}


def _cert_device_identity(cfg, host_or_raw, htype, ip, label, hostname, base_domain):
    """Return display label/hostname for direct management certificate targets."""
    htype = str(htype or "").strip().lower()
    label = str(label or "").strip()
    hostname = str(hostname or "").strip().lower()
    ip = str(ip or "").strip()
    raw_rec = _identity_record(host_or_raw, htype)
    service_tag = raw_rec.get("service_tag", "")
    domain = base_domain or _domain_from_hostname(hostname)
    generic_input = _is_generic_bmc_label(label) or _is_generic_bmc_label(hostname.split(".")[0])

    if htype in ("idrac", "ilo", "ipmi", "bmc", "redfish"):
        curated = _curated_device_identity(cfg, ip, service_tag)
        if curated:
            resolved_hostname = curated.get("hostname") or (
                f"{curated['label']}.{domain}" if domain else ""
            )
            return curated["label"], resolved_hostname, curated.get("service_tag", service_tag), curated.get("identity_source", "curated_inventory")

        label_from_raw, hostname_from_raw = _usable_identity_label(raw_rec)
        if label_from_raw:
            return label_from_raw, hostname_from_raw or (f"{label_from_raw}.{domain}" if domain else ""), service_tag, raw_rec.get("identity_source") or "device_self_report"

        snmp = _snmp_device_identity(cfg, ip)
        if snmp:
            snmp_label = snmp.get("label") or ip
            return snmp_label, snmp.get("hostname", ""), snmp.get("service_tag", service_tag), snmp.get("identity_source", "snmp")

        ptr = _ptr_identity(ip)
        if ptr:
            return ptr["label"], ptr["hostname"], service_tag, ptr["identity_source"]

        if generic_input:
            return ip, "", service_tag, "unnamed_ip"

    if hostname and not _is_generic_bmc_label(hostname.split(".")[0]):
        return hostname.split(".")[0], hostname, service_tag, raw_rec.get("identity_source", "")
    slug = _slug(label or htype)
    return slug, f"{slug}.{domain}" if slug and domain else hostname or slug, service_tag, raw_rec.get("identity_source", "")


def _cert_targets(cfg):
    """Return normalized certificate deployment targets."""
    targets = []
    settings = _cert_settings(cfg)
    base_domain = str(settings.get("base_domain", "") or "").strip().lower()
    for idx, raw in enumerate(getattr(cfg, "cert_targets", []) or []):
        if not isinstance(raw, dict):
            continue
        hostname = str(raw.get("hostname", "")).strip()
        label = str(raw.get("label") or hostname or f"target-{idx + 1}").strip()
        target_type = str(raw.get("target_type") or raw.get("type") or "unknown").strip()
        driver = str(raw.get("deploy_driver") or target_type).strip()
        service_tag = str(raw.get("service_tag", "")).strip().upper()
        identity_source = str(raw.get("identity_source", "")).strip()
        target_identity_type = target_type.lower()
        if target_identity_type in ("idrac", "bmc", "ipmi", "ilo", "redfish") or driver == "idrac_racadm":
            label, hostname, service_tag, identity_source = _cert_device_identity(
                cfg,
                raw,
                target_identity_type if target_identity_type in ("idrac", "bmc", "ipmi", "ilo", "redfish") else "idrac",
                raw.get("ip", ""),
                label,
                hostname,
                base_domain,
            )
        targets.append(
            {
                "label": label,
                "target_type": target_type,
                "hostname": hostname,
                "ip": str(raw.get("ip", "")).strip(),
                "port": int(raw.get("port", 443) or 443),
                "deploy_driver": driver,
                "cert_source": str(raw.get("cert_source", "wildcard")).strip(),
                "service_name": str(raw.get("service_name", "")).strip(),
                "subdomain": str(raw.get("subdomain", "")).strip(),
                "mode": str(raw.get("mode", "")).strip(),
                "origin_ip": str(raw.get("origin_ip", "")).strip(),
                "origin_port": int(raw.get("origin_port", 0) or 0),
                "origin_scheme": str(raw.get("origin_scheme", "")).strip().lower(),
                "origin_tls_verify": _as_bool(raw.get("origin_tls_verify"), False),
                "service_tag": service_tag,
                "identity_source": identity_source,
                "credential_ref": str(raw.get("credential_ref", "")).strip(),
                "scope": str(raw.get("scope", "")).strip(),
                "hostname_override": str(raw.get("hostname_override", "")).strip(),
                "ssh_user": str(raw.get("ssh_user", "")).strip(),
                "api_key_path": str(raw.get("api_key_path", "")).strip(),
                "cert_fullchain_path": str(raw.get("cert_fullchain_path", "")).strip(),
                "cert_key_path": str(raw.get("cert_key_path", "")).strip(),
                "remote_cert_dir": str(raw.get("remote_cert_dir", "")).strip(),
                "restart_policy": str(raw.get("restart_policy", "")).strip(),
                "verify_hostname": _as_bool(raw.get("verify_hostname"), bool(hostname)),
                "host_header_check": _as_bool(raw.get("host_header_check"), driver == "pfsense_config"),
                "resolver_private_domain": _as_bool(raw.get("resolver_private_domain"), driver == "pfsense_config"),
            }
        )
    return targets


def _merge_cert_targets(primary, discovered):
    """Merge configured and discovered cert targets by hostname/label."""
    merged = []
    seen = set()
    for target in list(primary or []) + list(discovered or []):
        key = (target.get("hostname") or target.get("label") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(target)
    return merged


def _cert_targets_from_catalog(catalog, base_domain, reverse_proxy_host=""):
    """Build cert targets from an operator-confirmed service/web-UI catalog."""
    if isinstance(catalog, dict):
        raw_entries = catalog.get("services") or catalog.get("targets") or catalog.get("items") or []
    elif isinstance(catalog, list):
        raw_entries = catalog
    else:
        raw_entries = []

    targets = []
    for idx, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            continue
        if str(raw.get("enabled", "true")).lower() in ("0", "false", "no", "off"):
            continue
        scope = str(raw.get("scope", "include") or "include").strip().lower()
        if scope in ("exclude", "excluded", "ignore", "ignored"):
            continue

        name = str(raw.get("name") or raw.get("service_name") or raw.get("label") or f"service-{idx + 1}").strip()
        label = str(raw.get("label") or name).strip()
        subdomain = _slug(raw.get("subdomain") or raw.get("slug") or name)
        hostname = str(raw.get("hostname") or raw.get("hostname_override") or "").strip().lower()
        if not hostname and subdomain and base_domain:
            hostname = f"{subdomain}.{base_domain}"
        if not hostname:
            continue

        mode = str(raw.get("mode") or raw.get("ssl_mode") or "direct").strip().lower().replace("-", "_")
        behind_proxy = mode in ("behind_proxy", "proxy", "proxied", "reverse_proxy")
        origin_ip = str(raw.get("origin_ip") or raw.get("ip") or raw.get("host") or "").strip()
        origin_port = int(raw.get("origin_port") or raw.get("port") or (443 if not behind_proxy else 0) or 0)
        proxy_ip = str(raw.get("proxy_ip") or raw.get("reverse_proxy_ip") or "").strip()
        connect_ip = proxy_ip if behind_proxy else origin_ip
        origin_scheme = str(
            raw.get("origin_scheme")
            or raw.get("upstream_scheme")
            or raw.get("reverse_proxy_upstream_scheme")
            or ("http" if behind_proxy else "")
        ).strip().lower()
        if origin_scheme not in ("http", "https", ""):
            origin_scheme = "http"
        origin_tls_verify = _as_bool(
            raw.get("origin_tls_verify", raw.get("upstream_tls_verify", raw.get("reverse_proxy_upstream_tls_verify"))),
            origin_scheme == "https",
        )

        targets.append(
            {
                "label": label,
                "service_name": name,
                "target_type": str(raw.get("target_type") or raw.get("type") or "web_ui").strip(),
                "hostname": hostname,
                "subdomain": subdomain,
                "ip": connect_ip,
                "port": int(raw.get("tls_port") or raw.get("public_port") or (443 if behind_proxy else origin_port) or 443),
                "origin_ip": origin_ip if behind_proxy else str(raw.get("origin_ip") or "").strip(),
                "origin_port": origin_port if behind_proxy else int(raw.get("origin_port") or 0),
                "origin_scheme": origin_scheme,
                "origin_tls_verify": origin_tls_verify,
                "mode": "behind_proxy" if behind_proxy else "direct",
                "deploy_driver": str(
                    raw.get("deploy_driver") or ("reverse_proxy" if behind_proxy else raw.get("type") or "web_ui_direct")
                ).strip(),
                "cert_source": str(raw.get("cert_source") or "wildcard").strip(),
                "restart_policy": str(raw.get("restart_policy") or ("proxy_reload" if behind_proxy else "")).strip(),
                "verify_hostname": _as_bool(raw.get("verify_hostname"), True),
                "credential_ref": str(raw.get("credential_ref") or raw.get("credential_pointer") or "").strip(),
                "scope": "include",
                "hostname_override": str(raw.get("hostname_override") or "").strip(),
                "reverse_proxy_host": str(raw.get("reverse_proxy_host") or reverse_proxy_host or "").strip(),
            }
        )
    return targets


def _source_paths(settings, target=None):
    """Return local fullchain/key paths for the configured certificate source."""
    target = target or {}
    base_domain = settings.get("base_domain", "")
    fullchain = target.get("cert_fullchain_path") or settings.get("cert_fullchain_path")
    key = target.get("cert_key_path") or settings.get("cert_key_path")
    if settings.get("management_mode") == "adopted_existing" and not fullchain and not key:
        return {"fullchain": "", "key": "", "source_mode": "external_existing"}
    if not fullchain or not key:
        acme_home = os.path.expanduser(settings.get("acme_home") or "~/.acme.sh")
        if base_domain:
            acme_dir = os.path.join(acme_home, f"{base_domain}_ecc")
            fullchain = fullchain or os.path.join(acme_dir, "fullchain.cer")
            key = key or os.path.join(acme_dir, f"{base_domain}.key")
    return {
        "fullchain": os.path.expanduser(fullchain) if fullchain else "",
        "key": os.path.expanduser(key) if key else "",
        "source_mode": "local_files",
    }


def _dns_provider_acme_name(provider):
    """Map config DNS provider names to acme.sh --dns names."""
    mapping = {"cloudflare": "dns_cf"}
    return mapping.get((provider or "").strip().lower(), provider or "")


def _acme_binary(settings):
    configured = settings.get("acme_binary", "")
    if configured:
        return os.path.expanduser(configured)
    found = shutil.which("acme.sh")
    if found:
        return found
    home_binary = os.path.join(os.path.expanduser(settings.get("acme_home") or "~/.acme.sh"), "acme.sh")
    if os.path.isfile(home_binary):
        return home_binary
    return home_binary


def _acme_available(settings):
    binary = _acme_binary(settings)
    return bool(shutil.which(binary) or os.path.isfile(binary))


def _install_acme_sh(settings):
    """Install acme.sh into acme_home. Called only from explicit --yes flows."""
    acme_home = os.path.expanduser(settings.get("acme_home") or "~/.acme.sh")
    os.makedirs(acme_home, mode=0o700, exist_ok=True)
    url = settings.get("acme_install_url") or "https://get.acme.sh"
    fd, script_path = tempfile.mkstemp(prefix="freq-acme-install-", suffix=".sh")
    os.close(fd)
    try:
        urllib.request.urlretrieve(url, script_path)
        os.chmod(script_path, 0o700)
        return subprocess.run(
            ["sh", script_path, "--install", "--home", acme_home],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def _dns_records(settings, targets):
    """Build DNS record intent from cert targets."""
    records = []
    for target in targets:
        if not target.get("hostname") or not target.get("ip"):
            continue
        records.append(
            {
                "type": "A",
                "hostname": target["hostname"],
                "value": target["ip"],
                "strategy": settings.get("record_strategy", ""),
                "proxied": False,
            }
        )
    return records


def _target_rebind_actions(settings, target):
    """Return Host-header/rebind protection actions required by a target."""
    actions = []
    if target.get("deploy_driver") == "pfsense_config" or target.get("host_header_check"):
        actions.append(
            {
                "type": "webgui_althostname",
                "hostname": target.get("hostname", ""),
                "reason": "pfSense webGUI DNS-rebind Host-header allowlist",
            }
        )
    if (
        target.get("deploy_driver") == "pfsense_config"
        and target.get("resolver_private_domain")
        and settings.get("record_strategy") == "public-private-a"
        and settings.get("base_domain")
    ):
        actions.append(
            {
                "type": "unbound_private_domain",
                "domain": settings["base_domain"],
                "reason": "allow public-zone private-IP answers through pfSense DNS resolver",
            }
        )
    return actions


def _build_acme_issue_command(settings):
    """Return an acme.sh issue command without embedding secrets."""
    base_domain = settings.get("base_domain", "")
    provider = _dns_provider_acme_name(settings.get("dns_provider"))
    cmd = [
        _acme_binary(settings),
        "--issue",
        "--dns",
        provider,
        "-d",
        base_domain,
        "--keylength",
        settings.get("acme_keylength") or "ec-256",
    ]
    if settings.get("wildcard", True):
        cmd.extend(["-d", f"*.{base_domain}"])
    return [part for part in cmd if part]


def _build_acme_install_command(settings):
    """Return an acme.sh install-cert command for persistent managed paths."""
    base_domain = settings.get("base_domain", "")
    source = _source_paths(settings)
    for path in (source.get("fullchain"), source.get("key")):
        if path:
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    cmd = [
        _acme_binary(settings),
        "--install-cert",
        "-d",
        base_domain,
        "--ecc",
        "--fullchain-file",
        source.get("fullchain", ""),
        "--key-file",
        source.get("key", ""),
        "--reloadcmd",
        "freq --yes cert deploy",
    ]
    return [part for part in cmd if part]


def _build_acme_renew_command(settings):
    """Return an acme.sh renew command without embedding secrets."""
    base_domain = settings.get("base_domain", "")
    cmd = [_acme_binary(settings), "--renew", "-d", base_domain, "--ecc"]
    return [part for part in cmd if part]


def _build_deploy_steps(settings, target):
    """Build executable deployment steps for a target without secret values."""
    driver = target.get("deploy_driver", "")
    source = _source_paths(settings, target)
    if source.get("source_mode") == "external_existing":
        return [
            {
                "kind": "adopt_existing",
                "message": "Existing certificate is externally owned; pve-freq verifies served TLS and does not copy local cert files.",
            }
        ]
    remote_dir = target.get("remote_cert_dir") or f"/tmp/freq-cert-{target.get('label') or target.get('hostname')}"
    remote_fullchain = f"{remote_dir}/fullchain.pem"
    remote_key = f"{remote_dir}/privkey.pem"
    steps = []

    if driver in ("proxmox_pvenode", "pfsense_config"):
        steps.extend(
            [
                {"kind": "ssh", "command": f"mkdir -p {shlex.quote(remote_dir)} && chmod 700 {shlex.quote(remote_dir)}"},
                {"kind": "scp", "local": source["fullchain"], "remote": remote_fullchain},
                {"kind": "scp", "local": source["key"], "remote": remote_key},
            ]
        )

    if driver == "proxmox_pvenode":
        steps.append(
            {
                "kind": "ssh",
                "command": (
                    f"pvenode cert set {shlex.quote(remote_fullchain)} {shlex.quote(remote_key)} "
                    "--restart --force && "
                    f"rm -rf {shlex.quote(remote_dir)}"
                ),
            }
        )
    elif driver == "pfsense_config":
        steps.append(
            {
                "kind": "ssh",
                "command": _pfsense_config_command(settings, target, remote_fullchain, remote_key, remote_dir),
            }
        )
    elif driver == "truenas_api":
        steps.extend(
            [
                {"kind": "truenas_import", "fullchain": source["fullchain"], "key": source["key"]},
                {"kind": "ssh", "command": "midclt call system.general.ui_restart"},
            ]
        )
    elif driver == "reverse_proxy":
        steps.append({"kind": "proxy_config", "message": "reverse proxy deployment is handled by the proxy driver"})
    else:
        steps.append({"kind": "unsupported", "message": f"unsupported deploy_driver: {driver}"})

    return steps


def _pfsense_config_command(settings, target, remote_fullchain, remote_key, remote_dir):
    """Return a pfSense config injection command that reads cert material from files."""
    hostname = target.get("hostname", "")
    descr = f"freq_{hostname.replace('.', '_')}"
    base_domain = settings.get("base_domain", "")
    php = f"""
$cert = trim(file_get_contents('{remote_fullchain}'));
$key = trim(file_get_contents('{remote_key}'));
$descr = '{descr}';
$hostname = '{hostname}';
$domain = '{base_domain}';
$config['cert'] = array_values(array_filter($config['cert'] ?? array(), function ($item) use ($descr) {{
    return (($item['descr'] ?? '') !== $descr);
}}));
$refid = uniqid();
$config['cert'][] = array('refid' => $refid, 'descr' => $descr, 'type' => 'server', 'crt' => base64_encode($cert), 'prv' => base64_encode($key));
$config['system']['webgui']['ssl-certref'] = $refid;
$existing = trim($config['system']['webgui']['althostnames'] ?? '');
$hosts = preg_split('/\\s+/', $existing, -1, PREG_SPLIT_NO_EMPTY);
if ($hostname && !in_array($hostname, $hosts, true)) {{
    $hosts[] = $hostname;
}}
$config['system']['webgui']['althostnames'] = implode(' ', $hosts);
$custom = $config['unbound']['custom_options'] ?? '';
$needle = 'private-domain: "' . $domain . '"';
if ($domain && strpos($custom, $needle) === false) {{
    $config['unbound']['custom_options'] = rtrim($custom) . "\\nserver:\\n" . $needle . "\\n";
}}
write_config('freq certificate deployment for ' . $hostname);
"""
    encoded = shlex.quote(php)
    return (
        f"printf %s {encoded} | /usr/local/sbin/pfSsh.php && "
        "/etc/rc.restart_webgui && "
        "if command -v pfSsh.php >/dev/null 2>&1; then /usr/local/sbin/pfSsh.php playback svc restart unbound || true; fi && "
        f"rm -rf {shlex.quote(remote_dir)}"
    )


def _build_lifecycle_plan(cfg):
    """Build a read-only certificate lifecycle plan for CLI/API display."""
    settings = _cert_settings(cfg)
    targets = _cert_targets(cfg)
    warnings = []
    adopted_existing = settings.get("management_mode") == "adopted_existing"
    if adopted_existing and settings.get("base_domain"):
        targets = _merge_cert_targets(targets, _infer_cert_targets(cfg, settings.get("base_domain")))

    if not settings.get("base_domain"):
        warnings.append("missing [certificates].base_domain")
    if not adopted_existing and not settings.get("dns_provider"):
        warnings.append("missing [certificates].dns_provider")
    token_path = settings.get("dns_token_path") or ""
    if not adopted_existing and not token_path:
        warnings.append("missing [certificates].dns_token_path")
    elif token_path and not os.path.isfile(os.path.expanduser(token_path)):
        warnings.append(f"dns token path not found: {token_path}")
    if not adopted_existing and settings.get("dns_provider") == "cloudflare" and not settings.get("cloudflare_zone_id"):
        warnings.append("missing [certificates].cloudflare_zone_id")
    if not adopted_existing and settings.get("record_strategy") == "public-private-a":
        warnings.append("record_strategy public-private-a publishes private IPs in public DNS")
    if not targets:
        warnings.append("no [[cert_target]] entries configured")

    source = _source_paths(settings)
    for label in ("fullchain", "key"):
        path = source.get(label, "")
        if path and not os.path.isfile(path):
            warnings.append(f"certificate {label} path not found: {path}")

    enriched_targets = []
    for target in targets:
        enriched = dict(target)
        enriched["capabilities"] = DRIVER_CAPABILITIES.get(target.get("deploy_driver"), {})
        enriched["rebind_actions"] = _target_rebind_actions(settings, target)
        enriched["deploy_steps"] = _build_deploy_steps(settings, target)
        enriched_targets.append(enriched)

    wildcard_name = f"*.{settings['base_domain']}" if settings.get("base_domain") else ""
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "settings": settings,
        "wildcard_name": wildcard_name,
        "source_paths": source,
        "dns_records": _dns_records(settings, targets),
        "targets": enriched_targets,
        "warnings": warnings,
    }


def _select_targets(plan, selector):
    """Filter plan targets by label/hostname; empty selector means all."""
    targets = plan.get("targets", [])
    if not selector:
        return targets
    return [
        t
        for t in targets
        if selector in (t.get("label"), t.get("hostname"), t.get("ip"))
    ]


def _target_host(target):
    return target.get("ip") or target.get("hostname")


def _target_ssh_user(cfg, target):
    return target.get("ssh_user") or getattr(cfg, "ssh_service_account", "") or None


def _target_htype(target):
    driver = target.get("deploy_driver", "")
    target_type = target.get("target_type", "")
    if driver == "proxmox_pvenode" or target_type == "proxmox_ve_node":
        return "pve"
    if driver == "truenas_api" or "truenas" in target_type:
        return "truenas"
    if driver == "pfsense_config" or "pfsense" in target_type:
        return "pfsense"
    return "linux"


def _target_use_sudo(target):
    return target.get("deploy_driver") not in ("pfsense_config",)


def _build_scp_cmd(cfg, target, local_path, remote_path):
    """Build scp command for cert deployment without shell interpolation."""
    auth = _device_ssh_auth(cfg, target)
    user = target.get("ssh_user") or auth.get("user") or _target_ssh_user(cfg, target)
    host = _target_host(target)
    cmd = [
        "scp",
        "-o",
        f"ConnectTimeout={getattr(cfg, 'ssh_connect_timeout', 5)}",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    password_file = auth.get("password_file", "")
    if password_file and os.path.isfile(password_file):
        cmd = ["sshpass", "-f", password_file] + cmd
    else:
        cmd.extend(["-o", "BatchMode=yes"])
    key_path = auth.get("key_path") or getattr(cfg, "ssh_key_path", "")
    if key_path and not password_file:
        cmd.extend(["-i", key_path])
    cmd.extend([local_path, f"{user}@{host}:{remote_path}"])
    if auth.get("local_user"):
        cmd = ["sudo", "-n", "-u", auth["local_user"]] + cmd
    if auth.get("sudo_password_file") and password_file:
        cmd = ["sudo", "-n"] + cmd
    return cmd


def _run_scp(cfg, target, local_path, remote_path):
    cmd = _build_scp_cmd(cfg, target, local_path, remote_path)
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)


def _execute_ssh_step(cfg, target, command):
    from freq.core.ssh import run as ssh_run

    auth = _device_ssh_auth(cfg, target)
    return ssh_run(
        host=_target_host(target),
        command=command,
        user=target.get("ssh_user") or auth.get("user") or _target_ssh_user(cfg, target),
        key_path=auth.get("key_path") or getattr(cfg, "ssh_key_path", ""),
        connect_timeout=getattr(cfg, "ssh_connect_timeout", 5),
        command_timeout=90,
        htype=_target_htype(target),
        use_sudo=_target_use_sudo(target),
        local_user=auth.get("local_user") or None,
        password_file=auth.get("password_file") or None,
        sudo_password_file=bool(auth.get("sudo_password_file")),
        cfg=cfg,
    )


def _device_ssh_auth(cfg, target):
    """Resolve target auth from staged device credentials, with config fallback."""
    try:
        from freq.core.device_credentials import resolve_staged_device_ssh_auth

        return resolve_staged_device_ssh_auth(cfg, _target_htype(target)) or {}
    except Exception:
        return {
            "user": _target_ssh_user(cfg, target),
            "key_path": getattr(cfg, "ssh_key_path", ""),
            "password_file": "",
            "local_user": "",
            "sudo_password_file": False,
        }


def _read_file(path):
    with open(os.path.expanduser(path), "r") as f:
        return f.read().strip()


def _acme_env(settings):
    """Build ACME environment from credential paths without logging secrets."""
    env = os.environ.copy()
    if settings.get("dns_provider") == "cloudflare":
        token_path = settings.get("dns_token_path", "")
        if token_path:
            env["CF_Token"] = _read_file(token_path)
        if settings.get("cloudflare_zone_id"):
            env["CF_Zone_ID"] = str(settings["cloudflare_zone_id"])
    return env


def _run_acme_command(settings, command):
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=180,
        env=_acme_env(settings),
    )


def _truenas_api_request(target, path, method="GET", payload=None):
    api_key_path = target.get("api_key_path", "")
    if not api_key_path:
        raise RuntimeError("missing api_key_path for truenas_api target")
    api_key = _read_file(api_key_path)
    host = target.get("hostname") or target.get("ip")
    url = f"https://{host}{path}"
    data = None
    headers = {"Authorization": f"Bearer {api_key}"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        body = resp.read().decode("utf-8", "replace")
        return json.loads(body) if body else None


def _execute_truenas_import(target, step):
    cert_text = _read_file(step["fullchain"])
    key_text = _read_file(step["key"])
    cert_name = ("freq_" + (target.get("hostname") or target.get("label", "cert"))).replace(".", "_").replace("-", "_")
    payload = {
        "name": cert_name,
        "create_type": "CERTIFICATE_CREATE_IMPORTED",
        "certificate": cert_text,
        "privatekey": key_text,
    }
    created = _truenas_api_request(target, "/api/v2.0/certificate", method="POST", payload=payload)
    cert_id = created.get("id") if isinstance(created, dict) else created
    if not cert_id:
        raise RuntimeError(f"TrueNAS certificate import did not return a certificate id: {created!r}")
    _truenas_api_request(target, "/api/v2.0/system/general", method="PUT", payload={"ui_certificate": cert_id})
    return {"returncode": 0, "stdout": f"ui_certificate={cert_id}", "stderr": ""}


def _execute_deploy_step(cfg, target, step):
    kind = step.get("kind")
    if kind == "scp":
        source = step["local"]
        if not os.path.isfile(source):
            return {"returncode": 1, "stdout": "", "stderr": f"source file not found: {source}"}
        result = _run_scp(cfg, target, source, step["remote"])
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    if kind == "ssh":
        result = _execute_ssh_step(cfg, target, step["command"])
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    if kind == "truenas_import":
        try:
            return _execute_truenas_import(target, step)
        except Exception as e:
            return {"returncode": 1, "stdout": "", "stderr": str(e)}
    return {"returncode": 1, "stdout": "", "stderr": step.get("message", f"unsupported step kind: {kind}")}


def _verify_tls_target(target):
    """Verify a target TLS endpoint with SNI and optional hostname checking."""
    host = target.get("hostname") or target.get("ip")
    connect_host = target.get("ip") or target.get("hostname")
    port = int(target.get("port", 443) or 443)
    verify_hostname = target.get("verify_hostname", True)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    driver = str(target.get("deploy_driver") or "").lower()
    target_type = str(target.get("target_type") or "").lower()
    if driver in ("switch_ios", "idrac_racadm") or target_type in ("switch", "idrac"):
        try:
            ctx.set_ciphers("ALL:@SECLEVEL=0")
        except ssl.SSLError:
            pass
        if hasattr(ssl, "TLSVersion"):
            try:
                ctx.minimum_version = ssl.TLSVersion.TLSv1
            except (ValueError, ssl.SSLError):
                pass
    started = time.monotonic()
    try:
        with socket.create_connection((connect_host, port), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                der = ssock.getpeercert(binary_form=True)
                cert = _decode_der_peer_cert(der) if der else {}
                if verify_hostname:
                    ssl.match_hostname(cert, host)
        duration = time.monotonic() - started
        subject = dict(x[0] for x in cert.get("subject", [])) if cert else {}
        issuer = dict(x[0] for x in cert.get("issuer", [])) if cert else {}
        sans = [entry[1] for entry in cert.get("subjectAltName", [])] if cert else []
        return {
            "label": target.get("label"),
            "hostname": host,
            "connect_host": connect_host,
            "port": port,
            "ok": True,
            "duration": round(duration, 3),
            "subject": subject.get("commonName", ""),
            "issuer": issuer.get("organizationName", issuer.get("commonName", "")),
            "sans": sans,
            "expires": cert.get("notAfter", "") if cert else "",
            "fingerprint_sha256": hashlib.sha256(der).hexdigest() if der else "",
            "self_signed": cert.get("subject") == cert.get("issuer") if cert else False,
        }
    except Exception as e:
        return {
            "label": target.get("label"),
            "hostname": host,
            "connect_host": connect_host,
            "port": port,
            "ok": False,
            "error": str(e),
        }


def _decode_der_peer_cert(der):
    """Decode an unverified peer DER cert into ssl.getpeercert()-style data."""
    path = ""
    try:
        pem = ssl.DER_cert_to_PEM_cert(der)
        fd, path = tempfile.mkstemp(prefix="freq-peer-cert-", suffix=".pem")
        with os.fdopen(fd, "w") as f:
            f.write(pem)
        return ssl._ssl._test_decode_cert(path)
    except Exception as e:
        logger.warn(f"cert_management: failed to decode peer cert: {e}")
        return {}
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _pem_cert_fingerprint(path):
    if not path or not os.path.isfile(path):
        return ""
    with open(os.path.expanduser(path), "r") as f:
        text = f.read()
    start = text.find("-----BEGIN CERTIFICATE-----")
    end = text.find("-----END CERTIFICATE-----")
    if start < 0 or end < 0:
        return ""
    pem = text[start:end + len("-----END CERTIFICATE-----")]
    try:
        der = ssl.PEM_cert_to_DER_cert(pem)
    except Exception:
        return ""
    return hashlib.sha256(der).hexdigest()


def _dnsname_matches(pattern, hostname):
    pattern = str(pattern or "").lower()
    hostname = str(hostname or "").lower()
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return hostname.endswith(suffix) and hostname.count(".") == pattern.count(".")
    return pattern == hostname


def _classify_tls_probe(settings, target, probe, managed_fingerprint=""):
    if not probe.get("ok"):
        return "UNREACHABLE"
    hostname = probe.get("hostname") or target.get("hostname") or ""
    sans = probe.get("sans") or []
    san_match = any(_dnsname_matches(san, hostname) for san in sans)
    issuer = str(probe.get("issuer") or "").lower()
    le_markers = ("let's encrypt", "lets encrypt", "ye1", "ye2", "r3", "r10", "r11", "e1", "e5", "e6")
    is_lets_encrypt = any(marker in issuer for marker in le_markers)
    fp_match = bool(managed_fingerprint and probe.get("fingerprint_sha256") == managed_fingerprint)
    if fp_match or (is_lets_encrypt and san_match and not probe.get("self_signed")):
        return "SERVING_MANAGED_WILDCARD"
    return "SELF_SIGNED_OR_OTHER"


def _reconcile_lifecycle_targets(cfg):
    """Probe configured cert targets and classify what is actually served."""
    settings = _cert_settings(cfg)
    targets = _cert_targets(cfg)
    if settings.get("management_mode") == "adopted_existing" and settings.get("base_domain"):
        targets = _merge_cert_targets(targets, _infer_cert_targets(cfg, settings.get("base_domain")))
    source = _source_paths(settings)
    managed_fingerprint = _pem_cert_fingerprint(source.get("fullchain"))
    results = []
    external_renewal_owner = (
        settings.get("management_mode") == "adopted_existing"
        and str(settings.get("renewal_owner") or "external").strip().lower() == "external"
    )
    for target in targets:
        probe = _verify_tls_target(target)
        probe["classification"] = _classify_tls_probe(settings, target, probe, managed_fingerprint)
        probe["managed_fingerprint_sha256"] = managed_fingerprint
        driver = target.get("deploy_driver", "")
        deploy_supported = driver in {
            "reverse_proxy",
            "proxmox_pvenode",
            "truenas_api",
            "pfsense_config",
            "idrac_racadm",
            "switch_ios",
        }
        managed_renewal = (
            settings.get("management_mode") != "adopted_existing"
            and bool(source.get("fullchain"))
            and bool(source.get("key"))
            and deploy_supported
        )
        probe["renewal_hooked"] = managed_renewal
        probe["renewal_owner"] = str(settings.get("renewal_owner") or "").strip()
        probe["renewal_status"] = "external_owner" if external_renewal_owner else ("hooked" if probe["renewal_hooked"] else "gap")
        probe["renewal_gap"] = (
            probe["classification"] == "SERVING_MANAGED_WILDCARD"
            and not probe["renewal_hooked"]
            and not external_renewal_owner
        )
        results.append(probe)
    return {
        "ok": True,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "settings": settings,
        "source_paths": source,
        "managed_fingerprint_sha256": managed_fingerprint,
        "targets": results,
        "summary": {
            "total": len(results),
            "serving_managed": sum(1 for r in results if r.get("classification") == "SERVING_MANAGED_WILDCARD"),
            "pending": sum(1 for r in results if r.get("classification") == "SELF_SIGNED_OR_OTHER"),
            "unreachable": sum(1 for r in results if r.get("classification") == "UNREACHABLE"),
            "renewal_gaps": sum(1 for r in results if r.get("renewal_gap")),
            "external_renewal": sum(1 for r in results if r.get("renewal_status") == "external_owner"),
        },
    }


def _cert_days_left(expires):
    if not expires:
        return None
    try:
        epoch = ssl.cert_time_to_seconds(expires)
        return int((epoch - time.time()) // 86400)
    except Exception:
        return None


def _cert_inventory_from_reconcile(cfg, existing=None, reconcile=None):
    """Return persisted cert inventory, or synthesize it from live probes."""
    existing = existing or {}
    if existing.get("certs"):
        return existing
    reconcile = reconcile or _reconcile_lifecycle_targets(cfg)
    certs = []
    for probe in reconcile.get("targets", []):
        if not probe.get("ok"):
            continue
        days_left = _cert_days_left(probe.get("expires", ""))
        status = "valid"
        if days_left is not None and days_left < 0:
            status = "expired"
        elif days_left is not None and days_left < 30:
            status = "expiring"
        certs.append(
            {
                "domain": probe.get("hostname", ""),
                "name": probe.get("label") or probe.get("hostname", ""),
                "issuer": probe.get("issuer", ""),
                "expires": probe.get("expires", ""),
                "not_after": probe.get("expires", ""),
                "days_left": days_left,
                "status": status,
                "classification": probe.get("classification", ""),
                "sans": probe.get("sans", []),
                "source": reconcile.get("source_paths", {}).get("source_mode", "served_probe"),
                "renewal_status": probe.get("renewal_status", ""),
            }
        )
    return {
        "certs": certs,
        "scan_time": reconcile.get("generated_at", ""),
        "source": "reconcile_probe",
        "summary": reconcile.get("summary", {}),
    }


def _issued_from_reconcile(cfg, existing=None, reconcile=None, inventory=None):
    """Return issued cache, or external ownership summary for adopted SSL."""
    existing = existing or {}
    if existing.get("certs"):
        return existing
    settings = _cert_settings(cfg)
    if settings.get("management_mode") != "adopted_existing":
        return existing or {"certs": []}
    inventory = inventory or _cert_inventory_from_reconcile(cfg, reconcile=reconcile)
    certs = inventory.get("certs", [])
    if not certs:
        return {
            "certs": [],
            "issued_at": "external existing",
            "source": "external_existing",
        }
    first = certs[0]
    return {
        "certs": [
            {
                "domain": f"*.{settings.get('base_domain', '')}" if settings.get("wildcard", True) else settings.get("base_domain", ""),
                "issuer": first.get("issuer", ""),
                "expires": first.get("expires", ""),
                "status": "externally managed",
                "source": "external_existing",
                "renewal_owner": settings.get("renewal_owner") or "external",
            }
        ],
        "issued_at": "external existing",
        "source": "external_existing",
        "summary": inventory.get("summary", {}),
    }


def _verify_host_header(target):
    """Probe Host-header DNS-rebind behavior for appliances such as pfSense."""
    host = target.get("hostname") or target.get("ip")
    connect_host = target.get("ip") or target.get("hostname")
    port = int(target.get("port", 443) or 443)
    ctx = ssl._create_unverified_context()
    request = f"GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
    try:
        with socket.create_connection((connect_host, port), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                ssock.sendall(request)
                body = ssock.recv(4096).decode("utf-8", "replace")
        blocked = "dns rebind" in body.lower() or "rebind" in body.lower()
        return {"ok": not blocked, "blocked": blocked, "snippet": body[:160]}
    except Exception as e:
        return {"ok": False, "blocked": False, "error": str(e)}


def _zone_candidates(base_domain):
    parts = [p for p in (base_domain or "").split(".") if p]
    return [".".join(parts[i:]) for i in range(0, max(len(parts) - 1, 0))]


def _cloudflare_request(token_path, path, method="GET", payload=None):
    token = _read_file(token_path)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4{path}",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _discover_cloudflare_zone_id(token_path, base_domain):
    """Discover the Cloudflare zone id from the base domain and token."""
    errors = []
    for candidate in _zone_candidates(base_domain):
        try:
            data = _cloudflare_request(token_path, f"/zones?name={candidate}")
        except Exception as e:
            errors.append(f"{candidate}: {e}")
            continue
        if data.get("success") and data.get("result"):
            zone = data["result"][0]
            return {"zone_id": zone.get("id", ""), "zone_name": zone.get("name", candidate), "errors": errors}
    return {"zone_id": "", "zone_name": "", "errors": errors}


def _cloudflare_find_dns_record(settings, record):
    zone_id = settings.get("cloudflare_zone_id", "")
    token_path = settings.get("dns_token_path", "")
    path = f"/zones/{zone_id}/dns_records?type={record['type']}&name={record['hostname']}"
    data = _cloudflare_request(token_path, path)
    if data.get("success") and data.get("result"):
        return data["result"][0]
    return None


def _cloudflare_upsert_dns_record(settings, record):
    zone_id = settings.get("cloudflare_zone_id", "")
    token_path = settings.get("dns_token_path", "")
    existing = _cloudflare_find_dns_record(settings, record)
    payload = {
        "type": record["type"],
        "name": record["hostname"],
        "content": record["value"],
        "ttl": 1,
        "proxied": bool(record.get("proxied", False)),
    }
    if existing:
        path = f"/zones/{zone_id}/dns_records/{existing['id']}"
        method = "PUT"
        action = "updated"
    else:
        path = f"/zones/{zone_id}/dns_records"
        method = "POST"
        action = "created"
    data = _cloudflare_request(token_path, path, method=method, payload=payload)
    if not data.get("success"):
        raise RuntimeError(f"Cloudflare DNS record {action} failed for {record['hostname']}: {data}")
    return {"action": action, "hostname": record["hostname"], "value": record["value"]}


def _stage_cloudflare_token(cfg, source_path, dest_path=""):
    """Copy a Cloudflare token to a managed path with 0600 permissions."""
    if not source_path:
        raise RuntimeError("--cloudflare-token-file is required")
    source_path = os.path.expanduser(source_path)
    if not os.path.isfile(source_path):
        raise RuntimeError(f"Cloudflare token file not found: {source_path}")
    candidates = []
    if dest_path:
        candidates.append(os.path.expanduser(dest_path))
    else:
        candidates.extend(
            [
                "/etc/freq/credentials/cloudflare_dns_token",
                os.path.join(cfg.conf_dir, "secrets", "cloudflare_dns_token"),
            ]
        )
    last_error = ""
    for candidate in candidates:
        try:
            os.makedirs(os.path.dirname(candidate), mode=0o700, exist_ok=True)
            shutil.copyfile(source_path, candidate)
            os.chmod(candidate, 0o600)
            return candidate
        except OSError as e:
            last_error = str(e)
    raise RuntimeError(f"could not stage Cloudflare token: {last_error}")


def _cloudflare_token_candidates(cfg, dest_path=""):
    if dest_path:
        return [os.path.expanduser(dest_path)]
    conf_dir = getattr(cfg, "conf_dir", "") or ""
    candidates = ["/etc/freq/credentials/cloudflare_dns_token"]
    if conf_dir:
        candidates.append(os.path.join(conf_dir, "secrets", "cloudflare_dns_token"))
    return candidates


def _stage_cloudflare_token_value(cfg, token, dest_path=""):
    """Write a pasted Cloudflare token into a managed secret file."""
    token = str(token or "").strip()
    if not token:
        raise RuntimeError("Cloudflare token is required")
    if len(token) < 8:
        raise RuntimeError("Cloudflare token is too short")
    last_error = ""
    for candidate in _cloudflare_token_candidates(cfg, dest_path):
        try:
            os.makedirs(os.path.dirname(candidate), mode=0o700, exist_ok=True)
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(token + "\n")
            os.chmod(candidate, 0o600)
            return candidate
        except OSError as e:
            last_error = str(e)
    raise RuntimeError(f"could not stage Cloudflare token: {last_error}")


def _cloudflare_token_status(cfg, settings=None):
    """Return token readiness metadata without exposing the token value."""
    settings = settings or _cert_settings(cfg)
    path = str(settings.get("dns_token_path") or "").strip()
    if not path:
        candidates = _cloudflare_token_candidates(cfg)
        path = next((p for p in candidates if os.path.isfile(os.path.expanduser(p))), "")
    expanded = os.path.expanduser(path) if path else ""
    exists = bool(expanded and os.path.isfile(expanded))
    readable = bool(exists and os.access(expanded, os.R_OK))
    mode = ""
    if exists:
        try:
            mode = oct(os.stat(expanded).st_mode & 0o777)
        except OSError:
            mode = ""
    return {
        "provider": settings.get("dns_provider") or "cloudflare",
        "configured": bool(settings.get("dns_token_path")),
        "stored": exists,
        "ready": bool(readable),
        "path": expanded,
        "secret_ref": "cloudflare_dns_token" if expanded else "",
        "mode": mode,
        "value_exposed": False,
        "store_endpoint": "/api/cert/lifecycle/cloudflare-token",
    }


def _infer_cert_targets(cfg, base_domain):
    """Infer default certificate targets from existing pve-freq inventory."""
    targets = []
    seen = set()

    def add_target(target):
        key = (target.get("hostname") or target.get("label") or "").lower()
        if not key or key in seen:
            return
        seen.add(key)
        targets.append(target)

    cert_settings = _cert_settings(cfg)
    reverse_proxy_host = str(cert_settings.get("reverse_proxy_host", "") or "").strip()
    dashboard_origin_host = str(cert_settings.get("dashboard_origin_host", "") or "").strip()
    dashboard_origin_port = int(cert_settings.get("dashboard_origin_port") or getattr(cfg, "dashboard_port", 8888) or 8888)
    upstream_scheme = str(cert_settings.get("reverse_proxy_upstream_scheme") or "http").strip().lower()
    upstream_tls_verify = _as_bool(
        cert_settings.get("reverse_proxy_upstream_tls_verify"),
        upstream_scheme == "https",
    )
    if reverse_proxy_host:
        add_target(
            {
                "label": "pve-freq-dashboard",
                "service_name": "pve-freq",
                "target_type": "freq_dashboard",
                "hostname": f"pve-freq.{base_domain}",
                "ip": reverse_proxy_host,
                "port": 443,
                "origin_ip": dashboard_origin_host,
                "origin_port": dashboard_origin_port,
                "origin_scheme": upstream_scheme,
                "origin_tls_verify": upstream_tls_verify,
                "mode": "behind_proxy",
                "deploy_driver": "reverse_proxy",
                "cert_source": "wildcard",
                "restart_policy": "external_proxy_reload",
                "verify_hostname": True,
                "reverse_proxy_host": reverse_proxy_host,
                "scope": "include",
            }
        )

        for vm in (getattr(cfg, "container_vms", {}) or {}).values():
            vm_label = getattr(vm, "label", "") or ""
            for container in (getattr(vm, "containers", {}) or {}).values():
                route = _public_container_route_name(getattr(container, "name", ""), vm_label)
                if not route:
                    continue
                add_target(
                    {
                        "label": route,
                        "service_name": route,
                        "target_type": "web_app",
                        "hostname": f"{route}.{base_domain}",
                        "ip": reverse_proxy_host,
                        "port": 443,
                        "origin_ip": getattr(vm, "ip", ""),
                        "origin_port": int(getattr(container, "port", 0) or 0),
                        "origin_scheme": "http",
                        "origin_tls_verify": False,
                        "mode": "behind_proxy",
                        "deploy_driver": "reverse_proxy",
                        "cert_source": "wildcard",
                        "restart_policy": "external_proxy_reload",
                        "verify_hostname": True,
                        "reverse_proxy_host": reverse_proxy_host,
                        "scope": "include",
                    }
                )

    pve_nodes = list(getattr(cfg, "pve_nodes", []) or [])
    pve_names = list(getattr(cfg, "pve_node_names", []) or [])
    for idx, ip in enumerate(pve_nodes):
        name = pve_names[idx] if idx < len(pve_names) and pve_names[idx] else f"pve{idx + 1:02d}"
        add_target(
            {
                "label": name,
                "target_type": "proxmox_ve_node",
                "hostname": f"{name}.{base_domain}",
                "ip": ip,
                "port": 8006,
                "deploy_driver": "proxmox_pvenode",
                "cert_source": "wildcard",
                "restart_policy": "pveproxy_restart",
                "verify_hostname": True,
            }
        )
    if getattr(cfg, "truenas_ip", ""):
        add_target(
            {
                "label": "truenas",
                "target_type": "truenas_scale",
                "hostname": f"truenas.{base_domain}",
                "ip": cfg.truenas_ip,
                "port": 443,
                "deploy_driver": "truenas_api",
                "cert_source": "wildcard",
                "restart_policy": "ui_restart",
                "verify_hostname": True,
            }
        )
    if getattr(cfg, "pfsense_ip", ""):
        add_target(
            {
                "label": "pfsense",
                "target_type": "pfsense",
                "hostname": f"pfsense.{base_domain}",
                "ip": cfg.pfsense_ip,
                "port": 4443,
                "deploy_driver": "pfsense_config",
                "cert_source": "wildcard",
                "restart_policy": "webgui_unbound_restart",
                "verify_hostname": True,
                "host_header_check": True,
                "resolver_private_domain": True,
            }
        )
    for host in getattr(cfg, "hosts", []) or []:
        htype = str(getattr(host, "htype", "") or "").lower()
        if htype not in ("idrac", "switch"):
            continue
        ip = str(getattr(host, "ip", "") or "").strip()
        label = _slug(getattr(host, "label", "") or htype)
        if not label:
            continue
        hostname = f"{label}.{base_domain}" if base_domain else label
        service_tag = ""
        identity_source = ""
        if htype == "idrac":
            label, hostname, service_tag, identity_source = _cert_device_identity(
                cfg,
                host,
                htype,
                ip,
                label,
                getattr(host, "hostname", "") or hostname,
                base_domain,
            )
        add_target(
            {
                "label": label,
                "target_type": htype,
                "hostname": hostname,
                "ip": ip,
                "port": 443,
                "deploy_driver": "idrac_racadm" if htype == "idrac" else "switch_ios",
                "cert_source": "wildcard_rsa",
                "restart_policy": "external_or_legacy_driver",
                "verify_hostname": bool(hostname),
                "service_tag": service_tag,
                "identity_source": identity_source,
                "scope": "include",
            }
        )
    return targets


def _strip_cert_tables(toml_text):
    """Remove existing cert lifecycle tables from freq.toml."""
    lines = toml_text.splitlines()
    kept = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if stripped == "[certificates]" or stripped == "[[cert_target]]":
            skip = True
            continue
        if skip and stripped.startswith("[") and stripped not in ("[certificates]", "[[cert_target]]"):
            skip = False
        if not skip:
            kept.append(line)
    return "\n".join(kept).rstrip() + "\n"


def _toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_cert_config_block(settings, targets):
    lines = [
        "",
        "# BEGIN FREQ MANAGED CERTIFICATES",
        "[certificates]",
    ]
    for key in (
        "base_domain",
        "wildcard",
        "management_mode",
        "issuer",
        "acme_home",
        "acme_auto_install",
        "acme_keylength",
        "cert_fullchain_path",
        "cert_key_path",
        "dns_provider",
        "dns_token_path",
        "cloudflare_zone_id",
        "record_strategy",
        "reverse_proxy_host",
        "reverse_proxy_upstream_scheme",
        "reverse_proxy_upstream_tls_verify",
        "dashboard_hostname",
        "dashboard_origin_host",
        "dashboard_origin_port",
        "renewal_owner",
    ):
        if key in settings and settings[key] != "":
            lines.append(f"{key} = {_toml_value(settings[key])}")
    for target in targets:
        lines.extend(["", "[[cert_target]]"])
        for key in (
            "label",
            "service_name",
            "target_type",
            "hostname",
            "subdomain",
            "ip",
            "port",
            "mode",
            "origin_ip",
            "origin_port",
            "origin_scheme",
            "origin_tls_verify",
            "deploy_driver",
            "cert_source",
            "restart_policy",
            "verify_hostname",
            "host_header_check",
            "resolver_private_domain",
            "credential_ref",
            "scope",
            "hostname_override",
            "reverse_proxy_host",
            "api_key_path",
            "ssh_user",
        ):
            value = target.get(key)
            if value not in (None, ""):
                lines.append(f"{key} = {_toml_value(value)}")
    lines.append("# END FREQ MANAGED CERTIFICATES")
    return "\n".join(lines) + "\n"


def _write_cert_config_block(cfg, settings, targets, replace=False):
    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    text = ""
    if os.path.isfile(toml_path):
        with open(toml_path) as f:
            text = f.read()
    if ("[certificates]" in text or "[[cert_target]]" in text) and not replace:
        raise RuntimeError("freq.toml already has certificate config; rerun with --replace to overwrite cert tables")
    stripped = _strip_cert_tables(text) if replace else text.rstrip() + "\n"
    block = _render_cert_config_block(settings, targets)
    with open(toml_path, "w") as f:
        f.write(stripped.rstrip() + "\n" + block)
    return toml_path


# ---------------------------------------------------------------------------
# Commands — Certificate Inspection
# ---------------------------------------------------------------------------


def cmd_cert_inspect(cfg: FreqConfig, pack, args) -> int:
    """Inspect TLS certificate on a host:port."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq cert inspect <host:port>")
        return 1

    # Parse host:port
    if ":" in target:
        host, port_str = target.rsplit(":", 1)
        port = int(port_str)
    else:
        host = target
        port = 443

    fmt.header(f"Certificate: {host}:{port}", breadcrumb="FREQ > Cert")
    fmt.blank()

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert(binary_form=False)
    except Exception as e:
        fmt.error(f"Could not connect to {host}:{port}: {e}")
        return 1

    if not cert:
        # Binary cert only — parse what we can
        fmt.warn("Certificate retrieved but no parsed data (self-signed or invalid chain)")
        fmt.footer()
        return 1

    # Display cert details
    subject = dict(x[0] for x in cert.get("subject", []))
    issuer = dict(x[0] for x in cert.get("issuer", []))
    not_before = cert.get("notBefore", "")
    not_after = cert.get("notAfter", "")
    sans = [entry[1] for entry in cert.get("subjectAltName", [])]

    fmt.line(f"{fmt.C.BOLD}Subject:{fmt.C.RESET}     {subject.get('commonName', '?')}")
    fmt.line(f"{fmt.C.BOLD}Issuer:{fmt.C.RESET}      {issuer.get('organizationName', issuer.get('commonName', '?'))}")
    fmt.line(f"{fmt.C.BOLD}Valid From:{fmt.C.RESET}   {not_before}")
    fmt.line(f"{fmt.C.BOLD}Valid Until:{fmt.C.RESET}  {not_after}")
    if sans:
        fmt.line(f"{fmt.C.BOLD}SANs:{fmt.C.RESET}        {', '.join(sans[:5])}")
        if len(sans) > 5:
            fmt.line(f"              ... and {len(sans) - 5} more")
    fmt.line(f"{fmt.C.BOLD}Serial:{fmt.C.RESET}      {cert.get('serialNumber', '?')}")

    # Check expiry
    try:
        from datetime import datetime

        expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
        days_left = (expiry - datetime.utcnow()).days
        if days_left < 0:
            fmt.blank()
            fmt.error(f"EXPIRED {abs(days_left)} days ago!")
        elif days_left < 30:
            fmt.blank()
            fmt.warn(f"Expires in {days_left} days")
        else:
            fmt.blank()
            fmt.success(f"{days_left} days until expiry")
    except (ValueError, ImportError):
        pass

    fmt.blank()
    logger.info("cert_inspect", target=f"{host}:{port}")
    fmt.footer()
    return 0


def cmd_cert_fleet_check(cfg: FreqConfig, pack, args) -> int:
    """Check TLS certificates across all fleet hosts."""
    fmt.header("Fleet Certificate Check", breadcrumb="FREQ > Cert")
    fmt.blank()

    # Check common ports on all hosts
    ports = [443, 8443, 8006, 9090]
    results = []

    for h in cfg.hosts:
        for port in ports:
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with socket.create_connection((h.ip, port), timeout=2) as sock:
                    with ctx.wrap_socket(sock, server_hostname=h.ip) as ssock:
                        cert = ssock.getpeercert(binary_form=False)
                        if cert:
                            not_after = cert.get("notAfter", "")
                            subject = dict(x[0] for x in cert.get("subject", []))
                            cn = subject.get("commonName", "?")
                            results.append(
                                {
                                    "host": h.label,
                                    "port": port,
                                    "cn": cn,
                                    "expires": not_after,
                                }
                            )
            except (ConnectionRefusedError, socket.timeout, OSError):
                continue

    if results:
        fmt.table_header(("Host", 14), ("Port", 6), ("CN", 24), ("Expires", 24))
        for r in results:
            fmt.table_row(
                (r["host"], 14),
                (str(r["port"]), 6),
                (r["cn"], 24),
                (r["expires"], 24),
            )
        fmt.blank()
        fmt.info(f"{len(results)} TLS endpoint(s) found")
    else:
        fmt.warn("No TLS endpoints found on standard ports")

    fmt.footer()
    return 0


def cmd_cert_acme_status(cfg: FreqConfig, pack, args) -> int:
    """Show ACME (Let's Encrypt) certificate status."""
    fmt.header("ACME Certificates", breadcrumb="FREQ > Cert > ACME")
    fmt.blank()

    # Check if certbot is available
    try:
        r = subprocess.run(["certbot", "certificates"], capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
        else:
            fmt.warn("certbot returned an error (may need sudo)")
            if r.stderr:
                fmt.line(f"  {fmt.C.DIM}{r.stderr[:200]}{fmt.C.RESET}")
    except FileNotFoundError:
        fmt.warn("certbot not installed")
        fmt.info("Install certbot using your package manager (apt, dnf, pacman, etc.)")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_cert_issued_list(cfg: FreqConfig, pack, args) -> int:
    """List tracked issued certificates."""
    data = _load_issued(cfg)
    certs = data.get("certs", [])

    fmt.header("Issued Certificates", breadcrumb="FREQ > Cert")
    fmt.blank()

    if not certs:
        fmt.info("No tracked certificates")
        fmt.footer()
        return 0

    fmt.table_header(("Domain", 24), ("Type", 8), ("Issued", 12), ("Expires", 12))
    for c in certs:
        fmt.table_row(
            (c.get("domain", ""), 24),
            (c.get("type", ""), 8),
            (c.get("issued", ""), 12),
            (c.get("expires", ""), 12),
        )

    fmt.blank()
    fmt.info(f"{len(certs)} certificate(s)")
    fmt.footer()
    return 0


def cmd_cert_plan(cfg: FreqConfig, pack, args) -> int:
    """Show the configured certificate lifecycle plan without mutating anything."""
    plan = _build_lifecycle_plan(cfg)

    if getattr(args, "json", False):
        print(json.dumps(plan, indent=2))
        return 0 if not any(w.startswith("missing") for w in plan["warnings"]) else 1

    settings = plan["settings"]
    fmt.header("Certificate Lifecycle Plan", breadcrumb="FREQ > Cert > Plan")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Base domain:{fmt.C.RESET}     {settings.get('base_domain') or '(not configured)'}")
    fmt.line(f"{fmt.C.BOLD}Wildcard:{fmt.C.RESET}        {plan.get('wildcard_name') or '(not configured)'}")
    fmt.line(f"{fmt.C.BOLD}Issuer:{fmt.C.RESET}          {settings.get('issuer')}")
    fmt.line(f"{fmt.C.BOLD}DNS provider:{fmt.C.RESET}    {settings.get('dns_provider') or '(not configured)'}")
    fmt.line(f"{fmt.C.BOLD}Record mode:{fmt.C.RESET}     {settings.get('record_strategy')}")
    if settings.get("dns_token_path"):
        fmt.line(f"{fmt.C.BOLD}DNS token path:{fmt.C.RESET} {settings.get('dns_token_path')}")
    fmt.blank()

    targets = plan["targets"]
    if targets:
        fmt.table_header(("LABEL", 16), ("TYPE", 18), ("HOSTNAME", 32), ("IP", 15), ("DRIVER", 18))
        for target in targets:
            fmt.table_row(
                (target["label"], 16),
                (target["target_type"], 18),
                (target["hostname"], 32),
                (target["ip"], 15),
                (target["deploy_driver"], 18),
            )
    else:
        fmt.warn("No certificate deployment targets configured")

    if plan["warnings"]:
        fmt.blank()
        fmt.divider("Warnings")
        for warning in plan["warnings"]:
            fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN} {warning}{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0 if not any(w.startswith("missing") for w in plan["warnings"]) else 1


def cmd_cert_bootstrap(cfg: FreqConfig, pack, args) -> int:
    """Create cert lifecycle config from one Cloudflare token file."""
    base_domain = getattr(args, "base_domain", "") or ""
    token_file = getattr(args, "cloudflare_token_file", "") or ""
    replace = bool(getattr(args, "replace", False))
    dry_run = bool(getattr(args, "dry_run", False))
    json_output = bool(getattr(args, "json", False))

    if not base_domain:
        fmt.error("Usage: freq cert bootstrap --base-domain DOMAIN --cloudflare-token-file PATH")
        return 1
    if not token_file:
        fmt.error("--cloudflare-token-file is required; the token value must stay in a file, not the shell history")
        return 1
    if not dry_run and not getattr(args, "yes", False):
        fmt.error("Certificate bootstrap writes config and stages a credential path; rerun with --yes or --dry-run")
        return 1

    source_token_path = os.path.expanduser(token_file)
    if not os.path.isfile(source_token_path):
        fmt.error(f"Cloudflare token file not found: {source_token_path}")
        return 1

    zone = _discover_cloudflare_zone_id(source_token_path, base_domain)
    if not zone.get("zone_id"):
        if json_output:
            print(json.dumps({"ok": False, "error": "could not discover Cloudflare zone", "details": zone}, indent=2))
        else:
            fmt.error("Could not discover Cloudflare zone id from token and base domain")
            for error in zone.get("errors", [])[:3]:
                fmt.line(f"  {fmt.C.DIM}{error}{fmt.C.RESET}")
        return 1

    try:
        token_path = source_token_path if dry_run else _stage_cloudflare_token(
            cfg, source_token_path, getattr(args, "token_dest", "") or ""
        )
    except Exception as e:
        fmt.error(str(e))
        return 1

    raw_settings = dict(DEFAULT_CERT_SETTINGS)
    raw_settings.update(
        {
            "base_domain": base_domain,
            "wildcard": True,
            "issuer": "acme.sh",
            "dns_provider": "cloudflare",
            "dns_token_path": token_path,
            "cloudflare_zone_id": zone["zone_id"],
            "record_strategy": "public-private-a",
        }
    )
    previous_certificates = getattr(cfg, "certificates", {})
    try:
        cfg.certificates = raw_settings
        settings = _cert_settings(cfg)
    finally:
        cfg.certificates = previous_certificates
    targets = _infer_cert_targets(cfg, base_domain)
    result = {
        "ok": True,
        "dry_run": dry_run,
        "zone": zone,
        "settings": settings,
        "targets": targets,
        "config_path": os.path.join(cfg.conf_dir, "freq.toml"),
    }

    if dry_run:
        result["config_block"] = _render_cert_config_block(settings, targets)
    else:
        try:
            result["config_path"] = _write_cert_config_block(cfg, settings, targets, replace=replace)
        except Exception as e:
            fmt.error(str(e))
            return 1

    if json_output:
        print(json.dumps(result, indent=2))
        return 0

    fmt.header("Certificate Bootstrap", breadcrumb="FREQ > Cert > Bootstrap")
    fmt.blank()
    fmt.step_ok(f"Cloudflare zone: {zone.get('zone_name')} ({zone.get('zone_id')})")
    fmt.step_ok(f"Token path: {token_path}")
    fmt.step_ok(f"Inferred targets: {len(targets)}")
    if dry_run:
        fmt.info("Dry run only; no config or credential file was written")
    else:
        fmt.step_ok(f"Updated {result['config_path']}")
    fmt.blank()
    fmt.footer()
    return 0


def cmd_cert_issue(cfg: FreqConfig, pack, args) -> int:
    """Issue the configured wildcard certificate via ACME DNS-01."""
    settings = _cert_settings(cfg)
    missing = [
        key
        for key in ("base_domain", "dns_provider", "dns_token_path")
        if not settings.get(key)
    ]
    if missing:
        error = "missing certificate settings: " + ", ".join(missing) + "; run freq cert bootstrap first"
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": error}, indent=2))
        else:
            fmt.error(error)
        return 1
    command = _build_acme_issue_command(settings)
    install_command = _build_acme_install_command(settings)
    dry_run = bool(getattr(args, "dry_run", False))
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "command": command,
                    "install_command": install_command,
                    "dry_run": dry_run,
                    "acme_available": _acme_available(settings),
                    "acme_install_planned": not _acme_available(settings),
                    "source_paths": _source_paths(settings),
                },
                indent=2,
            )
        )
        return 0
    fmt.header("Issue Certificate", breadcrumb="FREQ > Cert > Issue")
    fmt.blank()
    if not _acme_available(settings):
        fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN} acme.sh not installed; pve-freq will install it under {settings.get('acme_home')}{fmt.C.RESET}")
    fmt.line("  " + " ".join(shlex.quote(part) for part in command))
    if dry_run:
        fmt.info("Dry run only; ACME command not executed")
        fmt.footer()
        return 0
    if not getattr(args, "yes", False):
        fmt.error("Issuing certificates requires --yes")
        return 1
    if not _acme_available(settings):
        if not _as_bool(settings.get("acme_auto_install"), True):
            fmt.error("acme.sh is not installed and acme_auto_install is false")
            return 1
        install = _install_acme_sh(settings)
        if install.returncode != 0:
            fmt.error((install.stderr or install.stdout or "acme.sh install failed")[:800])
            return install.returncode or 1
        command = _build_acme_issue_command(settings)
        install_command = _build_acme_install_command(settings)
    result = _run_acme_command(settings, command)
    if result.returncode != 0:
        fmt.error((result.stderr or result.stdout or "acme.sh failed")[:800])
        return result.returncode or 1
    install_result = _run_acme_command(settings, install_command)
    if install_result.returncode != 0:
        fmt.error((install_result.stderr or install_result.stdout or "acme.sh install-cert failed")[:800])
        return install_result.returncode or 1
    fmt.step_ok("ACME issue completed")
    fmt.step_ok("Installed certificate to persistent managed paths")
    fmt.footer()
    if getattr(args, "deploy", False):
        args.target = ""
        return cmd_cert_deploy(cfg, pack, args)
    return 0


def cmd_cert_renew(cfg: FreqConfig, pack, args) -> int:
    """Renew the configured wildcard certificate via ACME."""
    settings = _cert_settings(cfg)
    missing = [
        key
        for key in ("base_domain", "dns_provider", "dns_token_path")
        if not settings.get(key)
    ]
    if missing:
        error = "missing certificate settings: " + ", ".join(missing) + "; run freq cert bootstrap first"
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": error}, indent=2))
        else:
            fmt.error(error)
        return 1
    command = _build_acme_renew_command(settings)
    install_command = _build_acme_install_command(settings)
    dry_run = bool(getattr(args, "dry_run", False))
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "command": command,
                    "install_command": install_command,
                    "dry_run": dry_run,
                    "acme_available": _acme_available(settings),
                    "acme_install_planned": not _acme_available(settings),
                    "source_paths": _source_paths(settings),
                },
                indent=2,
            )
        )
        return 0
    fmt.header("Renew Certificate", breadcrumb="FREQ > Cert > Renew")
    fmt.blank()
    if not _acme_available(settings):
        fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN} acme.sh not installed; pve-freq will install it under {settings.get('acme_home')}{fmt.C.RESET}")
    fmt.line("  " + " ".join(shlex.quote(part) for part in command))
    if dry_run:
        fmt.info("Dry run only; ACME command not executed")
        fmt.footer()
        return 0
    if not getattr(args, "yes", False):
        fmt.error("Renewing certificates requires --yes")
        return 1
    if not _acme_available(settings):
        if not _as_bool(settings.get("acme_auto_install"), True):
            fmt.error("acme.sh is not installed and acme_auto_install is false")
            return 1
        install = _install_acme_sh(settings)
        if install.returncode != 0:
            fmt.error((install.stderr or install.stdout or "acme.sh install failed")[:800])
            return install.returncode or 1
        command = _build_acme_renew_command(settings)
        install_command = _build_acme_install_command(settings)
    result = _run_acme_command(settings, command)
    if result.returncode != 0:
        fmt.error((result.stderr or result.stdout or "acme.sh failed")[:800])
        return result.returncode or 1
    install_result = _run_acme_command(settings, install_command)
    if install_result.returncode != 0:
        fmt.error((install_result.stderr or install_result.stdout or "acme.sh install-cert failed")[:800])
        return install_result.returncode or 1
    fmt.step_ok("ACME renew completed")
    fmt.step_ok("Installed certificate to persistent managed paths")
    fmt.footer()
    if getattr(args, "deploy", False):
        args.target = ""
        return cmd_cert_deploy(cfg, pack, args)
    return 0


def cmd_cert_deploy(cfg: FreqConfig, pack, args) -> int:
    """Deploy the configured certificate to selected targets."""
    plan = _build_lifecycle_plan(cfg)
    targets = _select_targets(plan, getattr(args, "target", ""))
    dry_run = bool(getattr(args, "dry_run", False))
    if not targets:
        fmt.error("No matching certificate targets")
        return 1
    if not dry_run and not getattr(args, "yes", False):
        fmt.error("Certificate deployment mutates appliances; rerun with --yes or --dry-run")
        return 1

    results = []
    for target in targets:
        target_result = {"target": target["label"], "steps": []}
        for step in target.get("deploy_steps", []):
            step_view = {k: v for k, v in step.items() if k not in ("command",)}
            if step.get("command"):
                step_view["command"] = step["command"]
            if dry_run:
                step_view["returncode"] = None
            else:
                execution = _execute_deploy_step(cfg, target, step)
                step_view.update(execution)
            target_result["steps"].append(step_view)
            if not dry_run and step_view.get("returncode") != 0:
                break
        results.append(target_result)

    if getattr(args, "json", False):
        print(json.dumps({"dry_run": dry_run, "results": results}, indent=2))
    else:
        fmt.header("Deploy Certificates", breadcrumb="FREQ > Cert > Deploy")
        fmt.blank()
        for result in results:
            fmt.line(f"{fmt.C.BOLD}{result['target']}{fmt.C.RESET}")
            for step in result["steps"]:
                status = "planned" if dry_run else ("ok" if step.get("returncode") == 0 else "failed")
                fmt.line(f"  {step.get('kind', '?')}: {status}")
                if step.get("stderr") and step.get("returncode"):
                    fmt.line(f"    {fmt.C.RED}{step['stderr'][:200]}{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()

    failed = any(step.get("returncode") not in (0, None) for result in results for step in result["steps"])
    return 1 if failed else 0


def cmd_cert_dns_sync(cfg: FreqConfig, pack, args) -> int:
    """Create/update Cloudflare DNS records for configured certificate targets."""
    plan = _build_lifecycle_plan(cfg)
    settings = plan["settings"]
    records = plan["dns_records"]
    dry_run = bool(getattr(args, "dry_run", False))
    if not records:
        fmt.error("No DNS records to sync; run freq cert bootstrap or add [[cert_target]] entries")
        return 1
    missing = [
        key
        for key in ("dns_token_path", "cloudflare_zone_id")
        if not settings.get(key)
    ]
    if missing:
        error = "missing Cloudflare DNS settings: " + ", ".join(missing)
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": error}, indent=2))
        else:
            fmt.error(error)
        return 1
    if settings.get("dns_provider") != "cloudflare":
        fmt.error("cert dns-sync currently supports dns_provider=cloudflare")
        return 1
    if not dry_run and not getattr(args, "yes", False):
        fmt.error("DNS sync mutates Cloudflare records; rerun with --yes or --dry-run")
        return 1

    results = []
    for record in records:
        if dry_run:
            results.append({"action": "planned", "hostname": record["hostname"], "value": record["value"]})
            continue
        try:
            results.append(_cloudflare_upsert_dns_record(settings, record))
        except Exception as e:
            results.append({"action": "failed", "hostname": record["hostname"], "value": record["value"], "error": str(e)})

    if getattr(args, "json", False):
        print(json.dumps({"dry_run": dry_run, "results": results}, indent=2))
    else:
        fmt.header("Sync Certificate DNS", breadcrumb="FREQ > Cert > DNS")
        fmt.blank()
        for result in results:
            status = result["action"]
            color = fmt.C.GREEN if status in ("planned", "created", "updated") else fmt.C.RED
            fmt.line(f"  {color}{status:8}{fmt.C.RESET} {result['hostname']} -> {result['value']}")
            if result.get("error"):
                fmt.line(f"    {fmt.C.RED}{result['error'][:200]}{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()

    return 1 if any(r.get("action") == "failed" for r in results) else 0


def cmd_cert_verify(cfg: FreqConfig, pack, args) -> int:
    """Verify configured certificate targets over live TLS."""
    plan = _build_lifecycle_plan(cfg)
    targets = _select_targets(plan, getattr(args, "target", ""))
    if not targets:
        fmt.error("No matching certificate targets")
        return 1
    results = []
    for target in targets:
        tls = _verify_tls_target(target)
        result = {"target": target["label"], "tls": tls}
        if target.get("host_header_check"):
            result["host_header"] = _verify_host_header(target)
        results.append(result)

    if getattr(args, "json", False):
        print(json.dumps({"results": results}, indent=2))
    else:
        fmt.header("Verify Certificates", breadcrumb="FREQ > Cert > Verify")
        fmt.blank()
        for result in results:
            tls = result["tls"]
            status = fmt.badge("ok") if tls.get("ok") else fmt.badge("fail")
            fmt.line(f"{status} {result['target']} {tls.get('hostname')}:{tls.get('port')}")
            if tls.get("error"):
                fmt.line(f"  {fmt.C.RED}{tls['error']}{fmt.C.RESET}")
            if result.get("host_header"):
                hh = result["host_header"]
                hh_status = fmt.badge("ok") if hh.get("ok") else fmt.badge("fail")
                fmt.line(f"  Host-header rebind check: {hh_status}")
        fmt.blank()
        fmt.footer()
    return 0 if all(r["tls"].get("ok") and r.get("host_header", {"ok": True}).get("ok") for r in results) else 1
