"""Read-only projections of ORIGINAL configured inputs; data, never authority.

The original native startup owner must acquire complete bounded bytes, retain
their actual source/writer/currentness and original deadline, and settle native
resources. These pure functions cannot open paths, load config, decrypt a Vault,
issue an installation/user/session/selection, or authorize any provider call.
No legacy loader/bootstrap/migration or request-supplied override is used.

Preserve original users precedence: nonempty TOML users, users.conf, roles.conf.
Unlike the permissive utility, ambiguous/malformed input refuses the complete
pilot view instead of silently publishing a successful subset.
"""
import ipaddress
import re
import tomllib


_MAX_INPUT = 1048576
_MAX_USERS = 1024
_USER = re.compile(r'[a-z_][a-z0-9_-]{0,31}', re.ASCII)
_ROLES = ('viewer', 'operator', 'admin', 'protected')


class PilotInputUnavailable(Exception):
    def __init__(self):
        super().__init__('Pilot configured input unavailable')


def _text(raw):
    if type(raw) is not bytes or len(raw) > _MAX_INPUT:
        raise PilotInputUnavailable()
    try:
        return raw.decode('utf-8', 'strict')
    except UnicodeError:
        raise PilotInputUnavailable() from None


def _literal(value, maximum):
    if (type(value) is not str or not value or
            any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xd800 <= ord(c) <= 0xdfff
                for c in value) or len(value.encode('utf-8')) > maximum):
        raise PilotInputUnavailable()
    return value


def _user(username, role):
    if (type(username) is not str or _USER.fullmatch(username) is None or
            type(role) is not str or role not in _ROLES):
        raise PilotInputUnavailable()
    return username, role


def _user_rows(document, users_raw, roles_raw):
    users = document.get('users', {})
    if type(users) is not dict:
        raise PilotInputUnavailable()
    rows = []
    if users:
        if len(users) > _MAX_USERS:
            raise PilotInputUnavailable()
        for username, info in users.items():
            if type(info) is not dict:
                raise PilotInputUnavailable()
            # Original TOML loader defaults missing role to viewer. Groups
            # are not used for this read-only application disclosure.
            rows.append(_user(username, info.get('role', 'viewer')))
    else:
        if users_raw is not None:
            for line in _text(users_raw).splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) not in (2, 3):
                    raise PilotInputUnavailable()
                rows.append(_user(parts[0], parts[1]))
                if len(rows) > _MAX_USERS:
                    raise PilotInputUnavailable()
        if not rows and roles_raw is not None:
            for line in _text(roles_raw).splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.count(':') != 1:
                    raise PilotInputUnavailable()
                username, role = line.split(':')
                rows.append(_user(username.strip(), role.strip()))
                if len(rows) > _MAX_USERS:
                    raise PilotInputUnavailable()
    if len({username for username, _ in rows}) != len(rows):
        raise PilotInputUnavailable()
    return tuple(rows)


def _token_id(pve):
    canonical = pve.get('api_token_id', '')
    legacy = pve.get('token_id', '')
    if type(canonical) is not str or type(legacy) is not str:
        raise PilotInputUnavailable()
    if canonical and legacy and canonical != legacy:
        raise PilotInputUnavailable()
    value = canonical or legacy
    if not value:
        return None
    if (not value.isascii() or len(value) > 386 or value.count('!') != 1 or
            value.count('@') != 1):
        raise PilotInputUnavailable()
    principal, token = value.split('!')
    if principal.count('@') != 1:
        raise PilotInputUnavailable()
    user, realm = principal.split('@')
    if not all(re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', part, re.ASCII)
               for part in (user, realm, token)):
        raise PilotInputUnavailable()
    return principal, token


def decode_retained_original_inputs(config_raw, users_raw=None, roles_raw=None):
    """Project complete retained bytes; None means native-confirmed absence.

    The caller may not turn a failed native read into None/empty bytes. A
    missing configured token ID is retained as None, never a shared-secret or
    SSH fallback. Missing trust/per-node secret resources must still make the
    actual installation unavailable before it can issue any selection.

    The TOML input byte cap does not establish a total heap/CPU bound. tomllib
    parsing and the complete native read need the original supervised worker
    and its qualified end/resource budget; this function alone supplies none.
    """
    if users_raw is not None and (type(users_raw) is not bytes or len(users_raw) > _MAX_INPUT):
        raise PilotInputUnavailable()
    if roles_raw is not None and (type(roles_raw) is not bytes or len(roles_raw) > _MAX_INPUT):
        raise PilotInputUnavailable()
    try:
        document = tomllib.loads(_text(config_raw))
    except (ValueError, RecursionError):
        raise PilotInputUnavailable() from None
    if type(document) is not dict:
        raise PilotInputUnavailable()
    pve, ssh = document.get('pve', {}), document.get('ssh', {})
    if type(pve) is not dict or type(ssh) is not dict:
        raise PilotInputUnavailable()
    endpoints = pve.get('nodes', [])
    labels = pve.get('node_names', [])
    if (type(endpoints) is not list or type(labels) is not list or
            len(endpoints) != len(labels) or len(endpoints) > 1024):
        raise PilotInputUnavailable()
    nodes = []
    for endpoint, label in zip(endpoints, labels):
        if (type(endpoint) is not str or not endpoint.isascii() or
                not 0 < len(endpoint) <= 45 or '%' in endpoint):
            raise PilotInputUnavailable()
        try:
            ipaddress.ip_address(endpoint)
        except ValueError:
            raise PilotInputUnavailable() from None
        # Retain original configured spelling for per-node secret path custody;
        # transport normalization never repairs its registration or identity.
        nodes.append((_literal(label, 256), endpoint))
    if (len({label for label, _ in nodes}) != len(nodes) or
            len({str(ipaddress.ip_address(endpoint)) for _, endpoint in nodes}) != len(nodes)):
        raise PilotInputUnavailable()
    service = ssh.get('service_account', 'freq-admin')
    if type(service) is not str:
        raise PilotInputUnavailable()
    service = service.strip().lower()
    if _USER.fullmatch(service) is None:
        raise PilotInputUnavailable()
    return (tuple(nodes), _user_rows(document, users_raw, roles_raw),
            service, _token_id(pve))


def exact_original_auth_hash(plaintext_raw, configured_username):
    """Select only existing auth/password_USER, with NO DEFAULT fallback.

    Retained bounded output from original OpenSSL AES-256-CBC/PBKDF2 read is
    required. This function does no decryption, store initialization, write,
    repair, migration or password verification. Its string return is private
    hash DATA, not a configured-user/lease/session grant. No logging/diagnostic
    includes the input or any value. Python strings are not securely erased.
    """
    _user(configured_username, 'viewer')  # Canonical scalar validation only.
    key = 'password_' + configured_username
    found = None
    for line in _text(plaintext_raw).splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('|', 2)
        if len(parts) != 3:
            raise PilotInputUnavailable()
        host, name, value = parts
        if host != 'auth' or name != key:
            continue
        if found is not None:
            raise PilotInputUnavailable()
        if '$' in value:
            if value.count('$') != 1:
                raise PilotInputUnavailable()
            salt, digest = value.split('$')
            if (len(salt.encode('utf-8')) > 256 or
                    any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in salt)):
                raise PilotInputUnavailable()
        else:
            digest = value
        if re.fullmatch(r'[0-9a-f]{64}', digest, re.ASCII) is None:
            raise PilotInputUnavailable()
        found = value
    return found


# No main/import hooks, file paths, native source issuance or effectful loader.
