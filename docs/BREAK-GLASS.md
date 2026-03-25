# Break Glass — Emergency Operations Procedure

> **Purpose:** When FREQ or the management system is broken, here's how to recover.
> **Audience:** Cluster operator

---

## When To Use This

- FREQ config is corrupted or missing
- SSH keys are lost or compromised
- Fleet connectivity is down
- Dashboard won't start

---

## Scenario 1: FREQ Config Corrupted

**Symptom:** `freq doctor` fails, commands error on config load.

```bash
# Re-seed config from examples
cd /opt/pve-freq
for f in conf/*.example; do
    active="${f%.example}"
    [ -f "$active" ] || cp "$f" "$active"
done

# Verify
freq doctor
```

---

## Scenario 2: SSH Keys Lost

**Symptom:** Fleet commands fail with "Permission denied" or "No such file".

```bash
# Regenerate FREQ SSH keys
freq init --regenerate-keys

# Or manually:
ssh-keygen -t ed25519 -f /opt/pve-freq/data/keys/freq_id_ed25519 -N ""
ssh-keygen -t rsa -b 4096 -f /opt/pve-freq/data/keys/freq_id_rsa -N ""

# Re-deploy to fleet
freq init --deploy-keys
```

---

## Scenario 3: Fleet Connectivity Down

**Symptom:** `freq exec all "hostname"` returns all failures.

```bash
# Test individual host connectivity
ssh -o ConnectTimeout=5 freq-admin@<host-ip> "hostname"

# Check if it's a network issue or auth issue
# Network: ping <host-ip>
# Auth: ssh -v freq-admin@<host-ip>

# Common fixes:
# - Firewall rule changed: check pfSense/OPNsense rules
# - SSH key permissions: chmod 600 on key files
# - Service account locked: check /etc/shadow on target host
```

---

## Scenario 4: Dashboard Won't Start

**Symptom:** `freq serve` exits immediately or port already in use.

```bash
# Check if already running
pgrep -f 'freq serve' && echo "Already running"

# Kill existing and restart
kill $(pgrep -f 'freq serve') 2>/dev/null
sleep 1
freq serve --port 8888 &

# Verify
curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/
# Should print: 200
```

---

## Recovery Priority

| Priority | Action |
|----------|--------|
| 1 | Stop. Don't make it worse. |
| 2 | Run `freq doctor` to identify what's broken |
| 3 | Check `data/log/freq.log` for error details |
| 4 | Re-seed config from examples if config is corrupted |
| 5 | Regenerate SSH keys if auth is broken |
| 6 | Fix the root cause |
| 7 | Document the failure mode for next time |
