"""OPNsense deployer (stub — community contribution welcome).

OPNsense uses configd API or direct FreeBSD pw commands.
Similar to pfSense but with different API surface.
"""
CATEGORY = "firewall"
VENDOR = "opnsense"
NEEDS_PASSWORD = True
NEEDS_RSA = False


def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy FREQ service account to OPNsense."""
    from freq.core import fmt
    fmt.step_warn("OPNsense deployer not yet implemented — contributions welcome")
    fmt.step_warn("Workaround: use 'firewall:pfsense' (pw useradd works on both)")
    return False


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from OPNsense."""
    return False, "not implemented"
