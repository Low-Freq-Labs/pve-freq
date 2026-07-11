"""Consumer for the disposable SSH lab environment contract."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from freq.core.ssh import run, run_many
from freq.core.types import Host


REQUIRED_ENV = (
    "EPHEMERAL_LAB_HOST",
    "EPHEMERAL_LAB_PORT",
    "EPHEMERAL_LAB_USER",
    "EPHEMERAL_LAB_KEY",
    "EPHEMERAL_LAB_KNOWN_HOSTS",
)


@dataclass(frozen=True)
class EphemeralLab:
    host: str
    port: int
    user: str
    key: Path
    known_hosts: Path

    @classmethod
    def from_env(cls) -> "EphemeralLab":
        missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
        if missing:
            raise ValueError("missing ephemeral-lab environment: " + ", ".join(missing))
        lab = cls(
            host=os.environ["EPHEMERAL_LAB_HOST"],
            port=int(os.environ["EPHEMERAL_LAB_PORT"]),
            user=os.environ["EPHEMERAL_LAB_USER"],
            key=Path(os.environ["EPHEMERAL_LAB_KEY"]),
            known_hosts=Path(os.environ["EPHEMERAL_LAB_KNOWN_HOSTS"]),
        )
        if lab.host != "127.0.0.1":
            raise ValueError(f"ephemeral lab must be loopback-only, got {lab.host}")
        if not 1 <= lab.port <= 65535:
            raise ValueError(f"ephemeral lab port out of range: {lab.port}")
        for path in (lab.key, lab.known_hosts):
            if not path.is_file():
                raise ValueError(f"ephemeral lab file missing: {path}")
        return lab

    def config(self):
        return SimpleNamespace(
            ssh_service_account=self.user,
            ssh_connect_timeout=3,
            ssh_max_parallel=2,
            ssh_key_path=str(self.key),
            ssh_rsa_key_path=str(self.key),
            legacy_password_file="",
        )

    def target(self, htype: str = "linux") -> Host:
        return Host(ip=self.host, label="freq-lab", htype=htype)

    def ssh(self, command: str, *, htype: str = "linux", use_sudo: bool = False):
        return run(
            host=self.host,
            command=command,
            user=self.user,
            key_path=str(self.key),
            connect_timeout=3,
            command_timeout=10,
            htype=htype,
            use_sudo=use_sudo,
            cfg=self.config(),
            port=self.port,
            known_hosts_file=str(self.known_hosts),
        )

    def ssh_many(self, command: str, *, htype: str = "linux", use_sudo: bool = False):
        host = self.target(htype)
        return host, run_many(
            hosts=[host],
            command=command,
            key_path=str(self.key),
            connect_timeout=3,
            command_timeout=10,
            max_parallel=1,
            use_sudo=use_sudo,
            cfg=self.config(),
            port=self.port,
            known_hosts_file=str(self.known_hosts),
        )
