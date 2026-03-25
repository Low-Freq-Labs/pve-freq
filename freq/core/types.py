"""Core data types for FREQ.

Every data structure lives here. No other file defines dataclasses.
Adapted from the Convergence engine types — extended for full CLI scope.
"""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


# --- Enums ---

class Phase(Enum):
    """Host remediation phase (engine pipeline)."""
    PENDING = auto()
    REACHABLE = auto()
    DISCOVERED = auto()
    COMPLIANT = auto()
    DRIFT = auto()
    PLANNED = auto()
    FIXING = auto()
    ACTIVATING = auto()
    VERIFYING = auto()
    DONE = auto()
    FAILED = auto()


class Severity(Enum):
    """Finding severity."""
    INFO = "info"
    WARN = "warn"
    CRIT = "crit"


class HostType(Enum):
    """Known host platform types."""
    LINUX = "linux"
    PVE = "pve"
    TRUENAS = "truenas"
    PFSENSE = "pfsense"
    IDRAC = "idrac"
    SWITCH = "switch"
    DOCKER = "docker"
    UNKNOWN = "unknown"


class Role(Enum):
    """RBAC roles — viewer < operator < admin < protected."""
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"
    PROTECTED = "protected"


class VMCategory(Enum):
    """VM fleet categories — determines what FREQ can do to each VM."""
    PERSONAL = "personal"
    INFRASTRUCTURE = "infrastructure"
    PROD_MEDIA = "prod_media"
    PROD_OTHER = "prod_other"
    SANDBOX = "sandbox"
    LAB = "lab"
    TEMPLATES = "templates"
    UNKNOWN = "unknown"


class PermissionTier(Enum):
    """Permission tiers — what actions each tier allows."""
    PROBE = "probe"
    OPERATOR = "operator"
    ADMIN = "admin"


# --- Core Data ---

@dataclass
class Host:
    """A fleet host."""
    ip: str
    label: str
    htype: str
    groups: str = ""
    all_ips: list = field(default_factory=list)
    phase: Phase = Phase.PENDING
    current: dict = field(default_factory=dict)
    desired: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    error: str = ""
    duration: float = 0.0


@dataclass
class CmdResult:
    """Result of a command execution (SSH or local)."""
    stdout: str
    stderr: str
    returncode: int
    duration: float = 0.0


@dataclass
class Finding:
    """A single configuration drift finding."""
    resource_type: str
    key: str
    current: Any
    desired: Any
    severity: Severity = Severity.WARN
    fix_cmd: str = ""
    platform: str = ""


@dataclass
class Resource:
    """A policy resource definition."""
    type: str
    path: str = ""
    applies_to: list = field(default_factory=list)
    entries: dict = field(default_factory=dict)
    after_change: dict = field(default_factory=dict)
    check_cmd: str = ""
    desired_output: str = ""
    fix_cmd: str = ""
    package: str = ""


@dataclass
class Policy:
    """A declarative remediation policy."""
    name: str
    description: str
    scope: list
    resources: list


@dataclass
class FleetResult:
    """Result of running a policy across the fleet."""
    policy: str
    mode: str
    duration: float
    hosts: list
    total: int = 0
    compliant: int = 0
    drift: int = 0
    fixed: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass
class VLAN:
    """A VLAN definition."""
    id: int
    name: str
    subnet: str
    prefix: str
    gateway: str = ""


@dataclass
class Distro:
    """A cloud image definition."""
    key: str
    name: str
    url: str
    filename: str
    sha_url: str = ""
    family: str = ""
    tier: str = "supported"
    aliases: list = field(default_factory=list)


@dataclass
class Container:
    """A Docker container in the fleet."""
    name: str
    vm_id: int
    port: int = 0
    api_path: str = ""
    auth_type: str = ""        # "header", "param", "cookie", ""
    auth_header: str = ""      # e.g. "X-Api-Key", "X-Plex-Token"
    auth_param: str = ""       # e.g. "apikey"
    vault_key: str = ""        # Key in FREQ vault for auth credential


@dataclass
class ContainerVM:
    """A VM hosting Docker containers."""
    vm_id: int
    ip: str
    label: str
    compose_path: str = ""
    containers: dict = field(default_factory=dict)  # name -> Container


@dataclass
class PhysicalDevice:
    """A physical infrastructure device (switch, iDRAC, firewall, NAS)."""
    key: str
    ip: str
    label: str
    device_type: str
    tier: str = "probe"
    detail: str = ""


@dataclass
class PVENode:
    """A Proxmox VE hypervisor node."""
    name: str
    ip: str
    detail: str = ""


@dataclass
class FleetBoundaries:
    """Fleet boundary definitions — the single source of truth for VM permissions.

    Loaded from conf/fleet-boundaries.toml. Determines what FREQ can do
    to each VM based on its category and permission tier.
    """
    tiers: dict = field(default_factory=dict)          # tier_name -> [allowed_actions]
    categories: dict = field(default_factory=dict)      # cat_name -> {description, tier, vmids?, range_start?, range_end?}
    physical: dict = field(default_factory=dict)         # device_key -> PhysicalDevice
    pve_nodes: dict = field(default_factory=dict)        # node_name -> PVENode

    def categorize(self, vmid: int) -> tuple:
        """Return (category_name, tier_name) for a VMID."""
        for name, cat in self.categories.items():
            if vmid in cat.get("vmids", []):
                return (name, cat.get("tier", "probe"))
            rs = cat.get("range_start")
            range_end = cat.get("range_end")
            if rs is not None and range_end is not None and rs <= vmid <= range_end:
                return (name, cat.get("tier", "probe"))
        return ("unknown", "probe")

    def allowed_actions(self, vmid: int) -> list:
        """Return list of allowed action strings for a VMID."""
        _, tier = self.categorize(vmid)
        return list(self.tiers.get(tier, ["view"]))

    def is_prod(self, vmid: int) -> bool:
        """True if this VMID belongs to a production category."""
        cat, _ = self.categorize(vmid)
        return cat in ("infrastructure", "prod_media", "prod_other")

    def is_protected(self, vmid: int) -> bool:
        """True if this VMID belongs to a category that should not be casually modified."""
        cat, _ = self.categorize(vmid)
        return cat in ("personal", "infrastructure", "prod_media", "prod_other")

    def can_action(self, vmid: int, action: str) -> bool:
        """Check if a specific action is allowed for a VMID."""
        return action in self.allowed_actions(vmid)

    def category_description(self, vmid: int) -> str:
        """Return human-readable description for a VMID's category."""
        cat_name, _ = self.categorize(vmid)
        cat = self.categories.get(cat_name, {})
        return cat.get("description", "Unknown")
