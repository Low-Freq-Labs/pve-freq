"""HP iLO BMC deployer (stub — community contribution welcome).

iLO uses its own CLI or REST API for user management.
Similar to iDRAC but with different command set.
"""
CATEGORY = "bmc"
VENDOR = "ilo"
NEEDS_PASSWORD = True
NEEDS_RSA = True


def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy FREQ service account to HP iLO."""
    from freq.core import fmt
    fmt.step_warn("HP iLO deployer not yet implemented — contributions welcome")
    return False


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from HP iLO."""
    return False, "not implemented"
