<!-- INTERNAL — Not for public distribution -->

# SOURCE CODE STANDARDS

**The Standard Every File in PVE FREQ Must Meet**

**Author:** Morty (Lead Dev)
**Created:** 2026-04-01
**Rule:** Every file. No exceptions. No "I'll add notes later." If the file exists, it meets this standard.

---

## THE PRINCIPLE

When a developer opens any file in pve-freq, they should believe a team of 10 engineers built this. They should think getting a spot on the pve-freq team would be like hitting the lottery. They should study the source code like a textbook.

Two people built this. The code should look like twenty did.

---

## THE FILE HEADER

Every `.py` file starts with a **module docstring**. This is the first thing anyone reads. It must answer five questions in under 15 lines:

1. **What is this file?** — One sentence.
2. **What commands/features does it provide?** — The user-facing surface.
3. **What does it replace?** — What enterprise tool this makes unnecessary, and what that tool costs.
4. **How does it connect?** — What core systems it uses (SSH transport, policy engine, deployer registry, etc.)
5. **Key design decisions** — Why it's built this way, not another way.

### Template

```python
"""Fleet-wide reverse proxy management for FREQ.

Domain: freq proxy <status|list|add|remove|health|drain>

Detects which proxy backend is running (Nginx Proxy Manager, Caddy, Traefik,
HAProxy) and uses the correct API. Users manage routes — FREQ handles the
backend differences.

Replaces: Nginx Proxy Manager GUI ($0 but GUI-only), Traefik Enterprise ($2K/yr)

Architecture:
    - Uses urllib.request (stdlib) to hit proxy backend REST APIs
    - Route state persisted in conf/proxy/routes.json
    - Auto-detection via SSH port/process scanning on fleet hosts
    - Certificate status pulled from freq/modules/cert.py inventory

Design decisions:
    - Backend is an implementation detail, not a user concern. freq proxy add
      works the same whether NPM or Caddy is behind it.
    - Routes stored locally even if the proxy has its own state, so freq is
      the source of truth and can detect drift.
"""
```

### What Makes a Good Header vs a Bad One

**Bad:**
```python
"""Proxy module for FREQ.

Handles proxy stuff.
"""
```

**Bad:**
```python
"""
This module provides functionality for managing reverse proxy configurations
across the fleet of managed hosts. It supports multiple backend proxy
implementations including Nginx Proxy Manager, Caddy, Traefik, and HAProxy.

The module exposes several commands through the CLI framework...
[30 more lines of filler]
"""
```

**Good:**
```python
"""Fleet-wide TLS certificate inventory and lifecycle for FREQ.

Domain: freq cert <inventory|inspect|issue|renew|deploy|ca|audit>

Scans every fleet host for TLS certificates on common ports. Tracks expiry.
Issues certs via ACME (Let's Encrypt) or private CA (step-ca). Deploys to
Proxmox, pfSense, nginx, or any SSH-reachable host. One command to know
every cert in your infrastructure and when it dies.

Replaces: Manual cert tracking in spreadsheets, certbot cron scripts,
           Let's Encrypt GUIs ($0 but no fleet awareness)

Architecture:
    - Scanning uses ssl + socket (stdlib) to connect and read certs
    - ACME issuance shells to certbot or speaks ACME protocol via urllib
    - Private CA shells to step-ca CLI
    - Deployment uses freq/core/ssh.py to SCP certs to targets
    - Inventory persisted in conf/certs/cert-inventory.json
    - Integrates with freq/modules/proxy.py for proxy cert status
"""
```

The good header tells you what, why, how, and what it replaces — in the time it takes to read a paragraph. A new developer can understand this file's purpose without reading a single line of code.

---

## THE UPDATE RULE

**Every time a file is edited — no matter how small the change — the header must be verified as 100% accurate after the edit.**

This is the rule. It's non-negotiable.

Sometimes you change one line of code and the header is still perfectly accurate. Great — you verified it, you move on. Takes 10 seconds.

Sometimes you add a new command and the domain line in the header is now missing an action. You update it. Takes 30 seconds.

Sometimes you refactor how the module connects to core and the architecture section is now wrong. You rewrite that section. Takes 2 minutes.

The cost of maintaining headers is trivial. The cost of stale headers is enormous — they mislead every future developer (including future-you) who trusts them.

**If you touch the code, you touch the header.** Period.

---

## INLINE COMMENTS

### When to Comment

Comment **why**, never **what**. The code says what. Comments say why.

**Bad — commenting the what:**
```python
# Increment counter
counter += 1

# Check if host is reachable
if host.status == "up":

# Loop through all VMs
for vm in vms:
```

**Good — commenting the why:**
```python
# SSH multiplexing reuses connections for 5 minutes — without this,
# fleet operations on 14 hosts take 30s instead of 2.7s
MUX_PERSIST_SECONDS = 300

# pfSense uses tcsh as root shell and has no bash — POSIX sh only
# for all remote commands. This is NOT the same as Linux targets.
PFSENSE_SHELL = "/bin/sh"

# iDRAC and Cisco IOS don't support ed25519 keys — they need RSA.
# This is a hardware/firmware limitation, not a config choice.
LEGACY_HTYPES = {"idrac", "switch"}
```

### When NOT to Comment

Don't comment obvious code. Don't comment standard patterns. Don't comment self-documenting names.

```python
# No comment needed — the code IS the documentation:
def get_fleet_hosts(cfg: FreqConfig) -> list[Host]:
    return [h for h in cfg.hosts if h.status == "up"]

# No comment needed — the function name says everything:
def is_systemd_active() -> bool:
    return os.path.isdir("/run/systemd/system")
```

### Magic Numbers and Thresholds

Every magic number gets a named constant with a comment explaining the value:

```python
# CIS Benchmark 5.2.20 recommends MaxAuthTries <= 4
SSH_MAX_AUTH_TRIES = 4

# Alert if disk usage exceeds this — 90% leaves enough room for
# log rotation and emergency operations without filling up
DISK_CRITICAL_PERCENT = 90

# SMART attribute ID 5 (Reallocated Sector Count) is the #1 predictor
# of imminent drive failure per Backblaze annual drive stats
SMART_REALLOCATED_SECTORS_ID = 5

# pfSense API rate limit — empirically determined, not documented.
# Hit it harder than this and pfSense returns 429s.
PFSENSE_API_DELAY_MS = 200
```

---

## FUNCTION DOCUMENTATION

### Public Functions (Called by Other Modules or the CLI)

Every public function gets a docstring that states:
1. What it does (one sentence)
2. What it returns
3. Side effects (if any — file writes, SSH calls, API calls)

```python
def cmd_cert_inventory(cfg: FreqConfig, pack, args) -> int:
    """Scan all fleet hosts for TLS certificates and display inventory.

    Returns: 0 on success, 1 on failure.
    Side effects: Updates conf/certs/cert-inventory.json with scan results.
    SSH calls: Connects to each fleet host on common HTTPS ports.
    """
```

### Private Functions (Internal to the Module)

Private functions (prefixed with `_`) get a one-line docstring if the name isn't self-explanatory:

```python
def _parse_cisco_vlan_output(raw: str) -> list[dict]:
    """Parse 'show vlan brief' output into structured VLAN list."""

def _resolve_ntp_provider(platform: RemotePlatform) -> str:
    """Detect whether target uses chrony, ntpd, or systemd-timesyncd."""
```

If the function name already says everything, skip the docstring:

```python
def _load_json(filepath: str) -> dict:
    # Name says it all — no docstring needed
    try:
        with open(filepath) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
```

---

## SECTION SEPARATORS

Long modules (300+ lines) use section comments to create a table of contents:

```python
# ─────────────────────────────────────────────────────────────
# SWITCH GETTERS — Vendor-agnostic data retrieval
# ─────────────────────────────────────────────────────────────

def get_facts(target, cfg): ...
def get_interfaces(target, cfg): ...
def get_vlans(target, cfg): ...

# ─────────────────────────────────────────────────────────────
# PORT MANAGEMENT — Per-port configuration
# ─────────────────────────────────────────────────────────────

def configure_port(target, port, cfg, **kwargs): ...
def set_port_description(target, port, desc, cfg): ...

# ─────────────────────────────────────────────────────────────
# CONFIG BACKUP — Oxidized-style config versioning
# ─────────────────────────────────────────────────────────────

def backup_config(target, cfg): ...
def diff_config(target, cfg): ...
```

A developer can scroll through a 500-line file and understand its structure in 5 seconds from the section headers alone.

---

## CONSTANTS AND CONFIGURATION

### At the Top, After Imports

Every module's constants and configuration values live immediately after imports, before any functions:

```python
"""Module docstring..."""

import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

# Timeouts (seconds)
CMD_TIMEOUT = 15              # Standard SSH command timeout
SCAN_TIMEOUT = 5              # TLS connect timeout for cert scanning
SNMP_TIMEOUT = 10             # SNMP poll timeout

# Storage
DATA_DIR = "certs"            # Subdirectory under conf/ for this module's data
INVENTORY_FILE = "cert-inventory.json"

# Thresholds
EXPIRY_CRITICAL_DAYS = 7      # Red alert — cert expires within a week
EXPIRY_WARNING_DAYS = 30      # Yellow warning — cert expires within a month

# Ports to scan for TLS certificates
DEFAULT_TLS_PORTS = [443, 8443, 8006, 8888, 9090, 3000, 8080]
```

### No Unnamed Constants in Code

**Bad:**
```python
if days_remaining < 7:
    severity = "critical"
elif days_remaining < 30:
    severity = "warning"
```

**Good:**
```python
if days_remaining < EXPIRY_CRITICAL_DAYS:
    severity = "critical"
elif days_remaining < EXPIRY_WARNING_DAYS:
    severity = "warning"
```

---

## ERROR HANDLING PATTERNS

### User-Facing Errors

When a command fails, the user sees:
1. What went wrong (one line)
2. Why it might have happened (one line)
3. What to do about it (one line)

```python
if not cfg.pfsense_ip:
    fmt.error("pfSense IP not configured")
    fmt.info("Set the IP in freq.toml: [infrastructure] pfsense_ip = \"10.x.x.x\"")
    fmt.info("Or run: freq configure")
    return 1
```

Never show raw tracebacks to users. Never show "an error occurred." Never show the error without telling them what to do next.

### Internal Errors

Use the logger for internal diagnostics. Users don't see these unless `--debug` is on:

```python
from freq.core import log as logger

try:
    result = ssh_run(host, cmd, cfg)
except Exception as e:
    logger.error(f"SSH to {host.label} failed: {e}")
    fmt.error(f"Cannot reach {host.label} — check SSH connectivity")
    fmt.info(f"Test with: freq host test {host.label}")
    return 1
```

---

## IMPORT ORDER

Follow this order, separated by blank lines:

```python
# 1. Standard library
import json
import os
import re
import time
from typing import Optional

# 2. FREQ core
from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run, run_many as ssh_run_many

# 3. FREQ modules (if cross-referencing — avoid when possible)
from freq.modules.cert import get_cert_inventory
```

No blank lines within a group. One blank line between groups. Alphabetical within each group.

---

## FILE NAMING

| Type | Convention | Example |
|---|---|---|
| Module (CLI command) | `snake_case.py` matching the domain | `switch_orchestration.py`, `event_network.py` |
| Core library | `snake_case.py` | `platform.py`, `services.py`, `packages.py` |
| Deployer | `vendor_name.py` in category directory | `deployers/switch/cisco.py` |
| Policy | `policy_name.py` | `engine/policies/ntp_sync.py` |
| Jarvis module | `feature_name.py` | `jarvis/chaos.py`, `jarvis/notify.py` |
| Test | `test_<module>.py` | `tests/test_switch_orchestration.py` |
| Config | `name.toml` or `name.conf` | `conf/switch-profiles.toml` |

---

## DEPLOYER DOCUMENTATION

Every deployer file documents the device it manages:

```python
"""Cisco IOS/IOS-XE switch deployer for FREQ.

Vendor: Cisco
Platforms: Catalyst 9200/9300/9500, ISR, ASR, legacy 2960/3750/4948
OS: IOS 15.x, IOS-XE 16.x/17.x
Auth: SSH with RSA key (ed25519 not supported on IOS). Password auth for
      initial deployment, key auth after.
Transport: SSH with legacy ciphers — requires diffie-hellman-group14-sha1
           and ssh-rsa (see freq/core/ssh.py LEGACY_HTYPES)

Getter interface:
    get_facts()        → show version (parse hostname, model, serial, uptime)
    get_interfaces()   → show interfaces status (parse name, status, speed, duplex)
    get_vlans()        → show vlan brief (parse id, name, ports)
    get_mac_table()    → show mac address-table (parse mac, vlan, port)
    get_arp_table()    → show ip arp (parse ip, mac, interface)
    get_neighbors()    → show cdp neighbors detail (parse device, port, ip)
    get_config()       → show running-config
    get_environment()  → show environment all (parse temp, fans, psu)

Setter interface:
    push_config(lines) → configure terminal, lines, end, write memory
    save_config()      → write memory

Known quirks:
    - IOS returns garbage exit codes. Parse output for '% Invalid' patterns.
    - 'terminal length 0' must be sent before show commands to disable paging.
    - Config mode requires 'configure terminal' entry and 'end' exit.
    - 'write memory' (not 'copy run start') for config save on older IOS.
"""

CATEGORY = "switch"
VENDOR = "cisco"
NEEDS_PASSWORD = True
NEEDS_RSA = True
```

A developer who has never touched a Cisco switch reads this header and knows exactly how to work with the code. Every quirk. Every gotcha. Every command mapping.

---

## CONFIGURATION FILE DOCUMENTATION

TOML config files document every field:

```toml
# freq.toml — PVE FREQ Configuration
#
# This file is created by 'freq init' and can be edited manually or
# via 'freq configure'. All fields have safe defaults — if a field is
# missing or invalid, FREQ falls back to the default without crashing.
#
# Paths: relative paths are relative to the conf/ directory.
# Secrets: NEVER put passwords or tokens in this file. Use freq vault
#          or reference a credential file path.

[freq]
version = "3.0.0"            # Target version — update on release
brand = "PVE FREQ"            # Branding shown in headers and dashboard
build = "default"              # Personality pack: "default" or "personal"
ascii = false                  # true = ASCII-only output (PuTTY-safe, no Unicode)
debug = false                  # true = verbose logging to conf/logs/

[ssh]
service_account = "freq-admin" # Account FREQ uses to SSH into fleet hosts.
                                # Created by 'freq init'. Do NOT set to your
                                # personal account or the bootstrap account.
connect_timeout = 5            # Seconds to wait for SSH connection. Increase
                                # for high-latency networks (VPN, WAN).
max_parallel = 5               # Max concurrent SSH sessions for fleet ops.
                                # Higher = faster but more load on targets.
mode = "sudo"                  # "sudo" = SSH as service_account + sudo
                                # "root" = SSH directly as root (not recommended)
```

Every field has a comment. Not just what it is — what it means, when to change it, what breaks if you set it wrong.

---

## TEST FILE DOCUMENTATION

Test files document what they test and why:

```python
"""Tests for freq net switch — switch orchestration commands.

Tests the vendor-agnostic getter interface by mocking SSH responses
from Cisco, Juniper, and Aruba switches. Verifies that:
1. Each vendor's raw CLI output parses into the same structured format
2. Port range expansion works (Gi1/1-24 → 24 individual ports)
3. Profile TOML loading and validation
4. Config backup creates correctly named files
5. Config diff detects changes

Does NOT test live SSH to real switches — that's E2E testing (Phase 12).
"""
```

---

## THE CHECKLIST

Before any file is committed, it must pass this checklist:

- [ ] **Header docstring** exists and answers the 5 questions
- [ ] **Header is accurate** after the changes in this commit
- [ ] **Constants** are named and documented at the top, not magic numbers in code
- [ ] **Public functions** have docstrings
- [ ] **Comments explain WHY**, not WHAT
- [ ] **Errors** tell the user what happened, why, and what to do
- [ ] **Imports** follow the standard order
- [ ] **Section separators** exist if the file is 300+ lines
- [ ] **No hardcoded distro assumptions** — uses abstraction layers
- [ ] **No DC01-specific values** in code — all in config

---

## WHY THIS MATTERS

Source code is read 10x more than it's written. Every hour spent on clear documentation saves 10 hours of "what does this do?" from future developers — including future us.

When FREQ goes public, the source code IS the resume. People will judge the project by opening a random file. If that file has a clear header, clean structure, meaningful comments, and professional organization — they trust the whole project. If that file has `# TODO: fix this later` and unnamed constants and no documentation — they close the tab.

We are building something that makes enterprise tools look lazy. The code should look the part.
