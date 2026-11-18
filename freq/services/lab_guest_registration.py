"""Local, expiring lab qualification manifest; this module supplies no target.

Only the installation owner can publish the manifest and protected token file.
Loading one validates local evidence, not provider identity or live authority.
"""

from dataclasses import dataclass, field
import datetime
import hashlib
import ipaddress
import json
import math
import os
import re
import ssl
import stat
import sys
import uuid


MAX_MANIFEST = 65536
MAX_SECRET = 4096
MAX_CA = 262144
_FIELDS = frozenset(("schema", "registration_id", "qualified_at", "expires_at",
                     "lab_only", "estate", "provider", "node", "guest_type", "vmid",
                     "name", "instance_uuid", "allowed_actions", "credentials", "qualification_ref"))
_NODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+![A-Za-z0-9_.-]+\Z")


class RegistrationError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _protected_read(path, limit, *, secret=False, ca=False):
    """Open every absolute path component without following symlinks.

    The descriptor's complete before/after metadata must match. Parent directory
    ownership is left to installation provisioning; no file path is returned in
    errors. A file can still be replaced after this bounded observation.
    """
    code = "credentials_unavailable" if secret or ca else "registration_unavailable"
    if (type(path) is not str or not path.startswith("/") or "\x00" in path
            or os.path.normpath(path) != path or path.startswith("//")):
        raise RegistrationError(code)
    directory = descriptor = None
    try:
        parts = path.split("/")[1:]
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise RegistrationError(code)
        # Traversal needs search permission, not permission to list a directory.
        directory_flags = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY
        directory = os.open("/", directory_flags)
        for part in parts[:-1]:
            next_directory = os.open(part, directory_flags | os.O_NOFOLLOW,
                                     dir_fd=directory)
            os.close(directory)
            directory = next_directory
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        before = os.fstat(descriptor)
        owners = (os.geteuid(), 0) if ca else (os.geteuid(),)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid not in owners
                or before.st_nlink != 1 or before.st_size > limit
                or before.st_mode & 0o022
                or (secret and stat.S_IMODE(before.st_mode) != 0o600)):
            raise RegistrationError(code)
        chunks = bytearray()
        while len(chunks) <= limit:
            chunk = os.read(descriptor, min(65536, limit + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        after = os.fstat(descriptor)
        attrs = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
                 "st_size", "st_mtime_ns", "st_ctime_ns")
        if (len(chunks) > limit or len(chunks) != before.st_size
                or any(getattr(before, attr) != getattr(after, attr) for attr in attrs)):
            raise RegistrationError(code)
        return bytes(chunks)
    except MemoryError:
        raise
    except (OSError, ValueError):
        raise RegistrationError(code) from None
    finally:
        pending, cleanup_error = sys.exception(), None
        for opened in (descriptor, directory):
            if opened is None:
                continue
            try:
                os.close(opened)
            except MemoryError as failure:
                cleanup_error = failure
            except OSError:
                if cleanup_error is None:
                    cleanup_error = RegistrationError(code)
        if cleanup_error is not None and (pending is None or (
                isinstance(cleanup_error, MemoryError) and not isinstance(pending, MemoryError))):
            raise cleanup_error


def read_token_secret(path):
    raw = _protected_read(path, MAX_SECRET, secret=True)
    if raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n"):
        raw = raw[:-1]
    if not raw or any(byte < 33 or byte > 126 for byte in raw):
        raise RegistrationError("credentials_unavailable")
    return raw.decode("ascii")


def read_ca(path):
    raw = _protected_read(path, MAX_CA, ca=True)
    try:
        text = raw.decode("ascii")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=text)
    except MemoryError:
        raise
    except (ValueError, UnicodeError, ssl.SSLError):
        raise RegistrationError("credentials_unavailable") from None
    return raw


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RegistrationError("invalid_registration")
        result[key] = value
    return result


def _constant(_value):
    raise RegistrationError("invalid_registration")


def _text(value, maximum=256):
    return (type(value) is str and 0 < len(value) <= maximum and bool(value.strip())
            and not any(ord(char) < 32 or 127 <= ord(char) <= 159
                        or 0xD800 <= ord(char) <= 0xDFFF for char in value))


def valid_provider(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", value):
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
                   for part in value.split("."))


def _utc(value):
    if (type(value) is not str or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value)):
        raise RegistrationError("invalid_registration")
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RegistrationError("invalid_registration") from None


@dataclass(frozen=True)
class Registration:
    registration_id: str
    qualified_at: str
    expires_at: str
    estate: str
    provider: str
    node: str
    guest_type: str
    vmid: int
    name: str
    instance_uuid: str
    allowed_actions: tuple
    qualification_ref: str
    revision: str
    token_id: str = field(repr=False)
    token_secret_file: str = field(repr=False)
    ca_file: str = field(repr=False)

    def public_view(self):
        return {"schema": "pve-freq-lab-guest-v1", "lab_only": True,
                **{name: getattr(self, name) for name in (
                    "registration_id", "qualified_at", "expires_at", "estate", "provider",
                    "node", "guest_type", "vmid", "name", "instance_uuid", "revision")},
                "allowed_actions": list(self.allowed_actions)}


def load_registration(cfg, now=None, *, allow_expired=False):
    path = os.path.join(cfg.conf_dir, "lab-guest.json")
    raw = _protected_read(path, MAX_MANIFEST)
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        if type(document) is not dict or set(document) != _FIELDS:
            raise RegistrationError("invalid_registration")
        if (document["schema"] != "pve-freq-lab-guest-v1" or document["lab_only"] is not True
                or document["guest_type"] != "qemu" or type(document["vmid"]) is not int
                or not 0 < document["vmid"] <= 2**53 - 1
                or not valid_provider(document["provider"])
                or type(document["node"]) is not str or not _NODE.fullmatch(document["node"])
                or not all(_text(document[key]) for key in ("estate", "name", "qualification_ref"))):
            raise RegistrationError("invalid_registration")
        registration_uuid = uuid.UUID(document["registration_id"])
        if document["registration_id"] not in (registration_uuid.hex, str(registration_uuid)):
            raise RegistrationError("invalid_registration")
        if str(uuid.UUID(document["instance_uuid"])) != document["instance_uuid"]:
            raise RegistrationError("invalid_registration")
        qualified, expires = _utc(document["qualified_at"]), _utc(document["expires_at"])
        current = datetime.datetime.now(datetime.timezone.utc) if now is None else (now() if callable(now) else now)
        if type(current) in (int, float) and math.isfinite(current):
            current = datetime.datetime.fromtimestamp(current, datetime.timezone.utc)
        if (not isinstance(current, datetime.datetime) or current.tzinfo is None
                or current.utcoffset() != datetime.timedelta(0)):
            raise RegistrationError("invalid_registration")
        if expires <= qualified or qualified > current or (expires <= current and allow_expired is not True):
            raise RegistrationError("registration_expired")
        actions = document["allowed_actions"]
        if (type(actions) is not list or not actions or not all(type(item) is str for item in actions)
                or len(set(actions)) != len(actions) or "status" not in actions
                or not set(actions) <= {"status", "start", "shutdown"}):
            raise RegistrationError("invalid_registration")
        credentials = document["credentials"]
        if (type(credentials) is not dict or set(credentials) != {"token_id", "token_secret_file", "ca_file"}
                or type(credentials["token_id"]) is not str or len(credentials["token_id"]) > 256
                or not _TOKEN.fullmatch(credentials["token_id"])):
            raise RegistrationError("invalid_registration")
        read_token_secret(credentials["token_secret_file"])
        read_ca(credentials["ca_file"])
        values = {key: document[key] for key in _FIELDS - {"schema", "lab_only", "credentials", "allowed_actions"}}
        return Registration(**values, allowed_actions=tuple(actions),
                            revision=hashlib.sha256(raw).hexdigest(), **credentials)
    except MemoryError:
        raise
    except RegistrationError:
        raise
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        raise RegistrationError("invalid_registration") from None
