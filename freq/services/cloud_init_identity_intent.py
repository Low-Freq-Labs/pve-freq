"""Pure bounded identity patch DATA; no credential or installed-image authority.

Input keys are submitted public material, never approved merely by parsing.
Password references are opaque caller DATA, not resolved secret versions.
No file/key discovery, private material, provider serializer or effect occurs.
The original target/profile/credential owner must validate every future use.
"""
import base64
import binascii
from dataclasses import dataclass
import hashlib
import re


class InvalidIdentityIntent(ValueError):
    """Fixed nonsensitive refusal; submitted values are never in the message."""


@dataclass(frozen=True, slots=True, repr=False)
class IdentityFieldPatch:
    action: str
    value: object


@dataclass(frozen=True, slots=True, repr=False)
class SubmittedPublicKey:
    normalized_text: str
    fingerprint: str


@dataclass(frozen=True, slots=True, repr=False)
class PasswordReferenceData:
    credential_ref: str
    version: str


@dataclass(frozen=True, slots=True, repr=False)
class IdentityPatch:
    ciuser: IdentityFieldPatch
    public_keys: IdentityFieldPatch
    password_reference: IdentityFieldPatch
    citype: IdentityFieldPatch
    ciupgrade: IdentityFieldPatch


_RETAIN = IdentityFieldPatch('retain', None)
_USER = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]{0,63}\Z')
_REF = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
_KEY_PREFIX = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20'


def _bad():
    raise InvalidIdentityIntent('Invalid or unsupported identity patch') from None


def _shape(value, allowed, required=()):
    if (type(value) is not dict or len(value) > len(allowed) or
            any(type(key) is not str for key in value) or
            not set(required) <= value.keys() <= set(allowed)):
        _bad()


def _action(value):
    _shape(value, ('action', 'value'), ('action',))
    action = value['action']
    if type(action) is not str or action not in ('retain', 'set', 'clear', 'inherit'):
        _bad()
    if (action == 'set') != ('value' in value):
        _bad()
    return action


def _public_key(value):
    # Deliberate first wire subset: no comments, authorized_keys options,
    # alternate algorithms, certificates or line endings. Not curve validation,
    # possession, trust, approval, usable credentials or guest compatibility.
    if type(value) is not str or not 1 <= len(value) <= 1024 or not value.isascii():
        _bad()
    parts = value.split(' ')
    if len(parts) != 2 or parts[0] != 'ssh-ed25519':
        _bad()
    failed = False
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except (binascii.Error, ValueError):
        failed = True
    if failed:
        _bad()
    if (len(blob) != 51 or not blob.startswith(_KEY_PREFIX) or
            base64.b64encode(blob).decode('ascii') != parts[1]):
        _bad()
    fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode('ascii').rstrip('=')
    return SubmittedPublicKey(value, fingerprint)


def _value(key, value):
    if key == 'ciuser':
        # Limited explicit guest-name DATA subset, not host account selection.
        if type(value) is not str or not 1 <= len(value) <= 64 or not _USER.fullmatch(value):
            _bad()
        return value
    if key == 'public_keys':
        if type(value) is not list or not 1 <= len(value) <= 32:
            _bad()
        # Check aggregate input size before any key decoding or hashing.
        total = 0
        for text in value:
            if type(text) is not str or not 1 <= len(text) <= 1024 or not text.isascii():
                _bad()
            total += len(text)
            if total > 32768:
                _bad()
        rows, seen = [], set()
        for text in value:
            row = _public_key(text)
            if row.normalized_text in seen:
                _bad()
            seen.add(row.normalized_text)
            rows.append(row)
        return tuple(rows)
    if key == 'password_reference':
        _shape(value, ('credential_ref', 'version'), ('credential_ref', 'version'))
        reference, version = value['credential_ref'], value['version']
        if (type(reference) is not str or not _REF.fullmatch(reference) or
                type(version) is not str or not _REF.fullmatch(version) or
                version.lower() in ('latest', 'current', 'default')):
            _bad()
        return PasswordReferenceData(reference, version)
    if key == 'citype':
        if type(value) is not str or value not in ('nocloud', 'configdrive2', 'opennebula'):
            _bad()
        return value
    if key == 'ciupgrade':
        if type(value) is not bool:
            _bad()
        return value
    _bad()


def normalize_identity_patch(value):
    """Preserve five independent actions, with omission meaning retain only.

    Clear/inherit are unresolved product intents, never command deletion or
    implicit defaults. Public-key fingerprints bind exact parsed wire bytes
    only. A password reference does not prove secret existence/version/trust;
    password hashing/serialization/application remains unsupported here.
    citype/ciupgrade values do not establish an image profile or package policy.
    Returned frozen records are caller-constructible DATA, never an issuer.
    """
    keys = ('ciuser', 'public_keys', 'password_reference', 'citype', 'ciupgrade')
    _shape(value, keys)
    rows = []
    for key in keys:
        if key not in value:
            rows.append(_RETAIN)
            continue
        action = _action(value[key])
        rows.append(IdentityFieldPatch(action,
            _value(key, value[key]['value']) if action == 'set' else None))
    return IdentityPatch(*rows)
