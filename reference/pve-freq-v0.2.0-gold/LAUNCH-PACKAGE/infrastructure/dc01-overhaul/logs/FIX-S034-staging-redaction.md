# FIX-S034: Staging File Credential Redaction

**Date:** 2026-02-20
**Session:** S034
**Findings addressed:** F-SEC-026, F-SEC-027, F-SEC-028, F-SEC-029

## Summary

Redacted all sensitive credentials from staging data files collected during the S034 security audit. These files contained password hashes, SSH private keys, and VPN keys that must never be stored in cleartext on disk.

## Actions Taken

### 1. Switch Running Config (F-SEC-026)
- **Deleted:** `staging/S034-20260220/switch/running-config.txt` (unredacted)
- **Kept:** `staging/S034-20260220/switch/running-config-redacted.txt` (already redacted)
- The unredacted version contained enable secret hashes, username secret hashes, and plaintext console/VTY passwords.

### 2. TrueNAS users.txt (F-SEC-027)
- **File:** `staging/S034-20260220/truenas/users.txt`
- **Redacted:** 11 SHA-512 (`$6$rounds=...`) Unix password hashes across 5 users
- **Redacted:** 5 SMB/NTLM hashes (32-character hex strings)
- **Users affected:** truenas_admin, sonny-aif, chrisadmin, donmin, svc-admin
- **Includes:** Password history entries for chrisadmin, donmin, svc-admin
- All hash values replaced with `<REDACTED>`. Non-sensitive fields (usernames, UIDs, groups, roles) preserved.

### 3. TrueNAS ssh-config.txt (F-SEC-028)
- **File:** `staging/S034-20260220/truenas/ssh-config.txt`
- **Redacted:** 3 base64-encoded SSH host private keys:
  - `host_ecdsa_key` (ECDSA NIST P-256)
  - `host_ed25519_key` (Ed25519)
  - `host_rsa_key` (RSA)
- Public keys (`*_pub` fields) preserved -- these are not sensitive.
- sshd_config section (non-sensitive) preserved.

### 4. VM 103 docker-env.txt (F-SEC-029)
- **File:** `staging/S034-20260220/vm103/docker-env.txt`
- **Redacted:** `WIREGUARD_PRIVATE_KEY` value (Gluetun VPN client key)
- All other env vars preserved (non-sensitive config values).

### 5. ANALYSIS-security.md (bonus cleanup)
- **File:** `staging/S034-20260220/ANALYSIS-security.md`
- The analysis document itself quoted actual credential values when describing findings F-SEC-026 and F-SEC-029.
- **Redacted:** Cisco enable secret hash, plaintext password quote, and WireGuard key from the analysis text.
- Finding descriptions preserved -- only the quoted values replaced with `<REDACTED>`.

## Verification

Final recursive sweep of `staging/S034-20260220/` confirmed:
- 0 remaining `$6$` password hashes (except descriptive text mentioning the pattern name)
- 0 remaining `$1$` or `$5$` hashes
- 0 remaining SMB/NTLM hex hashes
- 0 remaining base64 private keys in sensitive fields
- 0 remaining plaintext passwords or VPN keys

## Status: DONE
