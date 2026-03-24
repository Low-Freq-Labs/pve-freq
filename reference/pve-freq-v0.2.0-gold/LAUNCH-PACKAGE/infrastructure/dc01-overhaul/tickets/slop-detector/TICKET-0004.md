# TICKET-0004: Missing WSL Workstation Section, svc-admin UID, and Lesson #10 Detail

**Priority:** P3 (medium)

## Context

- **File:** `/home/sonny-aif/dc01-overhaul/infra/ARCHITECTURE.md` -- multiple sections
- **DC01.md references:**
  - WSL Workstation section (lines 27-49)
  - svc-admin UID 3003 (line 273)
  - Lesson #10 extra detail (line 655)

## Diagnosis

Three items from DC01.md ground truth are missing from ARCHITECTURE.md:

### 1. WSL Workstation Section (Omitted Entirely)

DC01.md includes a full section documenting the WSL workstation: hostname `wsl-debian`, user uid=3000/gid=950, SMB mount at `/mnt/smb-sonny` with credentials file, auto-mount via `.bashrc`, and symlinks. This is the operator's primary admin interface. Omitting it means the ARCHITECTURE.md is incomplete as an operational reference -- an operator cannot determine how the remote admin workstation connects to the cluster.

### 2. svc-admin UID 3003

DC01.md line 273:
```
svc-admin | UID 3003 (created via GUI, standardization to 2550 deprioritized)
```

ARCHITECTURE.md mentions `sonny-aif` UID 3000 and `truenas_admin` gid 950 but never documents the `svc-admin` service account. This user exists on TrueNAS and omitting it could cause confusion during future permission troubleshooting.

### 3. Lesson #10 Detail Truncated

DC01.md Lesson #10 (line 655):
```
`allFunctions=1` is rejected by pvesh schema -- edit the config file directly
or use semicolon-separated function list in the host field.
```

ARCHITECTURE.md Lesson #10 (line 772) omits this detail entirely. This is a specific workaround that prevents operators from hitting a known pvesh schema error.

## Recommendations

1. Add a WSL Workstation section (can be brief) covering: hostname, user, VPN config path, SMB mount point, and the `.bashrc` auto-mount behavior.

2. Add `svc-admin (UID 3003)` to the TrueNAS section or a user accounts reference table.

3. Append the truncated text to Lesson #10:
```
`allFunctions=1` is rejected by pvesh schema -- edit the config file directly
or use semicolon-separated function list in the host field.
```
