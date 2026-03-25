"""TrueNAS deployer.

TrueNAS uses standard Linux/FreeBSD user management via SSH.
Delegates to the server:linux deployer since the deploy process is identical.
"""
CATEGORY = "nas"
VENDOR = "truenas"
NEEDS_PASSWORD = False
NEEDS_RSA = False


def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy FREQ service account to TrueNAS."""
    from freq.deployers.server.linux import deploy as linux_deploy
    return linux_deploy(ip, ctx, auth_pass, auth_key, auth_user, htype="truenas")


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from TrueNAS."""
    from freq.deployers.server.linux import remove as linux_remove
    return linux_remove(ip, svc_name, key_path)
