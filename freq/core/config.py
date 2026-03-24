"""Configuration loader for FREQ.

Reads freq.toml (primary) and legacy bash-style configs (hosts.conf, vlans.conf).
Safe defaults are set BEFORE loading any config — if config is broken, FREQ still runs.
This is Trap #4 from the 5 Traps: config vs code confusion.
"""
import os
import re
from dataclasses import dataclass, field

try:
    import tomllib
except ModuleNotFoundError:
    # Python < 3.11 fallback — minimal TOML parser for freq.toml
    tomllib = None
from pathlib import Path
from typing import Optional

from freq.core.types import (
    Host, VLAN, Distro, Container, ContainerVM,
    FleetBoundaries, PhysicalDevice, PVENode,
)


# --- Safe Defaults (set BEFORE config load) ---
# These survive missing/broken config. Trap #4 lesson.

_DEFAULTS = {
    "version": "2.0.0",
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
    "vm_cpu": "kvm64",
    "vm_machine": "q35",
    "vm_bios": "ovmf",
    "vm_domain": "cluster.local",
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
    ssh_key_path: str = ""       # ed25519 (primary — modern hosts)
    ssh_rsa_key_path: str = ""   # RSA (legacy — iDRAC, switch)

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
    vm_bios: str = _DEFAULTS["vm_bios"]
    vm_domain: str = _DEFAULTS["vm_domain"]
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
    switch_ip: str = ""
    docker_dev_ip: str = ""
    docker_config_base: str = ""   # base path for Docker container configs
    docker_backup_dir: str = ""    # path for Docker container backups
    legacy_password_file: str = "" # password file for iDRAC/switch SSH auth

    # Notifications
    discord_webhook: str = ""
    slack_webhook: str = ""

    # Fleet data (loaded separately)
    hosts: list = field(default_factory=list)
    vlans: list = field(default_factory=list)
    distros: list = field(default_factory=list)

    # Container registry (loaded from containers.toml)
    container_vms: dict = field(default_factory=dict)  # vm_id -> ContainerVM

    # Template profiles
    template_profiles: dict = field(default_factory=dict)

    # NIC
    nic_bridge: str = "vmbr0"
    nic_mtu: int = 1500
    nic_profiles: dict = field(default_factory=dict)

    # Service ports
    dashboard_port: int = _DEFAULTS["dashboard_port"]
    watchdog_port: int = _DEFAULTS["watchdog_port"]
    agent_port: int = _DEFAULTS["agent_port"]

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

    # Production default
    if os.path.isdir("/opt/pve-freq"):
        return "/opt/pve-freq"

    return str(src_dir)


def _resolve_paths(cfg: FreqConfig) -> None:
    """Resolve all paths relative to install_dir."""
    base = Path(cfg.install_dir)
    cfg.conf_dir = str(base / "conf")
    cfg.data_dir = str(base / "data")
    cfg.log_file = str(base / "data" / "log" / "freq.log")
    cfg.hosts_file = str(base / "conf" / "hosts.conf")
    cfg.vault_dir = str(base / "data" / "vault")
    cfg.vault_file = str(base / "data" / "vault" / "freq-vault.enc")
    cfg.key_dir = str(base / "data" / "keys")


def load_toml(path: str) -> dict:
    """Load a TOML config file. Returns empty dict on failure.

    Uses tomllib (3.11+) or falls back to a basic parser for 3.9+.
    """
    if tomllib is not None:
        try:
            with open(path, "rb") as f:
                return tomllib.load(f)
        except (FileNotFoundError, tomllib.TOMLDecodeError):
            return {}
    else:
        return _parse_toml_basic(path)


def _parse_toml_basic(path: str) -> dict:
    """Minimal TOML parser for Python < 3.11. Handles freq.toml structure."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return {}

    result = {}
    current_section = None
    current_subsection = None

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Section header [section] or [section.subsection]
        if line.startswith("[") and line.endswith("]"):
            parts = line[1:-1].split(".")
            current_section = parts[0]
            current_subsection = ".".join(parts[1:]) if len(parts) > 1 else None
            if current_section not in result:
                result[current_section] = {}
            if current_subsection and current_subsection not in result[current_section]:
                result[current_section][current_subsection] = {}
            continue

        # Key = value
        if "=" in line and current_section:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            # Parse value
            parsed = _parse_toml_value(value)

            if current_subsection:
                if current_subsection not in result[current_section]:
                    result[current_section][current_subsection] = {}
                result[current_section][current_subsection][key] = parsed
            else:
                result[current_section][key] = parsed

    return result


def _parse_toml_value(value: str):
    """Parse a TOML value string."""
    # String
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    # Boolean
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    # Integer
    try:
        return int(value)
    except ValueError:
        pass
    # Float
    try:
        return float(value)
    except ValueError:
        pass
    # Array
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        items = []
        for item in inner.split(","):
            items.append(_parse_toml_value(item.strip()))
        return items
    # Inline table
    if value.startswith("{") and value.endswith("}"):
        inner = value[1:-1].strip()
        if not inner:
            return {}
        result = {}
        for pair in inner.split(","):
            if "=" in pair:
                k, _, v = pair.partition("=")
                result[k.strip()] = _parse_toml_value(v.strip())
        return result
    # Bare string
    return value


def load_config(install_dir: Optional[str] = None) -> FreqConfig:
    """Load FREQ configuration with safe defaults.

    Safe defaults are set first. Config file overrides what it can.
    If config is broken or missing, FREQ runs on defaults.
    """
    cfg = FreqConfig()
    cfg.install_dir = install_dir or resolve_install_dir()
    _resolve_paths(cfg)

    # Try TOML config first
    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    data = load_toml(toml_path)

    if data:
        _apply_toml(cfg, data)

    # Load fleet data
    cfg.hosts = load_hosts(cfg.hosts_file)
    cfg.vlans = load_vlans(os.path.join(cfg.conf_dir, "vlans.toml"))
    cfg.distros = load_distros(os.path.join(cfg.conf_dir, "distros.toml"))
    cfg.container_vms = load_containers(os.path.join(cfg.conf_dir, "containers.toml"))
    cfg.fleet_boundaries = load_fleet_boundaries(os.path.join(cfg.conf_dir, "fleet-boundaries.toml"))

    # Detect SSH keys
    cfg.ssh_key_path = _detect_ssh_key(cfg)
    cfg.ssh_rsa_key_path = _detect_rsa_key(cfg)

    return cfg


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
    cfg.ssh_connect_timeout = ssh.get("connect_timeout", cfg.ssh_connect_timeout)
    cfg.ssh_max_parallel = ssh.get("max_parallel", cfg.ssh_max_parallel)
    cfg.ssh_mode = ssh.get("mode", cfg.ssh_mode)
    cfg.legacy_password_file = ssh.get("legacy_password_file", cfg.legacy_password_file)

    pve = data.get("pve", {})
    cfg.pve_nodes = pve.get("nodes", cfg.pve_nodes)
    cfg.pve_node_names = pve.get("node_names", cfg.pve_node_names)
    storage = pve.get("storage", {})
    for node, info in storage.items():
        cfg.pve_storage[node] = {"pool": info.get("pool", ""), "type": info.get("type", "")}

    vm = data.get("vm", {}).get("defaults", {})
    cfg.vm_default_cores = vm.get("cores", cfg.vm_default_cores)
    cfg.vm_default_ram = vm.get("ram", cfg.vm_default_ram)
    cfg.vm_default_disk = vm.get("disk", cfg.vm_default_disk)
    cfg.vm_cpu = vm.get("cpu", cfg.vm_cpu)
    cfg.vm_machine = vm.get("machine", cfg.vm_machine)
    cfg.vm_scsihw = vm.get("scsihw", cfg.vm_scsihw)
    cfg.vm_bios = vm.get("bios", cfg.vm_bios)
    cfg.vm_domain = vm.get("domain", cfg.vm_domain)
    cfg.vm_gateway = vm.get("gateway", cfg.vm_gateway)
    cfg.vm_nameserver = vm.get("nameserver", cfg.vm_nameserver)

    safety = data.get("safety", {})
    cfg.protected_vmids = safety.get("protected_vmids", cfg.protected_vmids)
    cfg.protected_ranges = safety.get("protected_ranges", cfg.protected_ranges)
    cfg.max_failure_percent = safety.get("max_failure_percent", cfg.max_failure_percent)

    infra = data.get("infrastructure", {})
    cfg.cluster_name = infra.get("cluster_name", cfg.cluster_name)
    cfg.timezone = infra.get("timezone", cfg.timezone)
    cfg.truenas_ip = infra.get("truenas_ip", cfg.truenas_ip)
    cfg.pfsense_ip = infra.get("pfsense_ip", cfg.pfsense_ip)
    cfg.switch_ip = infra.get("switch_ip", cfg.switch_ip)
    cfg.docker_dev_ip = infra.get("docker_dev_ip", cfg.docker_dev_ip)
    cfg.docker_config_base = infra.get("docker_config_base", cfg.docker_config_base)
    cfg.docker_backup_dir = infra.get("docker_backup_dir", cfg.docker_backup_dir)

    templates = data.get("templates", {})
    cfg.template_profiles = templates.get("profiles", cfg.template_profiles)

    nic = data.get("nic", {})
    cfg.nic_bridge = nic.get("bridge", cfg.nic_bridge)
    cfg.nic_mtu = nic.get("mtu", cfg.nic_mtu)
    cfg.nic_profiles = nic.get("profiles", cfg.nic_profiles)

    notify = data.get("notifications", {})
    cfg.discord_webhook = notify.get("discord_webhook", cfg.discord_webhook)
    cfg.slack_webhook = notify.get("slack_webhook", cfg.slack_webhook)

    services = data.get("services", {})
    cfg.dashboard_port = services.get("dashboard_port", cfg.dashboard_port)
    cfg.watchdog_port = services.get("watchdog_port", cfg.watchdog_port)
    cfg.agent_port = services.get("agent_port", cfg.agent_port)


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
                hosts.append(Host(
                    ip=parts[0],
                    label=parts[1],
                    htype=parts[2],
                    groups=parts[3] if len(parts) > 3 else "",
                    all_ips=all_ips,
                ))
    except FileNotFoundError:
        pass
    return hosts


def load_vlans(path: str) -> list:
    """Load VLAN definitions from TOML."""
    data = load_toml(path)
    vlans = []
    for key, info in data.get("vlan", {}).items():
        vlans.append(VLAN(
            id=info.get("id", 0),
            name=info.get("name", key),
            subnet=info.get("subnet", ""),
            prefix=info.get("prefix", ""),
            gateway=info.get("gateway", ""),
        ))
    return vlans


def load_distros(path: str) -> list:
    """Load cloud image definitions from TOML."""
    data = load_toml(path)
    distros = []
    for key, info in data.get("distro", {}).items():
        distros.append(Distro(
            key=key,
            name=info.get("name", key),
            url=info.get("url", ""),
            filename=info.get("filename", ""),
            sha_url=info.get("sha_url", ""),
            family=info.get("family", ""),
            tier=info.get("tier", "supported"),
            aliases=info.get("aliases", []),
        ))
    return distros


def load_containers(path: str) -> dict:
    """Load container registry from containers.toml.

    Returns dict of vm_id (int) -> ContainerVM.
    Format: [vm.<id>] for VM, [vm.<id>.containers.<name>] for containers.
    """
    data = load_toml(path)
    result = {}

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

        # Parse containers sub-tables
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
