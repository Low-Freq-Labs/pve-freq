"""Certificate lifecycle management for FREQ — ACME, CA, fleet deployment.

Domain: freq cert <acme|ca|inspect|deploy> <action>
What: Issue certificates via ACME (Let's Encrypt), manage private CA,
      inspect certs on endpoints, deploy certs to fleet hosts.
      Extends existing cert.py scan/list/check with write operations.
Replaces: Manual certbot runs, step-ca CLI, SCP cert files, cert tracking
Architecture:
    - ACME: shells to certbot for issuance, parses output
    - CA: shells to step-ca for private CA operations
    - Deploy: SCP via ssh.py to push certs to target hosts
    - Inventory: extends conf/certs/ with issued cert tracking
Design decisions:
    - Shell to certbot/step-ca, not implement ACME protocol. Zero deps.
    - Track issued certs in JSON for renewal/expiry monitoring.
    - Deploy is SCP + service reload via SSH — works everywhere.
"""

import json
import hashlib
import os
import shlex
import shutil
import ssl
import socket
import subprocess
import tempfile
import time
import urllib.request

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


# ---------------------------------------------------------------------------
# Data Storage
# ---------------------------------------------------------------------------

CERT_DIR = "certs"

DEFAULT_CERT_SETTINGS = {
    "base_domain": "",
    "wildcard": True,
    "management_mode": "managed",
    "issuer": "acme.sh",
    "acme_home": "~/.acme.sh",
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
    "renewal_owner": "",
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


def _cert_targets(cfg):
    """Return normalized certificate deployment targets."""
    targets = []
    for idx, raw in enumerate(getattr(cfg, "cert_targets", []) or []):
        if not isinstance(raw, dict):
            continue
        hostname = str(raw.get("hostname", "")).strip()
        label = str(raw.get("label") or hostname or f"target-{idx + 1}").strip()
        target_type = str(raw.get("target_type") or raw.get("type") or "unknown").strip()
        driver = str(raw.get("deploy_driver") or target_type).strip()
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
                "credential_ref": str(raw.get("credential_ref", "")).strip(),
                "scope": str(raw.get("scope", "")).strip(),
                "hostname_override": str(raw.get("hostname_override", "")).strip(),
                "ssh_user": str(raw.get("ssh_user", "")).strip(),
                "api_key_path": str(raw.get("api_key_path", "")).strip(),
                "cert_fullchain_path": str(raw.get("cert_fullchain_path", "")).strip(),
                "cert_key_path": str(raw.get("cert_key_path", "")).strip(),
                "remote_cert_dir": str(raw.get("remote_cert_dir", "")).strip(),
                "restart_policy": str(raw.get("restart_policy", "")).strip(),
                "verify_hostname": _as_bool(raw.get("verify_hostname"), True),
                "host_header_check": _as_bool(raw.get("host_header_check"), driver == "pfsense_config"),
                "resolver_private_domain": _as_bool(raw.get("resolver_private_domain"), driver == "pfsense_config"),
            }
        )
    return targets


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
    if not fullchain or not key:
        acme_home = os.path.expanduser(settings.get("acme_home") or "~/.acme.sh")
        if base_domain:
            acme_dir = os.path.join(acme_home, f"{base_domain}_ecc")
            fullchain = fullchain or os.path.join(acme_dir, "fullchain.cer")
            key = key or os.path.join(acme_dir, f"{base_domain}.key")
    return {
        "fullchain": os.path.expanduser(fullchain) if fullchain else "",
        "key": os.path.expanduser(key) if key else "",
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


def _build_acme_renew_command(settings):
    """Return an acme.sh renew command without embedding secrets."""
    base_domain = settings.get("base_domain", "")
    cmd = [_acme_binary(settings), "--renew", "-d", base_domain, "--ecc"]
    return [part for part in cmd if part]


def _build_deploy_steps(settings, target):
    """Build executable deployment steps for a target without secret values."""
    driver = target.get("deploy_driver", "")
    source = _source_paths(settings, target)
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

    if not settings.get("base_domain"):
        warnings.append("missing [certificates].base_domain")
    if not adopted_existing and not settings.get("dns_provider"):
        warnings.append("missing [certificates].dns_provider")
    token_path = settings.get("dns_token_path") or ""
    if not adopted_existing and not token_path:
        warnings.append("missing [certificates].dns_token_path")
    elif not os.path.isfile(os.path.expanduser(token_path)):
        warnings.append(f"dns token path not found: {token_path}")
    if not adopted_existing and settings.get("dns_provider") == "cloudflare" and not settings.get("cloudflare_zone_id"):
        warnings.append("missing [certificates].cloudflare_zone_id")
    if not adopted_existing and settings.get("record_strategy") == "public-private-a":
        warnings.append("record_strategy public-private-a publishes private IPs in public DNS")
    if not targets:
        warnings.append("no [[cert_target]] entries configured")

    source = _source_paths(settings)
    for label, path in source.items():
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
    started = time.monotonic()
    try:
        with socket.create_connection((connect_host, port), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                der = ssock.getpeercert(binary_form=True)
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
    is_lets_encrypt = "let's encrypt" in issuer or "lets encrypt" in issuer
    fp_match = bool(managed_fingerprint and probe.get("fingerprint_sha256") == managed_fingerprint)
    if fp_match or (is_lets_encrypt and san_match and not probe.get("self_signed")):
        return "SERVING_MANAGED_WILDCARD"
    return "SELF_SIGNED_OR_OTHER"


def _reconcile_lifecycle_targets(cfg):
    """Probe configured cert targets and classify what is actually served."""
    settings = _cert_settings(cfg)
    targets = _cert_targets(cfg)
    source = _source_paths(settings)
    managed_fingerprint = _pem_cert_fingerprint(source.get("fullchain"))
    results = []
    for target in targets:
        probe = _verify_tls_target(target)
        probe["classification"] = _classify_tls_probe(settings, target, probe, managed_fingerprint)
        probe["managed_fingerprint_sha256"] = managed_fingerprint
        # Until deploy hooks are modeled per target, surface the renewal gap
        # truth explicitly for non-proxy appliance targets.
        driver = target.get("deploy_driver", "")
        probe["renewal_hooked"] = driver == "reverse_proxy"
        probe["renewal_gap"] = probe["classification"] == "SERVING_MANAGED_WILDCARD" and not probe["renewal_hooked"]
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
        },
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


def _infer_cert_targets(cfg, base_domain):
    """Infer default certificate targets from existing pve-freq inventory."""
    targets = []
    pve_nodes = list(getattr(cfg, "pve_nodes", []) or [])
    pve_names = list(getattr(cfg, "pve_node_names", []) or [])
    for idx, ip in enumerate(pve_nodes):
        name = pve_names[idx] if idx < len(pve_names) and pve_names[idx] else f"pve{idx + 1:02d}"
        targets.append(
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
        targets.append(
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
        targets.append(
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
                der = ssock.getpeercert(binary_form=True)
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

    settings = dict(DEFAULT_CERT_SETTINGS)
    settings.update(
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
    dry_run = bool(getattr(args, "dry_run", False))
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "command": command,
                    "dry_run": dry_run,
                    "acme_available": _acme_available(settings),
                    "acme_install_planned": not _acme_available(settings),
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
    result = _run_acme_command(settings, command)
    if result.returncode != 0:
        fmt.error((result.stderr or result.stdout or "acme.sh failed")[:800])
        return result.returncode or 1
    fmt.step_ok("ACME issue completed")
    fmt.footer()
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
    dry_run = bool(getattr(args, "dry_run", False))
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "command": command,
                    "dry_run": dry_run,
                    "acme_available": _acme_available(settings),
                    "acme_install_planned": not _acme_available(settings),
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
    result = _run_acme_command(settings, command)
    if result.returncode != 0:
        fmt.error((result.stderr or result.stdout or "acme.sh failed")[:800])
        return result.returncode or 1
    fmt.step_ok("ACME renew completed")
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
