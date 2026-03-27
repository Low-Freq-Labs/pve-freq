"""OPNsense deployer — community plugin (not included in base).

OPNsense uses configd API or direct FreeBSD pw commands.
Similar to pfSense but with different API surface.

To contribute: implement deploy() using OPNsense configd or SSH + pw commands.
Reference: freq/deployers/firewall/pfsense.py
"""
CATEGORY = "firewall"
VENDOR = "opnsense"
NEEDS_PASSWORD = True
NEEDS_RSA = False
STUB = True


def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy FREQ service account to OPNsense. (Not implemented — community plugin.)"""
    from freq.core import fmt
    fmt.step_warn("OPNsense deployer is a community plugin — not included in PVE FREQ base")
    fmt.info("  Workaround: use 'firewall:pfsense' (pw useradd works on both)")
    fmt.info("  To contribute: https://github.com/sonnet-io/pve-freq")
    return False


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from OPNsense. (Not implemented.)"""
    return False, "OPNsense deployer not included — community plugin"
