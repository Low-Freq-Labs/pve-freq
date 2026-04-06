"""Configuration loader for FREQ.

Provides: load_config() → FreqConfig dataclass with ~40 fields.

Reads freq.toml (primary) and legacy bash-style configs (hosts.conf, vlans.conf).
Hosts, VLANs, distros, fleet boundaries, monitors — everything the CLI and
web dashboard need to operate. Safe defaults set BEFORE loading any config so
FREQ runs even with a broken or missing config file.

Replaces: Ansible inventory files + group_vars + host_vars ($0 but complex),
          SaltStack pillar/grains ($0 but steeper learning curve)

Architecture:
    - TOML parsing via tomllib (stdlib 3.11+)
    - Legacy hosts.conf/vlans.conf parsed as key=value for migration
    - FreqConfig is a frozen-ish dataclass — loaded once, passed everywhere
    - Config paths: /etc/freq/ (system) or ./conf/ (dev/local)
    - Credentials NEVER in config — always vault paths or file references

Design decisions:
    - One load_config() call returns everything. No per-module config loading.
    - Safe defaults mean a fresh install with empty freq.toml still boots.
    - hosts.conf migration path: detected, warned, auto-read, eventually removed.
"""

import os
import shutil

try:
    import tomllib
except ModuleNotFoundError:
    # Python < 3.11 — should not happen (MIN_PYTHON = 3.11) but fail gracefully
    tomllib = None
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from freq.core.types import (
    Host,
    VLAN,
    Distro,
    Container,
    ContainerVM,
    FleetBoundaries,
    PhysicalDevice,
    PVENode,
    Monitor,
)
from freq import __version__


# --- Safe Defaults (set BEFORE config load) ---
# These survive missing/broken config. Trap #4 lesson.

_DEFAULTS = {
    "version": __version__,
    "brand": "PVE FREQ",
    "build": "default",
    "ascii": False,
    "debug": False,
    "ssh_service_account": "freq-admin",
    "ssh_connect_timeout": 5,
    "ssh_max_parallel": 5,
    "ssh_mode": "sudo",
    "vm_default_cores": 2,
    "vm_default_ram": 2048,
    "vm_default_disk": 32,
    "vm_cpu": "x86-64-v2-AES",
    "vm_machine": "q35",
    "vm_gateway": "",
    "vm_nameserver": "1.1.1.1",
    "max_failure_percent": 50,
    "cluster_name": "",
    "timezone": "UTC",
    "dashboard_port": 8888,
    "watchdog_port": 9900,
    "agent_port": 9990,
}


@dataclass
class FreqConfig:
    """Complete FREQ configuration — all settings in one place."""

    # Identity
    version: str = _DEFAULTS["version"]
    brand: str = _DEFAULTS["brand"]
    build: str = _DEFAULTS["build"]
    ascii_mode: bool = _DEFAULTS["ascii"]
    debug: bool = _DEFAULTS["debug"]

    # Paths (resolved after install_dir is known)
    install_dir: str = ""
    data_dir: str = ""
    log_file: str = ""
    conf_dir: str = ""
    hosts_file: str = ""
    vault_dir: str = ""
    vault_file: str = ""
    key_dir: str = ""

    # SSH
    ssh_service_account: str = _DEFAULTS["ssh_service_account"]
    ssh_connect_timeout: int = _DEFAULTS["ssh_connect_timeout"]
    ssh_max_parallel: int = _DEFAULTS["ssh_max_parallel"]
    ssh_mode: str = _DEFAULTS["ssh_mode"]
    ssh_key_path: str = ""  # ed25519 (primary — modern hosts)
    ssh_rsa_key_path: str = ""  # RSA (legacy — iDRAC, switch)

    # PVE
    pve_nodes: list = field(default_factory=list)
    pve_node_names: list = field(default_factory=list)
    pve_storage: dict = field(default_factory=dict)

    # VM defaults
    vm_default_cores: int = _DEFAULTS["vm_default_cores"]
    vm_default_ram: int = _DEFAULTS["vm_default_ram"]
    vm_default_disk: int = _DEFAULTS["vm_default_disk"]
    vm_cpu: str = _DEFAULTS["vm_cpu"]
    vm_machine: str = _DEFAULTS["vm_machine"]
    vm_scsihw: str = "virtio-scsi-single"
    vm_gateway: str = _DEFAULTS["vm_gateway"]
    vm_nameserver: str = _DEFAULTS["vm_nameserver"]

    # Safety
    protected_vmids: list = field(default_factory=list)
    protected_ranges: list = field(default_factory=list)
    max_failure_percent: int = _DEFAULTS["max_failure_percent"]

    # Infrastructure
    cluster_name: str = _DEFAULTS["cluster_name"]
    timezone: str = _DEFAULTS["timezone"]
    truenas_ip: str = ""
    pfsense_ip: str = ""
    opnsense_ip: str = ""
    synology_ip: str = ""
    switch_ip: str = ""
    docker_dev_ip: str = ""
    docker_config_base: str = ""  # base path for Docker container configs
    docker_backup_dir: str = ""  # path for Docker container backups
    legacy_password_file: str = ""  # password file for iDRAC/switch SSH auth
    snmp_community: str = "public"  # SNMP community string

    # Notifications
    discord_webhook: str = ""
    slack_webhook: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_to: str = ""
    smtp_tls: bool = True
    ntfy_url: str = ""
    ntfy_topic: str = ""
    gotify_url: str = ""
    gotify_token: str = ""
    pushover_user: str = ""
    pushover_token: str = ""
    webhook_url: str = ""

    # PVE API (optional — token auth alternative to SSH)
    pve_api_token_id: str = ""  # e.g. "freq@pve!dashboard"
    pve_api_token_secret: str = ""  # loaded from credential file at runtime
    pve_api_verify_ssl: bool = False  # homelab self-signed certs

    # Users from TOML (populated by _apply_toml if [users] section exists)
    _toml_users: list = field(default_factory=list)

    # Fleet data (loaded separately)
    hosts: list = field(default_factory=list)
    vlans: list = field(default_factory=list)
    distros: list = field(default_factory=list)

    # Container registry (loaded from containers.toml)
    container_vms: dict = field(default_factory=dict)  # vm_id -> ContainerVM

    # HTTP monitors (loaded from freq.toml [[monitor]])
    monitors: list = field(default_factory=list)  # List of Monitor

    # Template profiles
    template_profiles: dict = field(default_factory=dict)

    # NIC
    nic_bridge: str = "vmbr0"
    nic_profiles: dict = field(default_factory=dict)

    # Service ports
    dashboard_port: int = _DEFAULTS["dashboard_port"]
    watchdog_port: int = _DEFAULTS["watchdog_port"]
    agent_port: int = _DEFAULTS["agent_port"]

    # TLS (optional — omit for plaintext HTTP)
    tls_cert: str = ""
    tls_key: str = ""

    # Fleet boundaries (loaded from fleet-boundaries.toml)
    fleet_boundaries: FleetBoundaries = field(default_factory=FleetBoundaries)


def resolve_install_dir() -> str:
    """Find the FREQ install directory.

    Priority:
    1. FREQ_DIR environment variable
    2. Directory containing this source (development mode)
    3. /opt/pve-freq (production install)
    """
    env_dir = os.environ.get("FREQ_DIR")
    if env_dir and os.path.isdir(env_dir):
        return env_dir

    # Development: walk up from this file to find pyproject.toml
    src_dir = Path(__file__).resolve().parent.parent.parent
    if (src_dir / "pyproject.toml").exists():
        return str(src_dir)

    # Production default — always use /opt/pve-freq for pip installs
    return "/opt/pve-freq"


def _resolve_paths(cfg: FreqConfig) -> None:
    """Resolve all paths relative to install_dir."""
    base = Path(cfg.install_dir)
    cfg.conf_dir = str(base / "conf")
    cfg.data_dir = str(base / "data")
    cfg.log_file = str(base / "data" / "log" / "freq.log")
    cfg.hosts_file = str(base / "conf" / "hosts.toml")
    cfg.vault_dir = str(base / "data" / "vault")
    cfg.vault_file = str(base / "data" / "vault" / "freq-vault.enc")
    cfg.key_dir = str(base / "data" / "keys")


def load_toml(path: str) -> dict:
    """Load a TOML config file. Returns empty dict on failure."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (FileNotFoundError, PermissionError, tomllib.TOMLDecodeError):
        return {}


def bootstrap_conf(install_dir: str) -> bool:
    """Seed conf/ and data/ directories from package data on first run.

    Returns True if bootstrap happened, False if conf/ already exists.
    Idempotent — never overwrites existing files.
    """
    conf_dir = os.path.join(install_dir, "conf")
    if os.path.isdir(conf_dir) and os.listdir(conf_dir):
        return False  # Already has config files

    try:
        from freq.data import get_data_path
    except ImportError:
        return False  # Package data not available (shouldn't happen)

    templates = get_data_path() / "conf-templates"
    if not templates.is_dir():
        return False

    try:
        os.makedirs(conf_dir, exist_ok=True)
    except PermissionError:
        return False  # Non-root user — bootstrap deferred to freq init

    # Copy all template files (*.example, *.toml, *.conf)
    for src in templates.iterdir():
        if src.is_file():
            dst = os.path.join(conf_dir, src.name)
            if not os.path.exists(dst):
                shutil.copy2(str(src), dst)

    # Copy personality/
    personality_src = templates / "personality"
    if personality_src.is_dir():
        personality_dst = os.path.join(conf_dir, "personality")
        os.makedirs(personality_dst, exist_ok=True)
        for src in personality_src.glob("*.toml"):
            dst = os.path.join(personality_dst, src.name)
            if not os.path.exists(dst):
                shutil.copy2(str(src), dst)

    # Copy plugins/
    plugins_src = templates / "plugins"
    if plugins_src.is_dir():
        plugins_dst = os.path.join(conf_dir, "plugins")
        os.makedirs(plugins_dst, exist_ok=True)
        for src in plugins_src.glob("*.py"):
            dst = os.path.join(plugins_dst, src.name)
            if not os.path.exists(dst):
                shutil.copy2(str(src), dst)

    # Create data directories
    for subdir in ("log", "vault", "keys", "cache", "knowledge"):
        os.makedirs(os.path.join(install_dir, "data", subdir), exist_ok=True)

    # Seed knowledge base
    try:
        knowledge_src = get_data_path() / "knowledge"
        if knowledge_src.is_dir():
            knowledge_dst = os.path.join(install_dir, "data", "knowledge")
            for src in knowledge_src.glob("*.toml"):
                dst = os.path.join(knowledge_dst, src.name)
                if not os.path.exists(dst):
                    shutil.copy2(str(src), dst)
    except Exception:
        pass  # Knowledge base is optional

    return True


_deprecation_warned: set = set()


def _deprecation_warn(old_name: str, new_name: str):
    """Print a one-time deprecation warning for legacy config files."""
    if old_name in _deprecation_warned:
        return
    _deprecation_warned.add(old_name)
    import sys

    print(f"[FREQ] DEPRECATION: {old_name} detected. Migrate to {new_name} for long-term support.", file=sys.stderr)


import time as _time

_config_cache = None
_config_cache_ts = 0
_CONFIG_TTL = 5  # seconds


def load_config(install_dir: Optional[str] = None, force: bool = False) -> FreqConfig:
    """Load FREQ configuration with safe defaults.

    Safe defaults are set first. Config file overrides what it can.
    If config is broken or missing, FREQ runs on defaults.
    Caches result for 5 seconds to avoid redundant disk reads.
    """
    global _config_cache, _config_cache_ts
    now = _time.time()
    if not force and _config_cache and (now - _config_cache_ts) < _CONFIG_TTL and install_dir is None:
        return _config_cache
    cfg = FreqConfig()
    cfg.install_dir = install_dir or resolve_install_dir()
    _resolve_paths(cfg)

    # Bootstrap conf/ from package data if missing
    bootstrap_conf(cfg.install_dir)

    # Try TOML config first
    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    data = load_toml(toml_path)

    if data:
        _apply_toml(cfg, data)

    # Load fleet data — hosts.toml is the primary format
    if os.path.isfile(cfg.hosts_file):
        cfg.hosts = load_hosts_toml(cfg.hosts_file)
    else:
        # Migration fallback: read legacy hosts.conf if it exists
        legacy = os.path.join(cfg.conf_dir, "hosts.conf")
        if os.path.isfile(legacy):
            cfg.hosts = load_hosts(legacy)
            if cfg.hosts:
                _deprecation_warn("hosts.conf", "hosts.toml")
                # Auto-migrate: write hosts.toml and stop reading hosts.conf
                save_hosts_toml(cfg.hosts_file, cfg.hosts)
                from freq.core import log as _logger

                _logger.info("auto-migrated hosts.conf to hosts.toml")
    cfg.vlans = load_vlans(os.path.join(cfg.conf_dir, "vlans.toml"))
    cfg.distros = load_distros(os.path.join(cfg.conf_dir, "distros.toml"))
    cfg.container_vms = load_containers(os.path.join(cfg.conf_dir, "containers.toml"))
    cfg.fleet_boundaries = load_fleet_boundaries(os.path.join(cfg.conf_dir, "fleet-boundaries.toml"))
    cfg.monitors = _load_monitors(data if data else {})

    # Detect SSH keys
    cfg.ssh_key_path = _detect_ssh_key(cfg)
    cfg.ssh_rsa_key_path = _detect_rsa_key(cfg)

    # Validate loaded config
    from freq.core import log as logger

    for w in _validate_config(cfg):
        logger.warn(f"config: {w}")

    _config_cache = cfg
    _config_cache_ts = _time.time()
    return cfg


def _validate_config(cfg: FreqConfig) -> list:
    """Validate config. Returns list of warning strings."""
    warnings = []
    from freq.core.validate import ip as valid_ip, port as valid_port

    for host in cfg.hosts:
        if host.ip and not valid_ip(host.ip):
            warnings.append(f"Host {host.label}: invalid IP '{host.ip}'")
        if hasattr(host, "htype") and host.htype:
            try:
                from freq.deployers import resolve_htype

                cat, vendor = resolve_htype(host.htype)
                if cat == "unknown":
                    warnings.append(f"Host {host.label}: unknown type '{host.htype}'")
            except Exception:
                pass

    if cfg.dashboard_port and not valid_port(cfg.dashboard_port):
        warnings.append(f"Invalid dashboard port: {cfg.dashboard_port}")
    if cfg.ssh_connect_timeout <= 0:
        warnings.append(f"SSH connect timeout must be positive: {cfg.ssh_connect_timeout}")
    if cfg.ssh_max_parallel <= 0:
        warnings.append(f"SSH max parallel must be positive: {cfg.ssh_max_parallel}")

    return warnings


def _safe_int(value, default):
    """Coerce a value to int, falling back to default on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        from freq.core import log as logger

        logger.warn(f"config: expected int, got {type(value).__name__}: {value!r}, using default {default}")
        return default


def _apply_toml(cfg: FreqConfig, data: dict) -> None:
    """Apply TOML config values to FreqConfig."""
    freq = data.get("freq", {})
    cfg.version = freq.get("version", cfg.version)
    cfg.brand = freq.get("brand", cfg.brand)
    cfg.build = freq.get("build", cfg.build)
    cfg.ascii_mode = freq.get("ascii", cfg.ascii_mode)
    cfg.debug = freq.get("debug", cfg.debug)

    ssh = data.get("ssh", {})
    cfg.ssh_service_account = ssh.get("service_account", cfg.ssh_service_account)
    cfg.ssh_connect_timeout = _safe_int(ssh.get("connect_timeout"), cfg.ssh_connect_timeout)
    cfg.ssh_max_parallel = _safe_int(ssh.get("max_parallel"), cfg.ssh_max_parallel)
    cfg.ssh_mode = ssh.get("mode", cfg.ssh_mode)
    cfg.legacy_password_file = ssh.get("legacy_password_file", cfg.legacy_password_file)

    pve = data.get("pve", {})
    cfg.pve_nodes = pve.get("nodes", cfg.pve_nodes)
    cfg.pve_node_names = pve.get("node_names", cfg.pve_node_names)
    storage = pve.get("storage", {})
    for node, info in storage.items():
        cfg.pve_storage[node] = {"pool": info.get("pool", ""), "type": info.get("type", "")}

    vm = data.get("vm", {}).get("defaults", {})
    cfg.vm_default_cores = _safe_int(vm.get("cores"), cfg.vm_default_cores)
    cfg.vm_default_ram = _safe_int(vm.get("ram"), cfg.vm_default_ram)
    cfg.vm_default_disk = _safe_int(vm.get("disk"), cfg.vm_default_disk)
    cfg.vm_cpu = vm.get("cpu", cfg.vm_cpu)
    cfg.vm_machine = vm.get("machine", cfg.vm_machine)
    cfg.vm_scsihw = vm.get("scsihw", cfg.vm_scsihw)
    cfg.vm_gateway = vm.get("gateway", cfg.vm_gateway)
    cfg.vm_nameserver = vm.get("nameserver", cfg.vm_nameserver)

    safety = data.get("safety", {})
    cfg.protected_vmids = safety.get("protected_vmids", cfg.protected_vmids)
    raw_ranges = safety.get("protected_ranges", cfg.protected_ranges)
    validated_ranges = []
    if isinstance(raw_ranges, list):
        for rng in raw_ranges:
            if isinstance(rng, (list, tuple)) and len(rng) == 2:
                try:
                    validated_ranges.append([int(rng[0]), int(rng[1])])
                except (ValueError, TypeError):
                    pass
    cfg.protected_ranges = validated_ranges if validated_ranges else cfg.protected_ranges
    cfg.max_failure_percent = _safe_int(safety.get("max_failure_percent"), cfg.max_failure_percent)

    infra = data.get("infrastructure", {})
    cfg.cluster_name = infra.get("cluster_name", cfg.cluster_name)
    cfg.timezone = infra.get("timezone", cfg.timezone)
    cfg.truenas_ip = infra.get("truenas_ip", cfg.truenas_ip)
    cfg.pfsense_ip = infra.get("pfsense_ip", cfg.pfsense_ip)
    cfg.opnsense_ip = infra.get("opnsense_ip", cfg.opnsense_ip)

    # Also load [pfsense] section (written by freq init)
    pfsense_section = data.get("pfsense", {})
    if pfsense_section.get("host") and not cfg.pfsense_ip:
        cfg.pfsense_ip = pfsense_section["host"]
    cfg.synology_ip = infra.get("synology_ip", cfg.synology_ip)
    cfg.switch_ip = infra.get("switch_ip", cfg.switch_ip)
    cfg.docker_dev_ip = infra.get("docker_dev_ip", cfg.docker_dev_ip)
    cfg.docker_config_base = infra.get("docker_config_base", cfg.docker_config_base)
    cfg.docker_backup_dir = infra.get("docker_backup_dir", cfg.docker_backup_dir)
    cfg.snmp_community = infra.get("snmp_community", cfg.snmp_community)

    templates = data.get("templates", {})
    cfg.template_profiles = templates.get("profiles", cfg.template_profiles)

    nic = data.get("nic", {})
    cfg.nic_bridge = nic.get("bridge", cfg.nic_bridge)
    cfg.nic_profiles = nic.get("profiles", cfg.nic_profiles)

    notify = data.get("notifications", {})
    cfg.discord_webhook = notify.get("discord_webhook", cfg.discord_webhook)
    cfg.slack_webhook = notify.get("slack_webhook", cfg.slack_webhook)
    cfg.telegram_bot_token = notify.get("telegram_bot_token", cfg.telegram_bot_token)
    cfg.telegram_chat_id = notify.get("telegram_chat_id", cfg.telegram_chat_id)
    cfg.smtp_host = notify.get("smtp_host", cfg.smtp_host)
    cfg.smtp_port = _safe_int(notify.get("smtp_port"), cfg.smtp_port)
    cfg.smtp_user = notify.get("smtp_user", cfg.smtp_user)
    cfg.smtp_password = notify.get("smtp_password", cfg.smtp_password)
    cfg.smtp_to = notify.get("smtp_to", cfg.smtp_to)
    cfg.smtp_tls = notify.get("smtp_tls", cfg.smtp_tls)
    cfg.ntfy_url = notify.get("ntfy_url", cfg.ntfy_url)
    cfg.ntfy_topic = notify.get("ntfy_topic", cfg.ntfy_topic)
    cfg.gotify_url = notify.get("gotify_url", cfg.gotify_url)
    cfg.gotify_token = notify.get("gotify_token", cfg.gotify_token)
    cfg.pushover_user = notify.get("pushover_user", cfg.pushover_user)
    cfg.pushover_token = notify.get("pushover_token", cfg.pushover_token)
    cfg.webhook_url = notify.get("webhook_url", cfg.webhook_url)

    services = data.get("services", {})
    cfg.dashboard_port = _safe_int(services.get("dashboard_port"), cfg.dashboard_port)
    cfg.watchdog_port = _safe_int(services.get("watchdog_port"), cfg.watchdog_port)
    cfg.agent_port = _safe_int(services.get("agent_port"), cfg.agent_port)
    cfg.tls_cert = services.get("tls_cert", cfg.tls_cert)
    cfg.tls_key = services.get("tls_key", cfg.tls_key)

    # PVE API token auth (optional — alternative to SSH)
    cfg.pve_api_token_id = pve.get("api_token_id", cfg.pve_api_token_id)
    cfg.pve_api_verify_ssl = pve.get("api_verify_ssl", cfg.pve_api_verify_ssl)
    token_secret_path = pve.get("api_token_secret_path", "")
    if token_secret_path and os.path.isfile(token_secret_path):
        try:
            with open(token_secret_path) as f:
                cfg.pve_api_token_secret = f.read().strip()
        except OSError:
            pass

    # Inline users (optional — replaces users.conf)
    users_section = data.get("users", {})
    if users_section:
        for username, info in users_section.items():
            cfg._toml_users.append(
                {
                    "username": username,
                    "role": info.get("role", "viewer") if isinstance(info, dict) else "viewer",
                    "groups": info.get("groups", "") if isinstance(info, dict) else "",
                }
            )


# --- Fleet Loaders ---


def load_hosts(path: str) -> list:
    """Load hosts.conf — one host per line: IP LABEL TYPE [GROUPS] [ALL_IPS].

    Column 5 (ALL_IPS) is optional — comma-separated list of all IPv4
    addresses on the host. Backwards compatible with old 3-4 column format.
    """
    hosts = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                all_ips = []
                if len(parts) > 4:
                    all_ips = [ip for ip in parts[4].split(",") if ip]
                hosts.append(
                    Host(
                        ip=parts[0],
                        label=parts[1],
                        htype=parts[2],
                        groups=parts[3] if len(parts) > 3 else "",
                        all_ips=all_ips,
                    )
                )
    except FileNotFoundError:
        pass
    return hosts


def load_hosts_toml(path: str) -> list:
    """Load hosts from TOML format (preferred over hosts.conf).

    Format:
        [[host]]
        ip = "10.0.0.10"
        label = "node1"
        type = "pve"
        groups = "prod,cluster"
        all_ips = ["10.0.0.10", "10.0.1.10"]
    """
    data = load_toml(path)
    hosts = []
    for entry in data.get("host", []):
        all_ips = entry.get("all_ips", [])
        if isinstance(all_ips, str):
            all_ips = [ip for ip in all_ips.split(",") if ip]
        hosts.append(
            Host(
                ip=entry.get("ip", ""),
                label=entry.get("label", ""),
                htype=entry.get("type", "linux"),
                groups=entry.get("groups", ""),
                vmid=int(entry.get("vmid", 0)),
                all_ips=all_ips,
            )
        )
    return hosts


def save_hosts_toml(path: str, hosts: list) -> None:
    """Write all hosts to TOML format.

    Overwrites the file. Each host becomes a [[host]] entry.
    """
    lines = ["# FREQ Fleet Registry\n", "# Managed by freq — do not edit while freq is running\n\n"]
    for h in hosts:
        lines.append("[[host]]\n")
        lines.append(f'ip = "{h.ip}"\n')
        lines.append(f'label = "{h.label}"\n')
        lines.append(f'type = "{h.htype}"\n')
        if h.groups:
            lines.append(f'groups = "{h.groups}"\n')
        if h.vmid:
            lines.append(f"vmid = {h.vmid}\n")
        if h.all_ips:
            ips_str = ", ".join(f'"{ip}"' for ip in h.all_ips)
            lines.append(f"all_ips = [{ips_str}]\n")
        lines.append("\n")
    with open(path, "w") as f:
        f.writelines(lines)


def append_host_toml(path: str, host) -> None:
    """Append a single host entry to the TOML hosts file."""
    lines = []
    if not os.path.isfile(path):
        lines.append("# FREQ Fleet Registry\n\n")
    lines.append("[[host]]\n")
    lines.append(f'ip = "{host.ip}"\n')
    lines.append(f'label = "{host.label}"\n')
    lines.append(f'type = "{host.htype}"\n')
    if host.groups:
        lines.append(f'groups = "{host.groups}"\n')
    if host.vmid:
        lines.append(f"vmid = {host.vmid}\n")
    if host.all_ips:
        ips_str = ", ".join(f'"{ip}"' for ip in host.all_ips)
        lines.append(f"all_ips = [{ips_str}]\n")
    lines.append("\n")
    with open(path, "a") as f:
        f.writelines(lines)


def _load_monitors(data: dict) -> list:
    """Load HTTP monitor definitions from parsed TOML data.

    Expected format in freq.toml:
        [[monitor]]
        name = "Dashboard"
        url = "http://10.0.0.50:8888/healthz"
        interval = 60
        timeout = 10
        expected_status = 200
    """
    monitors = []
    for mon in data.get("monitor", []):
        if not mon.get("url"):
            continue
        monitors.append(
            Monitor(
                name=mon.get("name", mon["url"]),
                url=mon["url"],
                interval=int(mon.get("interval", 60)),
                timeout=int(mon.get("timeout", 10)),
                expected_status=int(mon.get("expected_status", 200)),
                method=mon.get("method", "GET"),
                keyword=mon.get("keyword", ""),
                notify=mon.get("notify", True),
            )
        )
    return monitors


def load_vlans(path: str) -> list:
    """Load VLAN definitions from TOML."""
    data = load_toml(path)
    vlans = []
    for key, info in data.get("vlan", {}).items():
        vlans.append(
            VLAN(
                id=info.get("id", 0),
                name=info.get("name", key),
                subnet=info.get("subnet", ""),
                prefix=info.get("prefix", ""),
                gateway=info.get("gateway", ""),
            )
        )
    return vlans


def load_distros(path: str) -> list:
    """Load cloud image definitions from TOML."""
    data = load_toml(path)
    distros = []
    for key, info in data.get("distro", {}).items():
        distros.append(
            Distro(
                key=key,
                name=info.get("name", key),
                url=info.get("url", ""),
                filename=info.get("filename", ""),
                sha_url=info.get("sha_url", ""),
                family=info.get("family", ""),
                tier=info.get("tier", "supported"),
                aliases=info.get("aliases", []),
            )
        )
    return distros


def load_containers(path: str) -> dict:
    """Load container registry from containers.toml.

    Returns dict of host_label (str) -> ContainerVM.
    Supports two formats:
    - [host.<label>] with [host.<label>.containers.<name>] (init output)
    - [vm.<id>] with [vm.<id>.containers.<name>] (legacy)
    """
    data = load_toml(path)
    result = {}

    # Format 1: [host.<label>] — generated by freq init
    for key, info in data.get("host", {}).items():
        if not isinstance(info, dict):
            continue

        vm = ContainerVM(
            vm_id=0,
            ip=info.get("ip", ""),
            label=info.get("label", key),
            compose_path=info.get("compose_path", ""),
        )

        containers_data = info.get("containers", {})
        if isinstance(containers_data, dict):
            for cname, cinfo in containers_data.items():
                if isinstance(cinfo, dict):
                    vm.containers[cname] = Container(
                        name=cinfo.get("name", cname),
                        vm_id=0,
                        port=cinfo.get("port", 0),
                        api_path=cinfo.get("api_path", ""),
                        auth_type=cinfo.get("auth_type", ""),
                        auth_header=cinfo.get("auth_header", ""),
                        auth_param=cinfo.get("auth_param", ""),
                        vault_key=cinfo.get("vault_key", ""),
                    )

        result[key] = vm

    # Format 2: [vm.<id>] — legacy format
    for key, info in data.get("vm", {}).items():
        try:
            vm_id = int(key)
        except (ValueError, TypeError):
            continue

        if not isinstance(info, dict):
            continue

        vm = ContainerVM(
            vm_id=vm_id,
            ip=info.get("ip", ""),
            label=info.get("label", ""),
            compose_path=info.get("compose_path", ""),
        )

        containers_data = info.get("containers", {})
        if isinstance(containers_data, dict):
            for cname, cinfo in containers_data.items():
                if isinstance(cinfo, dict):
                    vm.containers[cname] = Container(
                        name=cname,
                        vm_id=vm_id,
                        port=cinfo.get("port", 0),
                        api_path=cinfo.get("api_path", ""),
                        auth_type=cinfo.get("auth_type", ""),
                        auth_header=cinfo.get("auth_header", ""),
                        auth_param=cinfo.get("auth_param", ""),
                        vault_key=cinfo.get("vault_key", ""),
                    )

        result[vm_id] = vm

    return result


def load_fleet_boundaries(path: str) -> FleetBoundaries:
    """Load fleet boundary definitions from fleet-boundaries.toml.

    Returns a FleetBoundaries with safe defaults if file is missing/broken.
    """
    data = load_toml(path)
    if not data:
        return FleetBoundaries()

    fb = FleetBoundaries()

    # Tiers: tier_name -> [allowed_actions]
    fb.tiers = data.get("tiers", {})

    # Categories: each [categories.X] section
    cats_raw = data.get("categories", {})
    for name, info in cats_raw.items():
        if isinstance(info, dict):
            fb.categories[name] = {
                "description": info.get("description", ""),
                "tier": info.get("tier", "probe"),
                "vmids": info.get("vmids", []),
            }
            if "range_start" in info:
                fb.categories[name]["range_start"] = info["range_start"]
            if "range_end" in info:
                fb.categories[name]["range_end"] = info["range_end"]

    # Physical devices
    phys_raw = data.get("physical", {})
    for key, info in phys_raw.items():
        if isinstance(info, dict):
            fb.physical[key] = PhysicalDevice(
                key=key,
                ip=info.get("ip", ""),
                label=info.get("label", ""),
                device_type=info.get("type", "unknown"),
                tier=info.get("tier", "probe"),
                detail=info.get("detail", ""),
            )

    # PVE nodes
    nodes_raw = data.get("pve_nodes", {})
    for name, info in nodes_raw.items():
        if isinstance(info, dict):
            fb.pve_nodes[name] = PVENode(
                name=name,
                ip=info.get("ip", ""),
                detail=info.get("detail", ""),
            )

    return fb


def _detect_ssh_key(cfg: FreqConfig) -> str:
    """Find the primary (ed25519) SSH key in priority order."""
    candidates = [
        os.path.join(cfg.key_dir, "freq_id_ed25519"),
        os.path.expanduser("~/.ssh/id_ed25519"),
        # Fallback to RSA if no ed25519 exists
        os.path.join(cfg.key_dir, "freq_id_rsa"),
        os.path.expanduser("~/.ssh/id_rsa"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""


def _detect_rsa_key(cfg: FreqConfig) -> str:
    """Find the RSA SSH key for legacy devices (iDRAC, switch)."""
    candidates = [
        os.path.join(cfg.key_dir, "freq_id_rsa"),
        os.path.expanduser("~/.ssh/id_rsa"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""
