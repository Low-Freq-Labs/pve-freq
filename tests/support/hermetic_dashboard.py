#!/usr/bin/env python3
"""Run the real freq dashboard against deterministic, temporary test state."""

from __future__ import annotations

import argparse
import signal
import tempfile
import threading
import time
from pathlib import Path

from freq.api import auth
from freq.core.config import FreqConfig
from freq.modules import serve, users


TEST_USER = "admin"
TEST_PASSWORD = "hermetic-dashboard-password"


def _config(root: Path) -> FreqConfig:
    cfg = FreqConfig()
    cfg.install_dir = str(root / "install")
    cfg.conf_dir = str(root / "conf")
    cfg.data_dir = str(root / "data")
    cfg.cache_dir = str(root / "cache")
    cfg.key_dir = str(root / "keys")
    cfg.credentials_dir = str(root / "credentials")
    cfg.vault_dir = str(root / "vault")
    cfg.vault_file = str(root / "vault" / "vault.enc")
    cfg.ssh_key_path = str(root / "keys" / "freq_id_ed25519")
    cfg.ssh_rsa_key_path = str(root / "keys" / "freq_id_rsa")
    cfg.ssh_service_account = "freq-admin"
    cfg.hosts = []
    cfg.pve_nodes = []
    for path in (
        cfg.install_dir,
        cfg.conf_dir,
        cfg.data_dir,
        cfg.cache_dir,
        cfg.key_dir,
        cfg.credentials_dir,
        cfg.vault_dir,
    ):
        Path(path).mkdir(parents=True, exist_ok=True)
    return cfg


def _install_fixture(cfg: FreqConfig) -> None:
    """Bind product seams to hermetic state while preserving real HTTP code."""
    serve.load_config = lambda *args, **kwargs: cfg
    auth.load_config = lambda *args, **kwargs: cfg
    serve._is_first_run = lambda: False
    users._load_users = lambda loaded_cfg: [
        {"username": TEST_USER, "role": "admin"}
    ]
    auth.vault_get = lambda loaded_cfg, namespace, key: "hermetic-password-hash"
    auth.verify_password = lambda password, stored: password == TEST_PASSWORD
    auth.check_rate_limit = lambda *args, **kwargs: True
    auth.record_login_attempt = lambda *args, **kwargs: None

    now = time.time()
    serve._bg_cache["fleet_overview"] = {
        "vms": [],
        "vm_nics": {},
        "physical": [],
        "pve_nodes": [
            {
                "name": "pve-hermetic",
                "ip": "192.0.2.10",
                "online": True,
                "state": "live",
            }
        ],
        "vlans": [],
        "nic_profiles": {},
        "categories": {},
        "summary": {"resource_count": 1, "running": 1, "stopped": 0},
        "fleet_state": "live",
        "fleet_reason": "hermetic fixture healthy",
    }
    serve._bg_cache["health"] = {
        "hosts": [
            {
                "label": "pve-hermetic",
                "ip": "192.0.2.10",
                "state": "live",
                "status": "online",
                "ram": "25%",
                "disk": "20%",
            }
        ],
        "probe_status": "ok",
        "probe_state": "live",
    }
    serve._bg_cache_ts["fleet_overview"] = now
    serve._bg_cache_ts["health"] = now
    serve._bg_cache_errors.clear()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="pve-freq-dashboard-") as tmp:
        cfg = _config(Path(tmp))
        _install_fixture(cfg)
        httpd = serve.ThreadedHTTPServer(("127.0.0.1", args.port), serve.FreqHandler)

        def stop(signum, frame):
            del signum, frame
            threading.Thread(target=httpd.shutdown, daemon=True).start()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        print(f"HERMETIC_DASHBOARD http://127.0.0.1:{httpd.server_port}", flush=True)
        try:
            httpd.serve_forever()
        finally:
            httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
