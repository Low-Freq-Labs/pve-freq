"""Core data types for the FREQ engine.

Every data structure used in the engine lives here. No other file defines dataclasses.
"""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Any


class Phase(Enum):
    """Host remediation phase."""
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


@dataclass
class Host:
    """A fleet host."""
    ip: str
    label: str
    htype: str  # linux, pve, truenas, pfsense, idrac, switch
    groups: str = ""
    phase: Phase = Phase.PENDING
    current: dict = field(default_factory=dict)
    desired: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    error: str = ""
    duration: float = 0.0


@dataclass
class CmdResult:
    """Result of an SSH command."""
    stdout: str
    stderr: str
    returncode: int
    duration: float


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
    type: str  # file_line, middleware_config, command_check, package_ensure
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
    scope: list  # Host types this applies to
    resources: list  # List of Resource objects


@dataclass
class FleetResult:
    """Result of running a policy across the fleet."""
    policy: str
    mode: str  # check, fix, diff
    duration: float
    hosts: list  # List of Host objects
    total: int = 0
    compliant: int = 0
    drift: int = 0
    fixed: int = 0
    failed: int = 0
    skipped: int = 0
