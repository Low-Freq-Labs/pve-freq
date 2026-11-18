"""Private snippet/generated-intent composition, never an effective plan.

Accepted generated-field preparation and snippet intent are kept distinct.
This first join conservatively refuses explicit custom replacement together
with generated-field changes. Retain does not prove that an existing custom
reference is absent: original adapters still owe real ownership observations,
storage/target/profile/permission/currentness and operation custody checks.
"""
from dataclasses import dataclass

from freq.services.cloud_init_patch_data import (
    CloudInitPatchData, prepare_cloud_init_patch_data,
)
from freq.services.cloud_init_snippet_intent import (
    SnippetPatchData, normalize_snippet_patch_data,
)


class InvalidCloudInitSnippetPatch(ValueError):
    """Fixed private composition refusal without submitted values."""


@dataclass(frozen=True, slots=True, repr=False)
class CloudInitSnippetPatchData:
    generated: CloudInitPatchData
    snippets: SnippetPatchData
    __hash__ = None

    def __reduce_ex__(self, protocol):
        raise TypeError('Private snippet metadata cannot be serialized')


def _generated_changes(generated):
    network = generated.network
    if network.dns_servers.action != 'retain' or network.search_domains.action != 'retain':
        return True
    if any(nic.ipv4.action != 'retain' or nic.ipv6.action != 'retain' for nic in network.nics):
        return True
    identity = generated.identity
    return any(field.action != 'retain' for field in (
        identity.ciuser, identity.public_keys, identity.password_reference,
        identity.citype, identity.ciupgrade))


def prepare_cloud_init_snippet_patch_data(value):
    """Prepare each fixed submodel once, without fallback or implicit merge.

    This is an additional private root; the accepted two-key generated root
    stays unchanged. Supplied normalization results/callbacks are not inputs.
    No result, including omission/retain, is an authorization or compatibility
    verdict. Unexpected/control/allocation failures propagate unchanged.
    """
    if (type(value) is not dict or len(value) > 3 or
            any(type(key) is not str for key in value) or
            not value.keys() <= {'network', 'identity', 'snippets'}):
        raise InvalidCloudInitSnippetPatch('Invalid private cloud-init snippet root') from None
    generated = prepare_cloud_init_patch_data({
        key: value[key] for key in ('network', 'identity') if key in value})
    snippets = normalize_snippet_patch_data(value['snippets'] if 'snippets' in value else {})
    if type(generated) is not CloudInitPatchData or type(snippets) is not SnippetPatchData:
        raise InvalidCloudInitSnippetPatch('Invalid private cloud-init snippet result') from None
    custom_set = any(field.action == 'set' for field in (
        snippets.user, snippets.vendor, snippets.meta, snippets.network))
    if custom_set and _generated_changes(generated):
        raise InvalidCloudInitSnippetPatch('Custom snippet and generated-field changes conflict') from None
    return CloudInitSnippetPatchData(generated, snippets)
