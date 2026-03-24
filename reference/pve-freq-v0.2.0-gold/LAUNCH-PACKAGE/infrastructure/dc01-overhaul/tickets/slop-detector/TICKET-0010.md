Title: Tdarr API key plaintext in live compose file on NFS
Session: S027-20260220
Context: Audit Phase B — docker-compose.tdarr-node.yml on NFS at /mnt/truenas/nfs-mega-share/plex/ contains `apiKey=tapi_BmuGjjRCb` in plaintext. The backup copy was properly redacted to `<TDARR_API_KEY>` in S24.
Diagnosis: The credential was redacted only in the backup copy, not in the production compose file. Anyone with NFS read access (7 allowed networks) can read this API key. [CONFIRMED]
Exact Fix: Move Tdarr API key to an environment variable or .env file (similar to qBit compose pattern). Replace `apiKey=tapi_BmuGjjRCb` with `apiKey=${TDARR_API_KEY}` and create a .env file alongside the compose. Alternatively, if Tdarr API key rotation is supported, rotate after securing.
Priority: P3
