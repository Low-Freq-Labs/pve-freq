"""HP iLO BMC deployer — community plugin (not included in base).

iLO uses its own CLI or REST (Redfish) API for user management.
Similar to iDRAC but with different command set.

To contribute: implement deploy() using iLO SSH CLI or Redfish API.
Reference: freq/deployers/bmc/idrac.py
"""
CATEGORY = "bmc"
VENDOR = "ilo"
NEEDS_PASSWORD = True
NEEDS_RSA = True
STUB = True


def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy FREQ service account to HP iLO. (Not implemented — community plugin.)"""
    from freq.core import fmt
    fmt.step_warn("HP iLO deployer is a community plugin — not included in PVE FREQ base")
    fmt.info("  To contribute: https://github.com/sonnet-io/pve-freq")
    return False


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from HP iLO. (Not implemented.)"""
    return False, "HP iLO deployer not included — community plugin"
