"""Private configured target/role DATA for the future original startup owner.

This converts parser values to the shapes consumed by the original selected
components. It does not create an installation, native cohort, revision grant,
session, reference, UID, credential, context or authority. The actual original
native owner must retain its acquired source and writer/code/principal/resource
lifetime, construct and retain these exact values itself, and final-admit under
its currentness/response gates. Caller-created results are never such an owner.
"""
from dataclasses import dataclass
from types import MappingProxyType

from freq.services.cluster_references import TargetSnapshot
from freq.services.node_read_profile import _endpoint
from freq.services.pilot_readonly_inputs import (
    PilotInputUnavailable, _literal, _token_id, _user,
)
from freq.services.pilot_startup_inputs import PilotStartupData


class ConfiguredCohortUnavailable(Exception):
    def __init__(self):
        super().__init__('Pilot configured cohort unavailable')


@dataclass(frozen=True, slots=True, repr=False)
class PilotConfiguredData:
    """Immutable DATA only, not an issuer or installation constructor argument."""
    configuration_revision: str
    nodes: tuple
    roles: MappingProxyType
    service_user: str
    token_id: tuple | None
    config_supported: bool
    policy_supported: bool


def prepare_configured_cohort_data(parsed, configuration_revision):
    """Build private original-consumer shapes outside every admission gate.

    Revision is copied bounded data from the eventual original owner, never a
    caller currentness proof. TargetSnapshot construction grants no selection.
    It preserves configured order, labels and literal endpoint spelling. Wire
    transport normalization is used only to refuse duplicate recipient IPs.
    Selection keys are process-private ordinal data, not browser references.

    Empty nodes/users and missing token stay empty/None; unsupported config and
    policy stay independent. The native owner must refuse unavailable required
    inputs before positive admission, rather than filling defaults here. The
    service account remains separately excluded by original auth transactions.

    Fixed parsers and this bounded projection need the same original qualified
    worker/end/resources. Counts/string limits are not heap/CPU/native lifetime
    guarantees. No UID/currentness/writer callback or native IO is accepted.
    """
    if type(parsed) is not PilotStartupData:
        raise ConfiguredCohortUnavailable()
    # Copy fields once. Exact immutable containers/scalars prevent supplied
    # iteration/equality/length hooks; the public data type is not authority.
    nodes, users = parsed.nodes, parsed.configured_users
    service_user, token_id = parsed.service_user, parsed.token_id
    config_supported, policy_supported = parsed.config_supported, parsed.policy_supported
    if (type(nodes) is not tuple or len(nodes) > 1024 or
            type(users) is not tuple or len(users) > 1024 or
            type(config_supported) is not bool or type(policy_supported) is not bool):
        raise ConfiguredCohortUnavailable()
    failed = False
    try:
        revision = _literal(configuration_revision, 512)
        _user(service_user, 'viewer')
        if token_id is not None:
            if (type(token_id) is not tuple or len(token_id) != 2 or
                    any(type(value) is not str for value in token_id) or
                    len(token_id[0]) > 257 or len(token_id[1]) > 128 or
                    _token_id({'api_token_id': token_id[0] + '!' + token_id[1]}) != token_id):
                raise ConfiguredCohortUnavailable()
        labels, recipients, rows = set(), set(), []
        for index, row in enumerate(nodes):
            if type(row) is not tuple or len(row) != 2:
                raise ConfiguredCohortUnavailable()
            label, literal = row
            _literal(label, 256)
            recipient, _version = _endpoint(literal)
            if label in labels or recipient in recipients:
                raise ConfiguredCohortUnavailable()
            labels.add(label)
            recipients.add(recipient)
            target = TargetSnapshot(revision, 'configured-node-' + str(index), literal)
            rows.append((label, target))
        roles = {}
        for row in users:
            if type(row) is not tuple or len(row) != 2:
                raise ConfiguredCohortUnavailable()
            username, role = _user(*row)
            if username in roles:
                raise ConfiguredCohortUnavailable()
            roles[username] = role
    except (PilotInputUnavailable, ValueError, ConfiguredCohortUnavailable):
        failed = True
    if failed:
        # No parser/native diagnostics, chained input objects or partial cohort.
        raise ConfiguredCohortUnavailable()
    return PilotConfiguredData(revision, tuple(rows), MappingProxyType(roles),
                               service_user, token_id, config_supported, policy_supported)


# No original startup factory, admission enablement, binding publication,
# acquisition, trusted revision generation or positive native lifecycle exists.
