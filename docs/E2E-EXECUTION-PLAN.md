# E2E Execution Plan — v3.0.0 on VM 5005 (freq-test)

**Author:** Morty
**Date:** 2026-04-02
**Status:** DRAFT — Awaiting Sonny's approval before execution
**Target:** VM 5005 (freq-test) at 10.25.255.55

---

## ACCOUNT MODEL — DO NOT CONFUSE THESE

| Account | Purpose | Who Owns It | When Used |
|---------|---------|-------------|-----------|
| **freq-ops** | Sonny's bootstrap account. Already deployed on all hosts. Has NOPASSWD sudo. | Sonny | ONLY for running `sudo freq init`. Nothing else. |
| **freq-admin** | FREQ's own service account. Created BY `freq init`. Used BY every freq command after init. | FREQ | Every command after init completes. |

**Rule: freq-ops is the ladder. freq-admin is the house. You use the ladder to build the house, then you put the ladder away.**

After `freq init` completes, freq-ops is NEVER used again by FREQ. All SSH connections use freq-admin with the key that init generated and deployed.

---

## CHUNK 0 — CLEAN SLATE

Wipe VM 5005 completely. EVERYTHING goes. Fresh git clone, fresh install. This is a brand new user experience test.

The hosts.conf in Nexus's `/data/projects/pve-freq/conf/` is Morty's reference copy so I know the fleet layout. It does NOT get copied to VM 5005. freq init on 5005 builds its own config from scratch.

| Step | Action | Verify |
|------|--------|--------|
| 0.1 | SSH to freq-test as freq-ops | `ssh freq-ops@10.25.255.55 hostname` → `freq-test` |
| 0.2 | Nuke everything freq-related on 5005 | `sudo rm -rf /opt/pve-freq /etc/freq /home/freq-admin` |
| 0.3 | Remove freq-admin account if exists | `sudo userdel -r freq-admin 2>/dev/null; sudo rm -f /etc/sudoers.d/freq-admin` |
| 0.4 | Verify clean slate | `ls /opt/pve-freq` → not found. `id freq-admin` → no such user. |
| 0.5 | Fresh git clone on VM 5005 | `ssh freq-ops@10.25.255.55 'cd /opt && sudo git clone -b v3-rewrite https://github.com/Low-Freq-Labs/pve-freq.git pve-freq'` |
| 0.6 | Run install.sh on VM 5005 | `ssh freq-ops@10.25.255.55 'cd /opt/pve-freq && sudo bash install.sh --from-local . --yes'` |
| 0.7 | Verify freq runs on 5005 | `ssh freq-ops@10.25.255.55 'freq version'` → shows 3.0.0 |
| 0.8 | Verify config is EMPTY | `ssh freq-ops@10.25.255.55 'ls /opt/pve-freq/conf/'` → default template files only, no .initialized, no keys, no vault |
| 0.9 | Verify freq doctor pre-init | `ssh freq-ops@10.25.255.55 'freq doctor'` — expected: fleet connectivity fails (no init yet), everything else green |

**STOP.** Review output. If anything unexpected, do not proceed.

**WHAT I WILL NOT DO IN CHUNK 0:**
- I will NOT delete or modify freq-ops's account, keys, or authorized_keys on any host
- I will NOT copy hosts.conf, freq.toml, or any config from Nexus to 5005 — init creates those
- I will NOT set `service_account = "freq-ops"` in freq.toml — ever
- I will NOT proceed past 0.9 if anything looks wrong
- I will NOT install freq on any host other than VM 5005

---

## CHUNK 1 — FREQ INIT (The Real Test)

This is the moment of truth. freq init uses freq-ops to bootstrap freq-admin.

| Step | Action | Verify |
|------|--------|--------|
| 1.1 | Run freq init | `sudo freq init --bootstrap-user freq-ops --bootstrap-key ~/.ssh/fleet_key` |
| 1.2 | Init wizard prompts | Answer: PVE API nodes, service account name (freq-admin), confirm hosts |
| 1.3 | Init creates ed25519 keypair | Check `data/keys/` has new key files |
| 1.4 | Init deploys freq-admin to freq-test | Watch output — should show user created, key deployed, sudo configured |
| 1.5 | Init marks complete | `conf/.initialized` file created |
| 1.6 | Verify freq-admin SSH works | `ssh -i data/keys/freq-admin freq-admin@10.25.255.55 hostname` → `freq-test` |
| 1.7 | Verify freq-admin has sudo | `ssh -i data/keys/freq-admin freq-admin@10.25.255.55 sudo whoami` → `root` |
| 1.8 | Verify freq-ops is UNTOUCHED | `ssh freq-ops@10.25.255.55 whoami` → still works, nothing changed |

**CRITICAL CHECK after 1.8:** If freq-ops SSH breaks, STOP IMMEDIATELY. Something wrote to the wrong authorized_keys. Do not proceed.

**STOP.** Review all output. Verify freq-admin works AND freq-ops still works.

**WHAT I WILL NOT DO IN CHUNK 1:**
- I will NOT run `freq init` with `--bootstrap-user freq-admin` — freq-admin doesn't exist yet
- I will NOT run `freq init --uninstall` to "clean up" if something fails — that's what destroyed the fleet last time
- I will NOT manually SSH into hosts to create accounts — freq init does that
- I will NOT touch freq-ops's authorized_keys, sudoers, or home directory on any host
- I will NOT run init a second time without stopping and asking Sonny first
- If init fails, I STOP. I do not retry. I report what happened.

---

## CHUNK 2 — POST-INIT DIAGNOSTICS

All commands from here forward use freq-admin (via freq's own SSH key). freq-ops is done. The ladder is put away.

| Step | Action | Expected |
|------|--------|----------|
| 2.1 | `freq doctor` | All checks green. Fleet connectivity passes. |
| 2.2 | `freq fleet status` | freq-test shows UP |
| 2.3 | `freq host list` | freq-test listed with correct IP and type |
| 2.4 | `freq help` | 25 domains displayed, organized by category |
| 2.5 | `freq vm list` | VMs from PVE cluster (if PVE API configured) |
| 2.6 | `freq plugin list` | Shows example_ping plugin (from conf/plugins/) |
| 2.7 | `freq plugin types` | Shows 7 plugin types |

**STOP.** If any command fails, note the error and move on — do not retry blindly. 3-fail rule applies.

**WHAT I WILL NOT DO IN CHUNK 2:**
- I will NOT SSH as freq-ops for any reason — that account is done after init
- I will NOT re-run freq init to "fix" a failing command
- I will NOT modify hosts.conf, freq.toml, or any config to make a test pass — if it fails, the bug is in the code
- If 3 commands fail in a row, I STOP and report

---

## CHUNK 3 — DOMAIN SMOKE TESTS (Read-Only)

One command per domain. All read-only. Just verify the domain dispatch works and the command doesn't crash.

| Step | Command | Expected |
|------|---------|----------|
| 3.1 | `freq fleet health` | Health summary for freq-test |
| 3.2 | `freq fleet info freq-test` | System info (hostname, OS, CPU, RAM, disk) |
| 3.3 | `freq fleet detail freq-test` | Deep inventory |
| 3.4 | `freq secure audit freq-test` | Security audit output |
| 3.5 | `freq observe logs tail freq-test` | Recent log lines |
| 3.6 | `freq observe alert list` | Alert rules (may be empty) |
| 3.7 | `freq state policies` | Policy list |
| 3.8 | `freq auto rules list` | Automation rules (may be empty) |
| 3.9 | `freq ops oncall whoami` | On-call status |
| 3.10 | `freq hw cost` | Cost estimates |
| 3.11 | `freq user list` | User list |
| 3.12 | `freq event list` | Events (should be empty) |
| 3.13 | `freq vpn wg status` | WireGuard status |
| 3.14 | `freq cert scan` | TLS cert inventory |
| 3.15 | `freq dns scan` | DNS validation |
| 3.16 | `freq proxy status` | Proxy detection |
| 3.17 | `freq dr backup list` | Backup list |
| 3.18 | `freq store nas status` | TrueNAS/storage status |
| 3.19 | `freq docker list` | Container list on Docker hosts |

**For each:** Note exit code (0 = pass, non-zero = investigate). Note if output is empty vs error. Some domains may have no data — that's OK. Errors and crashes are NOT OK.

**STOP.** Tally results. Any crashes → file bug, do not retry.

**WHAT I WILL NOT DO IN CHUNK 3:**
- I will NOT run any command that modifies state (no create, delete, apply, fix, wipe)
- I will NOT SSH as freq-ops
- I will NOT run commands against hosts other than freq-test (except read-only fleet-wide queries)
- I will NOT retry a crashing command more than once — if it crashes, it's a bug, not a retry problem
- If 3 commands crash in a row, I STOP and report

---

## CHUNK 4 — VM LIFECYCLE (Destructive — 5010-5020 range ONLY)

These tests create and destroy VMs. ONLY use VMIDs 5010-5020 on pve02.

| Step | Command | Verify |
|------|---------|--------|
| 4.1 | `freq vm create --vmid 5010 --name e2e-test --node pve02 --cores 1 --ram 1024 --disk 8` | VM created |
| 4.2 | `freq vm list --node pve02` | 5010 appears |
| 4.3 | `freq vm power start 5010` | VM starts |
| 4.4 | `freq vm power status 5010` | Shows running |
| 4.5 | `freq vm snapshot create 5010 --name pre-test` | Snapshot created |
| 4.6 | `freq vm power stop 5010` | VM stops |
| 4.7 | `freq vm destroy 5010 --yes` | VM destroyed |
| 4.8 | `freq vm list --node pve02` | 5010 gone |

**CLEANUP:** After chunk 4 completes (pass or fail), verify no orphan VMs exist in 5010-5020 range on pve02.

**WHAT I WILL NOT DO IN CHUNK 4:**
- I will NOT use any VMID outside 5010-5020
- I will NOT create VMs on any node other than pve02
- I will NOT touch VM 5005 (freq-test), 100 (production), or any existing VM
- I will NOT run destroy without `--yes` and without verifying the VMID is in range first
- I will NOT leave orphan VMs — if create succeeds but destroy fails, I clean up manually
- I will NOT SSH as freq-ops

---

## CHUNK 5 — DASHBOARD

| Step | Action | Verify |
|------|--------|--------|
| 5.1 | `freq serve &` | Server starts on port 8888 |
| 5.2 | `curl -s http://localhost:8888/healthz` | Returns 200 |
| 5.3 | `curl -s http://localhost:8888/api/status` | Returns JSON with fleet data |
| 5.4 | Open browser to http://10.25.255.8:8888 | Login page loads |
| 5.5 | Kill serve process | Clean shutdown |

**WHAT I WILL NOT DO IN CHUNK 5:**
- I will NOT leave freq serve running after testing — kill it when done
- I will NOT modify serve.py to make tests pass
- I will NOT expose the dashboard to the public VLAN
- I will NOT SSH as freq-ops

---

## CHUNK 6 — RESULTS

| Metric | Target |
|--------|--------|
| Chunk 0 (clean slate) | All steps green |
| Chunk 1 (freq init) | freq-admin deployed, freq-ops untouched |
| Chunk 2 (diagnostics) | All 7 commands return 0 |
| Chunk 3 (domain smoke) | 19 commands, note pass/fail each |
| Chunk 4 (VM lifecycle) | Create → start → snapshot → stop → destroy clean |
| Chunk 5 (dashboard) | Health endpoint returns 200, login page loads |

---

## ABORT CONDITIONS

Stop testing immediately if:
- freq-ops SSH breaks at ANY point (init corrupted the bootstrap account)
- Any command modifies hosts outside of freq-test / 5010-5020 range
- 3 consecutive failures in any chunk
- Sonny says stop

If I hit an abort condition, I do NOT try to fix it. I report what happened and wait for instructions.
