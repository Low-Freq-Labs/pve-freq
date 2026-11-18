"""Ubiquiti switch/router deployer — community plugin (not included in base).

UniFi switches use SSH + standard Linux user management.
EdgeSwitch uses CLI similar to Cisco.

To contribute: implement deploy() for UniFi or EdgeSwitch.
Reference: freq/deployers/switch/cisco.py
"""

CATEGORY = "switch"
VENDOR = "ubiquiti"
NEEDS_PASSWORD = True
NEEDS_RSA = False
STUB = True


def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy FREQ service account to Ubiquiti device. (Not implemented — community plugin.)"""
    from freq.core import fmt

    fmt.step_warn("Ubiquiti deployer is a community plugin — not included in PVE FREQ base")
    fmt.info("  To contribute: https://github.com/sonnet-io/pve-freq")
    return False


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from Ubiquiti device. (Not implemented.)"""
    return False, "Ubiquiti deployer not included — community plugin"
