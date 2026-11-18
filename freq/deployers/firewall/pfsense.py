"""pfSense deployer (FreeBSD-based firewall).

Uses pw useradd for account creation. No sudo (pfSense admin model).
ed25519 key for SSH auth.
"""

CATEGORY = "firewall"
VENDOR = "pfsense"
NEEDS_PASSWORD = True
NEEDS_RSA = False


def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy FREQ service account to pfSense."""
    from freq.modules.init_cmd import _deploy_pfsense

    return _deploy_pfsense(ip, ctx, auth_pass, auth_key, auth_user)


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from pfSense."""
    from freq.modules.init_cmd import _remove_pfsense

    return _remove_pfsense(ip, svc_name, key_path)
