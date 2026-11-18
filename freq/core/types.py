"""Core data types for FREQ — the single source of truth for all structures.

Provides: Host, VLAN, Distro, CmdResult, Finding, Severity, Policy,
          FleetBoundaries, PhysicalDevice, PVENode, Monitor, Container, etc.

Every data structure in FREQ is defined here. No other file creates
dataclasses. This prevents circular imports and makes it trivial to find
any type definition — grep this one file.

Replaces: Scattered dicts and tuples across modules (error-prone, untyped)

Architecture:
    - All types are dataclasses with sensible defaults
    - Enums for finite sets (Severity, HostType)
    - FleetBoundaries is the nested config for VM categories and tiers
    - CmdResult wraps SSH command output (rc, stdout, stderr)

Design decisions:
    - ONE file for ALL types. Yes it's long. But "where is the Host type?"
      always has the same answer: freq/core/types.py. No hunting.
    - Dataclasses, not TypedDicts. IDE autocomplete, type checking, defaults.
    - Frozen where possible, mutable where SSH results need post-processing.
"""

from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field
from enum import Enum, auto
from types import MappingProxyType
from typing import Any, Mapping, Optional

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
    OPNSENSE = "opnsense"
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


# --- Core Data ---


@dataclass
class Host:
    """A fleet host."""

    ip: str
    label: str
    htype: str
    groups: str = ""
    vmid: int = 0
    managed: bool = True  # False = discovered but not deployed to (no service account)
    all_ips: list = field(default_factory=list)
    hostname: str = ""
    service_tag: str = ""
    identity_source: str = ""
    phase: Phase = Phase.PENDING
    current: dict = field(default_factory=dict)
    desired: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    error: str = ""
    duration: float = 0.0
    display_name: str = ""

    @property
    def category(self):
        """Device category (server, firewall, switch, bmc, nas)."""
        from freq.deployers import resolve_htype

        return resolve_htype(self.htype)[0]

    @property
    def vendor(self):
        """Device vendor (linux, pfsense, cisco, idrac, etc.)."""
        from freq.deployers import resolve_htype

        return resolve_htype(self.htype)[1]


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
    image: str = ""  # Docker image (e.g. "linuxserver/sonarr")
    status: str = ""  # Docker status (e.g. "running")
    api_path: str = ""
    auth_type: str = ""  # "header", "param", "cookie", ""
    auth_header: str = ""  # e.g. "X-Api-Key", "X-Plex-Token"
    auth_param: str = ""  # e.g. "apikey"
    vault_key: str = ""  # Key in FREQ vault for auth credential


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
    groups: str = ""
    scope: str = "core"
    hostname: str = ""
    service_tag: str = ""
    identity_source: str = ""
    display_name: str = ""


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

    tiers: dict = field(default_factory=dict)  # tier_name -> [allowed_actions]
    categories: dict = field(default_factory=dict)  # cat_name -> {description, tier, vmids?, range_start?, range_end?}
    physical: dict = field(default_factory=dict)  # device_key -> PhysicalDevice
    pve_nodes: dict = field(default_factory=dict)  # node_name -> PVENode

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
        """True if this VMID belongs to a production category.

        Matches both enum values (infrastructure, prod_media, prod_other) and
        the auto-categorized name 'production' from init's _categorize_vms.
        """
        cat, _ = self.categorize(vmid)
        return cat in (
            VMCategory.INFRASTRUCTURE.value, VMCategory.PROD_MEDIA.value,
            VMCategory.PROD_OTHER.value, "production",
        )

    def is_protected(self, vmid: int) -> bool:
        """True if this VMID belongs to a category that should not be casually modified."""
        cat, _ = self.categorize(vmid)
        return cat in (
            VMCategory.PERSONAL.value,
            VMCategory.INFRASTRUCTURE.value,
            VMCategory.PROD_MEDIA.value,
            VMCategory.PROD_OTHER.value,
            "production",
        )

    def can_action(self, vmid: int, action: str) -> bool:
        """Check if a specific action is allowed for a VMID."""
        return action in self.allowed_actions(vmid)

    def category_description(self, vmid: int) -> str:
        """Return human-readable description for a VMID's category."""
        cat_name, _ = self.categorize(vmid)
        cat = self.categories.get(cat_name, {})
        return cat.get("description", "Unknown")


@dataclass
class Monitor:
    """An HTTP endpoint to monitor."""

    name: str
    url: str
    interval: int = 60  # Check interval in seconds
    timeout: int = 10  # Request timeout in seconds
    expected_status: int = 200  # Expected HTTP status code
    method: str = "GET"  # HTTP method
    keyword: str = ""  # Optional keyword to look for in response body
    notify: bool = True  # Send notification on failure


# --- Init orchestration contracts ---


def _freeze_phase_payload(value):
    """Recursively detach supported container payloads for phase snapshots."""
    if isinstance(value, MappingABC):
        return MappingProxyType({key: _freeze_phase_payload(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_phase_payload(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_phase_payload(item) for item in value)
    return value


class PhaseStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class _InitCancellationBoundary(str, Enum):
    """Private execution-side classification around init's first mutation."""

    POINT_OF_NO_RETURN = "point_of_no_return"
    AFTER_POINT_OF_NO_RETURN = "after_point_of_no_return"


class _InitControlState(str, Enum):
    """Private durable states for pre-PONR cancellation arbitration."""

    PRE_PONR = "pre_ponr"
    CANCEL_REQUESTED = "cancel_requested"
    POINT_OF_NO_RETURN = "point_of_no_return"


@dataclass(frozen=True)
class PhaseIdentity:
    number: int
    key: str
    title: str

    def __post_init__(self):
        if not isinstance(self.number, int) or isinstance(self.number, bool) or self.number < 1:
            raise ValueError("phase number must be a positive integer")
        if not self.key or not self.key.strip():
            raise ValueError("phase key is required")
        if not self.title or not self.title.strip():
            raise ValueError("phase title is required")


@dataclass(frozen=True)
class PhaseInput:
    identity: PhaseIdentity
    context: Mapping[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    def __post_init__(self):
        if not isinstance(self.identity, PhaseIdentity):
            raise TypeError("phase input identity must be PhaseIdentity")
        if not isinstance(self.context, MappingABC):
            raise TypeError("phase input context must be a mapping")
        object.__setattr__(self, "context", _freeze_phase_payload(self.context))
        if not isinstance(self.dry_run, bool):
            raise TypeError("dry_run must be bool")


@dataclass(frozen=True)
class PhaseResult:
    identity: PhaseIdentity
    status: PhaseStatus
    error: Optional[str] = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.identity, PhaseIdentity):
            raise TypeError("phase result identity must be PhaseIdentity")
        if not isinstance(self.status, PhaseStatus):
            raise TypeError("phase result status must be PhaseStatus")
        if not isinstance(self.details, MappingABC):
            raise TypeError("phase result details must be a mapping")
        if self.status is PhaseStatus.FAILED and not str(self.error or "").strip():
            raise ValueError("failed phase result requires an error")
        if self.status is not PhaseStatus.FAILED and self.error is not None:
            raise ValueError("only failed phase results may carry an error")
        object.__setattr__(self, "details", _freeze_phase_payload(self.details))

    @classmethod
    def succeeded(cls, identity, *, details=None):
        return cls(identity, PhaseStatus.SUCCEEDED, details={} if details is None else details)

    @classmethod
    def failed(cls, identity, error, *, details=None):
        if error is None or not str(error).strip():
            raise ValueError("failed phase result requires an error")
        return cls(identity, PhaseStatus.FAILED, error=str(error), details={} if details is None else details)

    @classmethod
    def skipped(cls, identity, *, details=None):
        return cls(identity, PhaseStatus.SKIPPED, details={} if details is None else details)


@dataclass(frozen=True)
class InitPhase2ResumeProvenance:
    """Allowlisted non-secret identity for one headless Phase-2 checkpoint."""

    config_fingerprint: str
    bootstrap_user: str
    bootstrap_auth: str
    mode: str = "headless"
    version: int = 1

    def __post_init__(self):
        fingerprint = self.config_fingerprint
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise ValueError("config fingerprint must be 64 lowercase hexadecimal characters")
        if (
            not isinstance(self.bootstrap_user, str)
            or not self.bootstrap_user.strip()
            or self.bootstrap_user != self.bootstrap_user.strip()
        ):
            raise ValueError("bootstrap user must be a nonblank trimmed string")
        if self.bootstrap_auth not in {"key", "password"}:
            raise ValueError("bootstrap auth must be key or password")
        if self.mode != "headless":
            raise ValueError("Phase-2 resume provenance is headless-only")
        if type(self.version) is not int or self.version != 1:
            raise ValueError("Phase-2 resume provenance version must be 1")

    def to_payload(self):
        """Return the exact non-secret wire payload for this checkpoint identity."""
        return {
            "schema": "pve-freq-init-phase2-provenance-v1",
            "config_fingerprint": self.config_fingerprint,
            "bootstrap_user": self.bootstrap_user,
            "bootstrap_auth": self.bootstrap_auth,
            "mode": self.mode,
            "version": self.version,
        }

    @classmethod
    def from_payload(cls, payload):
        """Parse one exact provenance payload or fail closed."""
        expected_keys = {
            "schema",
            "config_fingerprint",
            "bootstrap_user",
            "bootstrap_auth",
            "mode",
            "version",
        }
        if (
            not isinstance(payload, MappingABC)
            or set(payload) != expected_keys
            or payload.get("schema") != "pve-freq-init-phase2-provenance-v1"
        ):
            raise ValueError("invalid Phase-2 resume provenance payload")
        return cls(
            config_fingerprint=payload["config_fingerprint"],
            bootstrap_user=payload["bootstrap_user"],
            bootstrap_auth=payload["bootstrap_auth"],
            mode=payload["mode"],
            version=payload["version"],
        )


INIT_PHASES = (
    PhaseIdentity(1, "prerequisites", "Prerequisites"),
    PhaseIdentity(2, "configure", "Cluster Configuration + VLAN Discovery"),
    PhaseIdentity(3, "service_account", "Service Account Setup"),
    PhaseIdentity(4, "ssh_keys", "SSH Key Generation"),
    PhaseIdentity(5, "pve_deploy", "PVE Node Deployment"),
    PhaseIdentity(6, "pve_api_token", "PVE API Token"),
    PhaseIdentity(7, "fleet_discover", "Fleet Discovery"),
    PhaseIdentity(8, "fleet_deploy", "Fleet Deployment"),
    PhaseIdentity(9, "fleet_configure", "Fleet Configuration"),
    PhaseIdentity(10, "pdm", "PDM Setup"),
    PhaseIdentity(11, "admin_setup", "Admin Account Setup"),
    PhaseIdentity(12, "verify", "Verification"),
    PhaseIdentity(13, "summary", "Summary"),
)


def phase_catalog(*, include_summary=True):
    """Return the immutable phase catalog used by interactive init."""
    return INIT_PHASES if include_summary else INIT_PHASES[:-1]


def _init_cancellation_boundary(identity):
    """Classify one canonical phase against init's fail-closed PONR.

    Phase 1 may install packages and seed live configuration, so execution has
    crossed the point of no return when that phase begins. Cancellation before
    Phase 1 is run-level state and deliberately is not represented by a phase
    identity. Equal-but-foreign identities fail closed instead of inheriting a
    policy merely because their fields resemble the canonical catalog.
    """
    if not isinstance(identity, PhaseIdentity):
        raise TypeError("init cancellation policy requires PhaseIdentity")
    for index, canonical in enumerate(INIT_PHASES):
        if identity is canonical:
            return (
                _InitCancellationBoundary.POINT_OF_NO_RETURN
                if index == 0
                else _InitCancellationBoundary.AFTER_POINT_OF_NO_RETURN
            )
    raise ValueError("init cancellation policy requires a canonical phase identity")
