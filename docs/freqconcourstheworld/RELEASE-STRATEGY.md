<!-- INTERNAL — Not for public distribution -->

# RELEASE STRATEGY

**Versioning, Branching, Milestones, and Distribution for v3.0.0**

**Author:** Morty (Lead Dev)
**Created:** 2026-04-01

---

## VERSION SCHEME

Semantic versioning: `MAJOR.MINOR.PATCH`

- **3.0.0** — The Conquest. Full rewrite. Converged domain CLI. 810 actions. Universal distro support.
- **3.0.x** — Patch releases. Bug fixes only. No new features.
- **3.1.0** — First feature release after 3.0.0. Community-requested additions.
- **4.0.0** — Only if we make another breaking change to the CLI grammar (unlikely — the converged structure is designed to last).

---

## MILESTONES

### 3.0.0-alpha — "The Skeleton"

**What ships:**
- Converged CLI domain structure (Phase 0.1 complete)
- All 126 existing features working under new domain names
- Platform abstraction layers (Phase 0.2)
- P0 distro fixes (Phase 0.3)
- SOURCE-CODE-STANDARDS applied to all existing files (Phase 0.4)
- API restructured for domain routing (Phase 0.5)

**What it proves:** The refactor works. Nothing is broken. The foundation is solid.

**Who uses it:** Just us. Internal testing only. Not tagged on GitHub.

### 3.0.0-beta — "The Arsenal"

**What ships:**
- All 21 workstreams built (Phases 1-7)
- 810 actions across 25 domains
- All unit tests passing
- Dashboard pages for all domains (Phase 8)

**What it proves:** The features work. The scope is complete.

**Who uses it:** Us + Sonny's fleet for E2E testing. May share with trusted testers if Sonny approves. Tagged on GitHub as pre-release.

### 3.0.0-rc1 — "The Proof"

**What ships:**
- E2E testing complete (Phase 9)
- All bugs from E2E fixed
- GIT-READY pass complete (Phase 10)
- Tested on Tier 1 + Tier 2 distros
- Docker images built and tested
- README polished
- CHANGELOG written

**What it proves:** It works on real infrastructure across real distros.

**Who uses it:** Anyone willing to test. Tagged on GitHub as pre-release. Docker images published.

### 3.0.0 — "The Conquest"

**What ships:** Everything from rc1 with any final fixes.

**Who uses it:** The world. Tagged on GitHub as latest release. Docker images tagged `latest`. Announcement post.

---

## GIT BRANCHING

```
main                  ← Always releasable. Current v2.2.0.
  └── v3-rewrite      ← Long-lived branch for the entire rewrite.
        ├── phase-0   ← CLI refactor + abstractions (merge to v3-rewrite when done)
        ├── phase-1   ← Network workstreams (merge to v3-rewrite when done)
        ├── phase-2   ← Gateway workstreams
        └── ...       ← One branch per phase, merged sequentially
```

**Rules:**
- `main` stays on v2.2.0 until 3.0.0 ships. It is the safety net.
- `v3-rewrite` is the integration branch. Phases merge here.
- Phase branches are short-lived — one phase, merge, delete.
- Never force-push `v3-rewrite` or `main`.
- Commit often, small commits, clear messages (CLAUDE.md rule 8).

**When 3.0.0 is ready:**
```
v3-rewrite → main (merge, not squash — preserve full history)
Tag main as v3.0.0
```

---

## pve-freq-docker SYNC STRATEGY

CLAUDE.md: "Both repos stay 1:1 — no exceptions."

### What Syncs

| pve-freq file/dir | pve-freq-docker equivalent | Sync method |
|---|---|---|
| `freq/` (all Python source) | `freq/` (identical copy) | Direct copy |
| `conf/*.example` | `conf/*.example` | Direct copy |
| `install.sh` | `install.sh` | Direct copy |
| `pyproject.toml` | `pyproject.toml` | Direct copy |
| `Dockerfile` | `Dockerfile` | May differ slightly (Docker-specific ENV/VOLUME) |
| `docker-compose.yml` | `docker-compose.yml` | Docker repo is authoritative |
| `docker-entrypoint.sh` | `docker-entrypoint.sh` | Docker repo is authoritative |
| `README.md` | `README.md` | Different — Docker repo has Docker-specific docs |
| `docs/` | Not synced | Only in pve-freq |
| `tests/` | `tests/` | Direct copy |

### When to Sync

After every phase merge to `v3-rewrite`:
1. Copy all synced files from pve-freq to pve-freq-docker
2. Build Docker image: `docker build -t pve-freq:test .`
3. Run smoke test: `docker run pve-freq:test freq version`
4. Commit to pve-freq-docker with matching commit message
5. Both repos should have the same commit count for the phase

### Sync Script

Create `scripts/sync-docker.sh` in pve-freq:
```bash
#!/bin/bash
# Sync pve-freq → pve-freq-docker
SRC=/data/projects/pve-freq
DST=/data/projects/pve-freq-docker

rsync -av --delete \
    --exclude='.git' \
    --exclude='docs/' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='conf/*.toml'     # Don't sync actual config, only examples \
    --exclude='conf/*.conf'     \
    $SRC/freq/ $DST/freq/

cp $SRC/pyproject.toml $DST/
cp $SRC/install.sh $DST/
cp $SRC/conf/*.example $DST/conf/ 2>/dev/null
rsync -av --delete $SRC/tests/ $DST/tests/

echo "Sync complete. Build and test the Docker image."
```

---

## DISTRIBUTION CHANNELS

### 1. GitHub Release (Primary)

```
https://github.com/lowfreqlabs/pve-freq/releases/tag/v3.0.0
```

Assets:
- Source tarball (`pve-freq-3.0.0.tar.gz`)
- Pre-built wheel (`pve_freq-3.0.0-py3-none-any.whl`) — if we add pyproject packaging
- Changelog
- SHA256 checksums

### 2. Docker Hub / GitHub Container Registry

```bash
docker pull ghcr.io/lowfreqlabs/pve-freq:3.0.0
docker pull ghcr.io/lowfreqlabs/pve-freq:latest
docker pull ghcr.io/lowfreqlabs/pve-freq:alpine
```

Tags:
- `3.0.0` — exact version
- `latest` — always points to latest stable
- `alpine` — Alpine-based minimal image
- `3.0.0-rc1`, `3.0.0-beta` — pre-release tags

### 3. Install Script (curl | bash)

```bash
curl -fsSL https://raw.githubusercontent.com/lowfreqlabs/pve-freq/main/install.sh | bash
```

The install script:
1. Detects distro and Python version
2. Installs Python 3.11+ if needed (with user confirmation)
3. Downloads the latest release tarball
4. Installs to `/opt/pve-freq` (or `~/.local/share/pve-freq` on immutable distros)
5. Creates `freq` symlink in PATH
6. Runs `freq doctor` to verify

### 4. Git Clone (Developer Install)

```bash
git clone https://github.com/lowfreqlabs/pve-freq.git
cd pve-freq
./install.sh --local
```

### 5. pip Install (Future — If We Add pyproject Packaging)

```bash
pip install pve-freq
```

Not a priority for 3.0.0. The zero-dependency constraint means pip is just a distribution mechanism, not a dependency resolver.

---

## CHANGELOG FORMAT

```markdown
# Changelog

## [3.0.0] — 2026-XX-XX

### The Conquest

Complete rewrite of PVE FREQ. 810 actions across 25 command domains.
Replaces 20+ enterprise tools with one CLI.

### Breaking Changes
- CLI restructured to domain-based commands (`freq vm create` replaces `freq create`)
- All 126 previous top-level commands moved to domains
- Minimum Python version raised to 3.11

### New Domains
- `freq net` — Switch orchestration, SNMP, topology, traffic analysis, IPAM
- `freq fw` — Full pfSense/OPNsense management (rules, NAT, DHCP, DNS, QoS, IDS, HA)
- `freq dns` — Pi-hole, AdGuard Home, Unbound, BIND management
- `freq vpn` — WireGuard, OpenVPN, Tailscale/Headscale, IPsec
- `freq cert` — ACME, private CA, fleet-wide cert inventory
- `freq proxy` — NPM, Caddy, Traefik, HAProxy management
- `freq store` — TrueNAS full API, ZFS deep, Ceph, MinIO, fleet shares
- `freq dr` — Backup orchestration, replication, failover, DR testing, RTO/RPO
- `freq observe` — Metrics, logs, synthetics, anomaly detection, status pages
- `freq secure` — Vuln scanning, CIS/STIG, FIM, IDS, container security
- `freq ops` — Incident, change, problem management, postmortems, CMDB
- `freq hw` — iDRAC Redfish, IPMI, SMART, UPS/PDU management
- `freq state` — Infrastructure as Code, plan/apply, drift detection
- `freq auto` — Event bus, reactors, workflows, auto-remediation
- `freq event` — Live event network lifecycle

### Platform Support
- Works on every Linux distro with Python 3.11+
- Manages Debian, RHEL, Arch, Alpine, SUSE, Gentoo, Void fleet targets
- Manages FreeBSD targets (pfSense/OPNsense)
- Docker images available (Debian and Alpine based)

### Architecture
- Domain-based CLI dispatch (25 domains replacing 126 flat commands)
- Platform abstraction layers (package manager, service manager, init system)
- Domain-based API routing (/api/v1/<domain>/<action>)
- Multi-vendor switch deployer interface (Cisco, Juniper, Aruba, Ubiquiti, Arista)
```

---

## SECURITY CONSIDERATIONS FOR PUBLIC RELEASE

Before going public, these must be verified:

### What's in the Repo (Must NOT Contain)

- [ ] No API tokens, passwords, or secrets in any file
- [ ] No DC01 IP addresses in production code (config only)
- [ ] No private SSH keys
- [ ] No credential file contents
- [ ] No `.env` files with real values
- [ ] `conf/` directory only has `.example` files, no real configs
- [ ] `git log` doesn't contain secrets in commit messages
- [ ] `.gitignore` covers: `conf/*.toml`, `conf/*.conf`, `data/`, `*.pyc`, `__pycache__/`, `.env`

### What's in the Code (Must Be Auditable)

- [ ] Vault encryption uses strong defaults (AES-256 or better)
- [ ] SSH key generation uses ed25519 (not RSA by default)
- [ ] API authentication uses secure session tokens (not basic auth)
- [ ] No eval(), exec(), or pickle on untrusted input
- [ ] subprocess calls use lists (not shell=True with string interpolation)
- [ ] File permissions set correctly (600 for credentials, 755 for executables)
- [ ] No command injection vectors in SSH command construction

### What's Documented

- [ ] Security model explained in README or dedicated SECURITY.md
- [ ] How SSH keys are generated and stored
- [ ] How vault encryption works
- [ ] How API auth works
- [ ] How to report security vulnerabilities (SECURITY.md with contact info)
