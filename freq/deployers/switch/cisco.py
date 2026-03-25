"""Cisco IOS switch deployer.

Uses IOS config commands via stdin pipe. RSA key only (no ed25519).
Password auth for initial connect.
"""
CATEGORY = "switch"
VENDOR = "cisco"
NEEDS_PASSWORD = True
NEEDS_RSA = True


def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy FREQ service account to Cisco IOS switch."""
    from freq.modules.init_cmd import _deploy_switch
    return _deploy_switch(ip, ctx, auth_pass, auth_key, auth_user)


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from Cisco IOS switch."""
    from freq.modules.init_cmd import _remove_switch
    return _remove_switch(ip, svc_name, rsa_key_path or key_path)
