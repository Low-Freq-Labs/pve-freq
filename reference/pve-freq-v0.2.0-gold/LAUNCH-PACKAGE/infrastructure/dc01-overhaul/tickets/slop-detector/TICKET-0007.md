Title: TrueNAS svc-admin primary GID is 3000, not 950 (truenas_admin)
Session: S027-20260220
Context: Audit Phase A — TrueNAS /etc/passwd shows svc-admin:x:3003:3000 (GID 3000 = sonny-aif UID, likely default group). DC01.md and CLAUDE.md both document svc-admin as UID 3003, GID 950.
Diagnosis: When svc-admin was created on TrueNAS via middleware (S26), the primary GID was set to 3000 instead of 950. NFS exports use mapall_group=truenas_admin (950) so NFS operations are unaffected, but local file operations on TrueNAS create files with GID 3000. [CONFIRMED]
Exact Fix: Via TrueNAS middleware: `midclt call user.update <svc-admin-id> '{"group": <truenas_admin_group_id>}'` to change primary GID to 950. Verify with `id svc-admin`.
Priority: P2
