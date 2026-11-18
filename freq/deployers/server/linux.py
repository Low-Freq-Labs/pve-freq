"""Linux-family deployer (linux, pve, docker, truenas).

Standard SSH + useradd + sudo deployment. Handles Alpine vs glibc.
Adds docker group for docker-type hosts.
"""

CATEGORY = "server"
VENDOR = "linux"
NEEDS_PASSWORD = False
NEEDS_RSA = False

# These are thin wrappers — the actual logic lives in init_cmd.py
# until we extract SSH primitives to freq.core.remote.
# This module exists so the registry can discover it and new server
# variants (e.g., server:freebsd) can be added as new files.


def deploy(ip, ctx, auth_pass, auth_key, auth_user, htype="linux"):
    """Deploy FREQ service account to a Linux-family host."""
    from freq.modules.init_cmd import _deploy_linux

    return _deploy_linux(ip, ctx, auth_pass, auth_key, auth_user, htype=htype)


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from a Linux-family host."""
    from freq.modules.init_cmd import _remove_linux

    return _remove_linux(ip, svc_name, key_path)
