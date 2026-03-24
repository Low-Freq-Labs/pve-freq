# PVE FREQ Overnight Edge Case Matrix

**Purpose:** Hammer every code path with non-DC01 configurations to find crashes, wrong behavior, and confusing output.
**Method:** For each test, simulate the config state by creating temporary freq.toml/hosts.conf variants and calling the Python functions directly (no SSH needed — we mock or skip network calls).

---

## Config Profiles (test each command against ALL of these)

### Profile A: "Bare Metal Baby"
- 1 PVE node: `proxmox1` at `192.168.1.10`
- 0 VLANs (flat network)
- 0 hosts in hosts.conf
- No pfSense, no TrueNAS, no iDRAC, no switch
- Service account: `admin`
- Storage: `local-lvm`
- Network: `192.168.1.0/24`
- Gateway: `192.168.1.1`
- Domain: `home.lab`
- Personality: `default`
- No risk.toml

### Profile B: "Big Boy /16"
- 3 PVE nodes: `node1`, `node2`, `node3` at `10.0.1.1`, `10.0.1.2`, `10.0.1.3`
- 4 VLANs with /16 subnets (10.0.0.0/16, 10.1.0.0/16, etc.)
- 12 hosts across multiple types
- pfSense at `10.0.0.1`, TrueNAS at `10.0.1.100`
- Service account: `pveadmin`
- Gateway: `10.0.0.1`
- Domain: `corp.internal`
- Personality: `default`
- Has risk.toml with custom topology

### Profile C: "Ghost Town"
- 0 PVE nodes (empty list)
- 0 VLANs
- 0 hosts
- All infrastructure IPs empty
- Service account: `freq-admin` (default)
- Gateway: empty string
- Domain: `cluster.local` (default)
- No personality pack files at all
- No risk.toml, no knowledge files

### Profile D: "IPv6 Curious /23"
- 1 PVE node at `172.16.0.5`
- 2 VLANs with /23 subnets (`172.16.0.0/23`, `172.16.2.0/23`)
- 5 hosts
- Gateway: `172.16.0.1`
- No pfSense (using OPNsense — not in config)
- Storage: `ceph-pool` (not local-lvm)
- Service account: `root`

### Profile E: "DC01 Regression"
- Exact DC01 config (current conf/freq.toml)
- Verify everything still works identically
- This is the regression guard

---

## Test Matrix

### TIER 1: Config Loading (Profile A-D)

| # | Test | Method | Expected | Owner |
|---|------|--------|----------|-------|
| 1.1 | Load config with empty freq.toml | `load_config()` with minimal TOML | Returns FreqConfig with defaults, no crash | Rick |
| 1.2 | Load config with missing freq.toml | Delete freq.toml, call `load_config()` | Returns defaults, warns | Rick |
| 1.3 | Load config with missing vlans.toml | No vlans.toml file | `cfg.vlans = []`, no crash | Rick |
| 1.4 | Load config with missing hosts.conf | No hosts.conf file | `cfg.hosts = []`, no crash | Rick |
| 1.5 | Load config with /16 VLANs | Profile B vlans.toml | Parses correctly, cidr="16" | Rick |
| 1.6 | Load config with /23 VLANs | Profile D vlans.toml | Parses correctly, cidr="23" | Rick |
| 1.7 | Load config with unknown personality | `build = "nonexistent"` | Falls back to defaults, no crash | Rick |
| 1.8 | Load config with empty pve_nodes | `nodes = []` | `cfg.pve_nodes = []`, no crash | Rick |
| 1.9 | Load config with custom storage pool names | `pool = "ceph-pool"` | Parses correctly | Rick |
| 1.10 | Load config with service_account = "root" | Profile D | `cfg.ssh_service_account = "root"` | Rick |

### TIER 2: CLI Commands — Empty State (Profile C)

| # | Test | Command Simulated | Expected | Owner |
|---|------|-------------------|----------|-------|
| 2.1 | `freq version` | `cmd_version(cfg, pack, args)` | Prints version, no crash | Morty |
| 2.2 | `freq doctor` | `cmd_doctor(cfg, pack, args)` | Reports missing items as warnings, returns 0 or 1 | Morty |
| 2.3 | `freq status` | `cmd_status(cfg, pack, args)` | "No hosts registered", returns 0 | Morty |
| 2.4 | `freq hosts list` | `cmd_hosts(cfg, pack, args)` | "No hosts", returns 0 | Morty |
| 2.5 | `freq health` | `cmd_health(cfg, pack, args)` | "No hosts registered", returns 0 | Morty |
| 2.6 | `freq risk all` | `cmd_risk(cfg, pack, args)` | "No risk map configured", returns 0 | Morty |
| 2.7 | `freq learn nfs` | `cmd_learn(cfg, pack, args)` | Returns results from default knowledge, or "no results" | Morty |
| 2.8 | `freq configure` | `cmd_configure(cfg, pack, args)` | Shows current config, no crash | Morty |
| 2.9 | `freq distros` | `cmd_distros(cfg, pack, args)` | Shows distros or empty list | Morty |
| 2.10 | `freq pfsense` | `cmd_pfsense(cfg, pack, args)` | "pfSense not configured", returns 1 | Morty |
| 2.11 | `freq truenas` | `cmd_truenas(cfg, pack, args)` | "TrueNAS not configured", returns 1 | Morty |
| 2.12 | `freq switch` | `cmd_switch(cfg, pack, args)` | "Switch not configured", returns 1 | Morty |
| 2.13 | `freq idrac` | `cmd_idrac(cfg, pack, args)` | "iDRAC not configured", returns 1 | Morty |
| 2.14 | `freq media status` | `cmd_media(cfg, pack, args)` | "No container VMs configured", returns 0 | Morty |
| 2.15 | `freq lab` | `cmd_lab(cfg, pack, args)` | "No lab hosts found", returns 0 | Morty |
| 2.16 | `freq vault list` | `cmd_vault(cfg, pack, args)` | "Vault not initialized" or empty list | Morty |
| 2.17 | `freq groups` | `cmd_groups(cfg, pack, args)` | "No groups" or empty | Morty |
| 2.18 | `freq journal` | `cmd_journal(cfg, pack, args)` | Empty or "no entries" | Morty |

### TIER 3: CLI Commands — Single Node (Profile A)

| # | Test | What We're Checking | Expected | Owner |
|---|------|---------------------|----------|-------|
| 3.1 | `freq vm create` with 1 node | Does it find the single node? | Creates on the only node | Rick |
| 3.2 | `freq vm clone` | Clone on single-node cluster | Works, no multi-node assumptions | Rick |
| 3.3 | `freq vm migrate` | Migrate with only 1 node | "No other nodes available" or similar | Rick |
| 3.4 | `freq discover` | Discover with 1 node | Queries that node, returns VMs | Rick |
| 3.5 | `freq list` | PVE list with 1 node | Shows VMs from that node | Rick |
| 3.6 | `freq snapshot` | Snapshot on single node | Works normally | Rick |
| 3.7 | `freq vm destroy` | Destroy with single node | Works, finds node | Rick |
| 3.8 | `freq init --dry-run` | With 1 PVE node, 0 hosts | Shows correct plan | Rick |
| 3.9 | `freq init --check` | Check on bare system | Reports status accurately | Rick |
| 3.10 | `freq risk all` with custom risk.toml | Profile A risk.toml | Shows custom chain + targets | Rick |

### TIER 4: Dashboard API — Edge Cases (Profile A, C, D)

| # | Endpoint | Config Profile | What We're Checking | Owner |
|---|----------|---------------|---------------------|-------|
| 4.1 | `/api/fleet/overview` | C (empty) | Empty vms, empty physical, empty vlans | Morty |
| 4.2 | `/api/fleet/overview` | A (1 node) | Single node, no VLANs in response | Morty |
| 4.3 | `/api/fleet/overview` | D (/23 subnets) | VLAN cidr="23" in response | Morty |
| 4.4 | `/api/info` | C (no personality) | Falls back to "PVE FREQ Dashboard" | Morty |
| 4.5 | `/api/info` | A (default pack) | Shows default pack values | Morty |
| 4.6 | `/api/config` | C (empty) | Returns defaults, kill_chain = generic fallback | Morty |
| 4.7 | `/api/config` | A (with risk.toml) | Returns custom kill_chain | Morty |
| 4.8 | `/api/risk` | C (no risk.toml) | Returns empty targets, empty chain | Morty |
| 4.9 | `/api/risk` | A (custom risk.toml) | Returns custom targets | Morty |
| 4.10 | `/api/status` | C (no hosts) | Empty or graceful response | Morty |
| 4.11 | `/api/health` | C (no hosts) | Empty results | Morty |
| 4.12 | `/api/learn?q=nfs` | A (default knowledge) | Returns results | Morty |
| 4.13 | `/api/learn?q=nfs` | C (no knowledge files) | Returns empty or creates DB | Morty |
| 4.14 | `/api/media/status` | C (no containers) | `{"containers":[],"count":0}` | Morty |
| 4.15 | `/api/pfsense` | C (no pfSense IP) | Graceful error, not crash | Morty |
| 4.16 | `/api/truenas` | C (no TrueNAS IP) | Graceful error, not crash | Morty |
| 4.17 | `/api/vm/create` | C (no PVE nodes) | Error: "no PVE nodes configured" | Morty |
| 4.18 | `/api/infra/overview` | C (empty) | Empty infra dict (no pfSense/TrueNAS keys) | Morty |
| 4.19 | `/api/infra/overview` | A (1 node) | Only hosts from config | Morty |
| 4.20 | `/api/vm/add-nic` | D (/23 subnet) | Uses /23 not /24 | Morty |
| 4.21 | `/api/vm/change-ip` | D (/23 subnet) | Uses /23 not /24 | Morty |

### TIER 5: JavaScript Rendering (Profile A, C, D)

| # | Component | Config Profile | What We're Checking | Owner |
|---|-----------|---------------|---------------------|-------|
| 5.1 | Kill chain display | C (no chain) | Generic fallback renders | Rick |
| 5.2 | Kill chain display | A (custom chain) | Custom chain from API | Rick |
| 5.3 | NODE_COLORS | A (1 node) | Single node gets color | Rick |
| 5.4 | NODE_COLORS | C (0 nodes) | Empty object, no crash | Rick |
| 5.5 | VLAN_COLORS | C (0 VLANs) | Empty object, no crash | Rick |
| 5.6 | VLAN_COLORS | D (2 VLANs) | Both get colors | Rick |
| 5.7 | NIC combo builder | C (0 VLANs) | Shows "Default" option | Rick |
| 5.8 | NIC combo builder | A (0 VLANs) | Shows "Default" option | Rick |
| 5.9 | NIC combo builder | D (2 VLANs, /23) | Shows both VLANs, uses /23 | Rick |
| 5.10 | VM detail panel | C (no VLAN data) | Renders without crash | Rick |
| 5.11 | VM detail panel | D (non-/24 network) | Shows correct cidr | Rick |
| 5.12 | Gateway display | A (no VLANs) | Shows `?` or configured gateway | Rick |
| 5.13 | Gateway display | D (/23, gw=172.16.0.1) | Shows correct gateway from VLAN config | Rick |
| 5.14 | Credits/footer | A (default pack) | "PVE FREQ" not "LOW FREQ Labs" | Rick |
| 5.15 | Search placeholder | All | "knowledge base" not "154 sessions" | Rick |
| 5.16 | Lab detection | A (no lab VMs) | No lab section, no crash | Rick |
| 5.17 | PROD_HOSTS / PROD_VMS | C (empty fleet) | Empty arrays, no crash | Rick |

### TIER 6: VM Operations — Network Edge Cases

| # | Test | Input | Expected | Owner |
|---|------|-------|----------|-------|
| 6.1 | Create VM with empty gateway | `cfg.vm_gateway = ""` | Falls back to DHCP or warns | Rick |
| 6.2 | Clone VM with IP including /23 | `ip_addr = "172.16.0.50/23"` | Uses /23, doesn't append /24 | Rick |
| 6.3 | Clone VM with bare IP | `ip_addr = "172.16.0.50"` | Appends /24 as fallback | Rick |
| 6.4 | Sandbox VM with IP including prefix | `ip_addr = "10.0.5.10/16"` | Uses /16, doesn't double-append | Rick |
| 6.5 | Sandbox VM with bare IP | `ip_addr = "10.0.5.10"` | Appends /24 | Rick |
| 6.6 | Create VM with custom CPU type | `cfg.vm_cpu = "host"` | Uses "host" not "kvm64" | Morty |
| 6.7 | Create VM with custom bridge | `cfg.nic_bridge = "vmbr1"` | Uses vmbr1 not vmbr0 | Morty |
| 6.8 | Create VM with custom scsihw | `cfg.vm_scsihw = "lsi"` | Uses lsi not virtio-scsi-single | Morty |
| 6.9 | Provision agent with custom nameserver | `cfg.vm_nameserver = "192.168.1.1"` | Uses 192.168.1.1 not 1.1.1.1 | Morty |
| 6.10 | Create VM, storage fallback | No pve_storage configured | Uses "local-lvm" | Morty |

### TIER 7: Personality System

| # | Test | Input | Expected | Owner |
|---|------|-------|----------|-------|
| 7.1 | Load default pack | `build = "default"` | Loads default.toml, neutral values | Rick |
| 7.2 | Load personal pack | `build = "personal"` | Loads personal.toml, DC01-specific OK | Rick |
| 7.3 | Load nonexistent pack | `build = "enterprise"` | Falls back to defaults, no crash | Rick |
| 7.4 | Load with missing personality dir | No `conf/personality/` | Falls back to hardcoded defaults | Rick |
| 7.5 | Celebrate with None pack | `celebrate(pack=None)` | No crash (was a bug, verify fixed) | Rick |
| 7.6 | Splash with default pack | `splash(pack, version)` | Shows "PVE FREQ" subtitle | Rick |
| 7.7 | Splash with personal pack | `splash(pack, version)` | Shows "LOW FREQ Labs" subtitle | Rick |
| 7.8 | Dashboard header via API | `/api/info` with default | `"PVE FREQ Dashboard"` | Rick |
| 7.9 | Dashboard header via API | `/api/info` with personal | `"LOW FREQ Labs Dashboard"` | Rick |

### TIER 8: SSH System

| # | Test | Input | Expected | Owner |
|---|------|-------|----------|-------|
| 8.1 | `get_platform_ssh("linux", cfg)` | `cfg.ssh_service_account = "admin"` | Returns `user: "admin"` | Morty |
| 8.2 | `get_platform_ssh("linux", None)` | No cfg | Returns `user: "freq-admin"` (fallback) | Morty |
| 8.3 | `get_platform_ssh("idrac", cfg)` | With legacy_password_file | Includes password_file | Morty |
| 8.4 | `get_platform_ssh("idrac", cfg)` | Without legacy_password_file | No password_file | Morty |
| 8.5 | `PLATFORM_SSH` module-level dict | Import ssh.py | Dict exists, uses fallback user | Morty |
| 8.6 | `_resolve_legacy_key()` | ed25519 key path | Finds sibling RSA key | Morty |
| 8.7 | `_resolve_legacy_key()` | RSA key path | Returns same path | Morty |

### TIER 9: Regression — DC01 (Profile E)

| # | Test | Expected | Owner |
|---|------|----------|-------|
| 9.1 | `freq status` | Same output as before overhaul | Morty |
| 9.2 | `freq risk all` | Shows DC01 topology from risk.toml | Morty |
| 9.3 | `freq risk pfsense` | Shows pfSense detail | Morty |
| 9.4 | `freq learn nfs` | Returns NFS lessons | Morty |
| 9.5 | `freq doctor` | All checks pass | Morty |
| 9.6 | `freq configure` | Shows DC01 config values | Morty |
| 9.7 | Dashboard `/api/info` | Shows "LOW FREQ Labs Dashboard" (personal pack) | Morty |
| 9.8 | Dashboard `/api/config` | kill_chain = DC01 chain from risk.toml | Morty |
| 9.9 | Dashboard `/api/fleet/overview` | VLANs have cidr="24" | Morty |
| 9.10 | `freq vm create` args | Uses x86-64-v2-AES and vmbr0 (from DC01 freq.toml) | Morty |

---

## Execution Method

### For Python-level tests (Tiers 1-3, 6-8):
```python
# Create temporary config state
import sys, os, tempfile
sys.path.insert(0, "/home/freq-ops/dev-ops/rick")

# Build a test config directory with the profile's files
# Call functions directly with mock args
# Check return codes and output
```

### For API tests (Tier 4):
```python
# Start serve.py with test config
# Use urllib to hit each endpoint
# Parse JSON responses
# Verify no crashes, correct structure
```

### For JS tests (Tier 5):
- Read the JS source, trace logic with test data
- Verify variable assignments produce correct values
- Check for undefined/null access with empty data

---

## Work Split

| Tier | Rick | Morty |
|------|------|-------|
| 1. Config Loading | ALL (1.1-1.10) | — |
| 2. CLI Empty State | — | ALL (2.1-2.18) |
| 3. CLI Single Node | ALL (3.1-3.10) | — |
| 4. Dashboard API | — | ALL (4.1-4.21) |
| 5. JS Rendering | ALL (5.1-5.17) | — |
| 6. VM Network Edge | 6.1-6.5 | 6.6-6.10 |
| 7. Personality | ALL (7.1-7.9) | — |
| 8. SSH System | — | ALL (8.1-8.7) |
| 9. DC01 Regression | — | ALL (9.1-9.10) |

**Rick:** Tiers 1, 3, 5, 7 + half of 6 = **51 tests**
**Morty:** Tiers 2, 4, 8, 9 + half of 6 = **60 tests**

---

## Test Config Files Needed

Create these in `/home/freq-ops/dev-ops/rick/tests/configs/`:

```
profile_a/          # Bare Metal Baby
  freq.toml
  hosts.conf        # empty
  vlans.toml        # empty

profile_b/          # Big Boy /16
  freq.toml
  hosts.conf        # 12 hosts
  vlans.toml        # 4 VLANs with /16

profile_c/          # Ghost Town
  freq.toml         # minimal
  (no hosts.conf)
  (no vlans.toml)

profile_d/          # /23 network
  freq.toml
  hosts.conf        # 5 hosts
  vlans.toml        # 2 VLANs with /23

profile_e/          # DC01 (symlink to current conf/)
```
