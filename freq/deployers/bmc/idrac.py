"""Dell iDRAC BMC deployer.

Uses racadm commands for user management. RSA key only (no ed25519).
Password auth for initial connect. Legacy SSH ciphers required.
"""

CATEGORY = "bmc"
VENDOR = "idrac"
NEEDS_PASSWORD = True
NEEDS_RSA = True


def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy FREQ service account to Dell iDRAC."""
    from freq.modules.init_cmd import _deploy_idrac

    return _deploy_idrac(ip, ctx, auth_pass, auth_key, auth_user)


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from Dell iDRAC."""
    from freq.modules.init_cmd import _remove_idrac

    return _remove_idrac(ip, svc_name, rsa_key_path or key_path)
