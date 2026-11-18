"""Private combined cloud-init patch preparation, never an API or issuer.

The root shape is internal DATA only. Actual interface adapters must separately
join original target/revision/attachment/profile/credential/permission/operation
owners. No effective current/pending/generated/guest value is inferred here.
"""
from dataclasses import dataclass

from freq.services.cloud_init_network_intent import (
    NetworkPatch, normalize_network_patch,
)
from freq.services.cloud_init_identity_intent import (
    IdentityPatch, normalize_identity_patch,
)


class InvalidCloudInitPatch(ValueError):
    """Fixed root shape/type refusal without submitted values."""


@dataclass(frozen=True, slots=True, repr=False)
class CloudInitPatchData:
    network: NetworkPatch
    identity: IdentityPatch


def prepare_cloud_init_patch_data(value):
    """Normalize each supplied exact subpatch once; omission means retain.

    There is no fallback after the first failure and no callback/parsed result
    supplied by the caller. Inner public failures propagate unchanged. Clear,
    inherit, package effects and secret references remain product intents with
    no installed representation, credential approval or source authority.
    """
    if (type(value) is not dict or len(value) > 2 or
            any(type(key) is not str for key in value) or
            not value.keys() <= {'network', 'identity'}):
        raise InvalidCloudInitPatch('Invalid cloud-init patch root') from None
    network = normalize_network_patch(value['network'] if 'network' in value else {})
    if type(network) is not NetworkPatch:
        raise InvalidCloudInitPatch('Invalid cloud-init patch result') from None
    identity = normalize_identity_patch(value['identity'] if 'identity' in value else {})
    if type(identity) is not IdentityPatch:
        raise InvalidCloudInitPatch('Invalid cloud-init patch result') from None
    return CloudInitPatchData(network, identity)
