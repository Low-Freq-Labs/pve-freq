"""Ubiquiti switch/router deployer (stub — community contribution welcome).

UniFi switches use SSH + standard Linux user management.
EdgeSwitch uses CLI similar to Cisco.
"""
CATEGORY = "switch"
VENDOR = "ubiquiti"
NEEDS_PASSWORD = True
NEEDS_RSA = False


def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy FREQ service account to Ubiquiti device."""
    from freq.core import fmt
    fmt.step_warn("Ubiquiti deployer not yet implemented — contributions welcome")
    return False


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from Ubiquiti device."""
    return False, "not implemented"
