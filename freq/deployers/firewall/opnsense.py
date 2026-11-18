"""First-class OPNsense API enrollment deployer.

The actual transaction is owned by ``freq.core.opnsense_lifecycle`` so init,
post-setup Settings, CLI, and removal share one fail-closed implementation.
"""

CATEGORY = "firewall"
VENDOR = "opnsense"
NEEDS_PASSWORD = True
NEEDS_RSA = False
STUB = False


def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Enroll the managed API identity using staged value-only credentials."""
    from freq.core.opnsense_lifecycle import deploy_from_init

    return deploy_from_init(ip, ctx, auth_pass, auth_key, auth_user)


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove the managed API identity through the shared lifecycle owner."""
    from freq.core.opnsense_lifecycle import remove_from_init

    return remove_from_init(ip, svc_name, key_path)
