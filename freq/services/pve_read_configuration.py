"""Create-only local PVE read configuration; no auth, network or provider effects.

The API owner enforces admin/CSRF and reloads config after success. One exact
shared token covers at most eight endpoints. Existing configurations cannot be
updated here. Source gates coordinate participating writers in this process;
external writers and power-loss recovery are not transactionally covered.
Directories must already be provisioned and writable by the runtime owner.
"""
import hashlib
import ipaddress
import json
import os
import re
import secrets
import ssl
import stat
import threading
import tomllib

from freq.core.read_source_epoch import source_write

_MAX_CONFIG = 1024 * 1024
_MAX_CA = 64 * 1024
_LOCK = threading.Lock()
_KEYS = frozenset({"nodes", "node_names", "api_token_id", "api_token_secret_path",
                   "api_ca_path", "api_verify_ssl"})


class ConfigurationError(ValueError):
    """Only a fixed public code; never raw filesystem/credential exceptions."""
    def __init__(self, code="configuration_unavailable"):
        self.code = code
        super().__init__(code)


def _address(value):
    if type(value) is not str or not value or len(value) > 253:
        raise ConfigurationError("invalid_address")
    if not value.isascii() or any(c.isspace() for c in value) or "%" in value:
        raise ConfigurationError("invalid_address")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        labels = value.rstrip(".").split(".")
        if (not labels or all(c.isdigit() or c == "." for c in value)
                or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                       for label in labels)):
            raise ConfigurationError("invalid_address") from None
        return ".".join(labels).lower()


def _token(value):
    if (type(value) is not str or len(value) > 255
            or not re.fullmatch(r"[A-Za-z0-9._-]+@[A-Za-z0-9._-]+![A-Za-z0-9._-]+", value)):
        raise ConfigurationError("invalid_token")
    return value


def _validate(body):
    if (type(body) is not dict or set(body) - {"addresses", "token_id", "token_secret", "ca_pem"}
            or not {"addresses", "token_id", "token_secret"} <= set(body)):
        raise ConfigurationError("invalid_request")
    values = body["addresses"]
    if type(values) is not list or not 1 <= len(values) <= 8:
        raise ConfigurationError("invalid_address")
    addresses = [_address(value) for value in values]
    if len(set(addresses)) != len(addresses):
        raise ConfigurationError("invalid_address")
    token_id = _token(body["token_id"])
    secret = body["token_secret"]
    if (type(secret) is not str or not 1 <= len(secret) <= 4096
            or any(not 33 <= ord(c) <= 126 for c in secret)):
        raise ConfigurationError("invalid_token")
    ca = body.get("ca_pem")
    if type(ca) is str:
        if len(ca) > _MAX_CA:
            raise ConfigurationError("invalid_ca")
        if not ca.strip():
            ca = None
    if ca is not None:
        if (type(ca) is not str or not ca.isascii() or not 1 <= len(ca) <= _MAX_CA
                or "PRIVATE KEY" in ca):
            raise ConfigurationError("invalid_ca")
        # Accept certificate PEM blocks only, not paths, keys or arbitrary text.
        remainder = re.sub(r"-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----", "", ca)
        if remainder.strip() or "-----BEGIN CERTIFICATE-----" not in ca:
            raise ConfigurationError("invalid_ca")
        try:
            ssl.create_default_context(cadata=ca)
        except (ValueError, ssl.SSLError):
            raise ConfigurationError("invalid_ca") from None
    return addresses, token_id, secret.encode("ascii"), ca.encode("ascii") if ca is not None else None


def _directory(path):
    """Open only the authorized canonical runtime directory, never its parents.

    Reject symlink components before the no-follow leaf open. Concurrent
    external directory replacement is outside participating-process coverage.
    """
    if (type(path) is not str or not os.path.isabs(path)
            or os.path.normpath(path) != path
            or os.path.realpath(path, strict=True) != path):
        raise ConfigurationError()
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _read_config(fd):
    try:
        file_fd = os.open("freq.toml", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return None, None, {}
    with os.fdopen(file_fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_CONFIG or info.st_nlink != 1:
            raise ConfigurationError()
        raw = stream.read(_MAX_CONFIG + 1)
    if len(raw) > _MAX_CONFIG:
        raise ConfigurationError()
    data = tomllib.loads(raw.decode("utf-8"))
    if type(data.get("pve", {})) is not dict:
        raise ConfigurationError()
    return raw, info, data


def _projection(data):
    pve = data.get("pve", {})
    nodes = pve.get("nodes", [])
    if type(nodes) is not list or len(nodes) > 8:
        raise ConfigurationError()
    addresses = [_address(value) for value in nodes]
    token_id = pve.get("api_token_id") or pve.get("token_id") or ""
    if token_id:
        _token(token_id)
    return {"addresses": addresses,
            "token_principal": token_id.split("!", 1)[0],
            "ca_configured": bool(pve.get("api_ca_path"))}


def _render(raw, fields):
    """Replace only managed assignments in an explicit root [pve] table.

    Accumulating each TOML statement handles multiline strings/arrays without
    treating table-looking text inside them as a table header. Unrelated bytes
    and comments remain intact. Dotted-root pve declarations are refused.
    """
    text = raw.decode("utf-8") if raw is not None else ""
    output = []
    pending = ""
    in_pve = found = inserted = False
    additions = "".join(f"{key} = {json.dumps(value)}\n" if type(value) is not bool
                        else f"{key} = {str(value).lower()}\n" for key, value in fields.items())
    for line in text.splitlines(keepends=True):
        pending += line
        try:
            statement = tomllib.loads(pending)
        except tomllib.TOMLDecodeError:
            continue
        stripped = pending.lstrip()
        header = stripped.startswith("[")
        if header:
            if in_pve and not inserted:
                output.append(additions)
                inserted = True
            in_pve = statement == {"pve": {}}
            found = found or in_pve
        if not header and in_pve and set(statement) & _KEYS:
            pending = ""
            continue
        output.append(pending)
        pending = ""
    if pending:
        raise ConfigurationError()
    if in_pve and not inserted:
        if output and not output[-1].endswith("\n"):
            output.append("\n")
        output.append(additions)
    elif not found:
        if output and not output[-1].endswith("\n"):
            output.append("\n")
        output.append("\n[pve]\n" + additions)
    result = "".join(output).encode("utf-8")
    original = tomllib.loads(text)
    expected = dict(original)
    expected["pve"] = dict(original.get("pve", {}), **fields)
    if tomllib.loads(result.decode("utf-8")) != expected:
        raise ConfigurationError()
    return result


def _create(fd, name, data, created, mode=0o600, owner=None):
    file_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    created.append((fd, name))
    with os.fdopen(file_fd, "wb") as stream:
        if owner is not None:
            info = os.fstat(stream.fileno())
            if (info.st_uid, info.st_gid) != owner:
                os.fchown(stream.fileno(), *owner)
        os.fchmod(stream.fileno(), mode)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _same_config(fd, expected):
    actual, _, _ = _read_config(fd)
    return actual == expected


def _rollback(fd, old_raw, old_info, new_raw, created):
    """Confirm restoration before allowing removal of referenced credentials."""
    if _same_config(fd, old_raw):
        return
    if not _same_config(fd, new_raw):
        raise ConfigurationError()
    if old_raw is None:
        os.unlink("freq.toml", dir_fd=fd)
    else:
        name = ".pve-read-rollback-" + secrets.token_hex(16)
        _create(fd, name, old_raw, created, stat.S_IMODE(old_info.st_mode), (old_info.st_uid, old_info.st_gid))
        os.replace(name, "freq.toml", src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)
    if not _same_config(fd, old_raw):
        raise ConfigurationError()


def _cleanup(created):
    failed = False
    for fd, name in reversed(created):
        try:
            os.unlink(name, dir_fd=fd)
        except FileNotFoundError:
            pass
        except OSError:
            failed = True
    if failed:
        raise ConfigurationError()


def _configure(cfg, body):
    addresses, token_id, secret, ca = _validate(body)
    conf_fd = cred_fd = None
    created = []
    committed = attempted = False
    old_raw = old_info = new_raw = None
    try:
        conf_fd = _directory(cfg.conf_dir)
        cred_fd = _directory(cfg.credentials_dir)
        transaction = source_write()
        try:
            with transaction:
                old_raw, old_info, data = _read_config(conf_fd)
                pve = data.get("pve", {})
                if (getattr(cfg, "pve_nodes", None) or getattr(cfg, "pve_api_token_id", None)
                        or getattr(cfg, "pve_api_token_secret", None)
                        or any(pve.get(key) for key in ("nodes", "api_token_id", "token_id",
                                                       "api_token_secret_path", "token_secret_file", "api_token_secret", "token_secret", "api_ca_path"))):
                    raise ConfigurationError("already_configured")
                # The old resolver must not replace the entered token with a
                # principal plus synthesized per-node token identifier.
                for name in ["pve-token-rw"] + [
                        "pve-token-rw-" + hashlib.sha256(address.encode()).hexdigest()[:12]
                        for address in addresses]:
                    try:
                        os.stat(name, dir_fd=cred_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    raise ConfigurationError("already_configured")
                suffix = secrets.token_hex(16)
                secret_name = "pve-read-token-" + suffix
                ca_name = "pve-read-ca-" + suffix
                fields = {"nodes": addresses, "node_names": [],
                          "api_token_id": token_id,
                          "api_token_secret_path": os.path.join(cfg.credentials_dir, secret_name),
                          "api_ca_path": os.path.join(cfg.credentials_dir, ca_name) if ca is not None else "",
                          "api_verify_ssl": True}
                new_raw = _render(old_raw, fields)
                if len(new_raw) > _MAX_CONFIG:
                    raise ConfigurationError()
                try:
                    _create(cred_fd, secret_name, secret, created)
                    if ca is not None:
                        _create(cred_fd, ca_name, ca, created)
                    os.fsync(cred_fd)
                    temp = ".pve-read-config-" + suffix
                    _create(conf_fd, temp, new_raw, created,
                            stat.S_IMODE(old_info.st_mode) if old_info else 0o600,
                            (old_info.st_uid, old_info.st_gid) if old_info else None)
                    if not _same_config(conf_fd, old_raw):
                        raise ConfigurationError()
                    attempted = True
                    os.replace(temp, "freq.toml", src_dir_fd=conf_fd, dst_dir_fd=conf_fd)
                    os.fsync(conf_fd)
                    if not _same_config(conf_fd, new_raw):
                        raise ConfigurationError()
                    committed = True
                except BaseException:
                    if attempted:
                        _rollback(conf_fd, old_raw, old_info, new_raw, created)
                        attempted = False
                    _cleanup(created)
                    raise
        except BaseException:
            # An uncertain gate-exit may follow the final config commit. Only
            # a fresh admitted writer may restore it. If that cannot finish,
            # leave all possibly referenced credential files in place.
            if committed:
                rollback_transaction = source_write()
                with rollback_transaction:
                    _rollback(conf_fd, old_raw, old_info, new_raw, created)
                committed = attempted = False
                _cleanup(created)
            elif not attempted:
                _cleanup(created)
            raise
        return _projection({"pve": fields})
    finally:
        if cred_fd is not None:
            os.close(cred_fd)
        if conf_fd is not None:
            os.close(conf_fd)


def configure_pve_read(cfg, body):
    """Persist one create-only batch. The API must authenticate the admin."""
    if not _LOCK.acquire(blocking=False):
        raise ConfigurationError()
    try:
        return _configure(cfg, body)
    except MemoryError:
        raise
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError() from None
    finally:
        _LOCK.release()


def get_pve_read_configuration(cfg):
    """Read passive metadata under the local lock, never observation authority.

    First-admin preparation permanently retires source_read in this process.
    That gate belongs to original qualified reads, not this secret-free local
    configuration projection. Atomic replacement supplies a complete document;
    _LOCK excludes this helper's concurrent writes. External writers remain
    outside that coordination.
    """
    if not _LOCK.acquire(blocking=False):
        raise ConfigurationError()
    try:
        fd = _directory(cfg.conf_dir)
        try:
            _, _, data = _read_config(fd)
            return _projection(data)
        finally:
            os.close(fd)
    except MemoryError:
        raise
    except Exception:
        raise ConfigurationError() from None
    finally:
        _LOCK.release()
