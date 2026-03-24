Title: Switch running `no service password-encryption` — type 7 passwords would be cleartext
Session: S027-20260220
Context: Audit Phase A — switch running-config shows `no service password-encryption`. While all user accounts use `secret 5` (MD5 hash, secure), any future `password` type entries would be stored in cleartext.
Diagnosis: Current config uses `secret` (type 5 hash) for all accounts, so no passwords are actually cleartext today. But the lack of `service password-encryption` means any future config using `password` instead of `secret` would be stored cleartext. Also, the running-config output includes type 5 hashes which, while not directly reversible, are attackable with rainbow tables. [CONFIRMED]
Exact Fix: Enable `service password-encryption` on the switch: `conf t` → `service password-encryption` → `end` → `write memory`. This encrypts any type 0 passwords with type 7 (weak but better than cleartext).
Priority: P4
