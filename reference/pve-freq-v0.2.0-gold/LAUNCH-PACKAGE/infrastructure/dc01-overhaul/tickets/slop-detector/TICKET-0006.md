Title: Temporary password changeme1234! on all 10 systems — single compromise = full infrastructure access
Session: S027-20260220
Context: Audit Phase A — all systems confirmed using temp password from S26 svc-admin deployment
Diagnosis: svc-admin account deployed to all 10 systems with identical temporary password. No SSH keys deployed. Password auth enabled everywhere. A single credential compromise gives full NOPASSWD sudo access to every system in DC01. [CONFIRMED]
Exact Fix: (1) Generate SSH keypair for svc-admin on WSL. (2) Deploy public key to all 10 systems. (3) Rotate password to unique per-system or disable password auth entirely. (4) Set PasswordAuthentication no in sshd_config on all systems.
Priority: P1
