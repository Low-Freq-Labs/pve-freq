"""Durable one-time bearer claim for first-admin creation.

The raw claim exists only long enough to reach the caller-supplied delivery
sink.  Product state retains a domain-separated digest and a non-secret
generation identifier; verification and terminal consumption are serialized
through one stable private lock file.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import stat
import time
from dataclasses import dataclass
from typing import Callable, Iterator


SCHEMA = "pve-freq-first-admin-claim-v1"
_DIGEST_DOMAIN = b"pve-freq-first-admin-claim-v1\0"
_STATE_NAME = "first-admin-claim.json"
_LOCK_NAME = ".first-admin-claim.lock"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class ClaimStateError(RuntimeError):
    """Claim state cannot be trusted or durably changed."""


def claim_state_path(cfg) -> str:
    return os.path.join(cfg.data_dir, "setup", _STATE_NAME)


def _claim_dir(cfg) -> str:
    return os.path.dirname(claim_state_path(cfg))


def _state_unavailable(exc: BaseException | str) -> ClaimStateError:
    detail = str(exc) or type(exc).__name__
    return ClaimStateError(f"claim state unavailable: {detail}")


def _ensure_private_directory(path: str) -> None:
    try:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            os.makedirs(path, mode=0o700, exist_ok=True)
            info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise OSError("setup claim path is not a private directory")
        if stat.S_IMODE(info.st_mode) != 0o700:
            os.chmod(path, 0o700)
            info = os.lstat(path)
            if stat.S_IMODE(info.st_mode) != 0o700:
                raise PermissionError("could not enforce setup directory mode")
    except (OSError, ValueError) as exc:
        raise _state_unavailable(exc) from exc


def _validate_private_file(fd: int, *, repair_mode: bool = True) -> os.stat_result:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise OSError("claim artifact is not a regular file")
    if info.st_nlink != 1:
        raise OSError("claim artifact has an unsafe link count")
    if stat.S_IMODE(info.st_mode) != 0o600:
        if not repair_mode:
            raise PermissionError("claim artifact is not private")
        os.fchmod(fd, 0o600)
        info = os.fstat(fd)
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise PermissionError("could not enforce claim artifact mode")
    return info


def _open_lock(cfg) -> int:
    from freq.core.read_source_epoch import retire_process_reads, _first

    retire_process_reads()
    directory = _claim_dir(cfg)
    _ensure_private_directory(directory)
    path = os.path.join(directory, _LOCK_NAME)
    flags = os.O_RDWR | os.O_CREAT | _NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
        try:
            _validate_private_file(fd)
        except BaseException as body_error:
            try:
                os.close(fd)
            except BaseException as cleanup_error:
                if (not issubclass(type(body_error), Exception)
                        or issubclass(type(body_error), MemoryError)
                        or not issubclass(type(cleanup_error), Exception)
                        or issubclass(type(cleanup_error), MemoryError)):
                    raise _first(body_error, cleanup_error) from None
                raise
            raise
        return fd
    except (OSError, ValueError) as exc:
        raise _state_unavailable(exc) from exc


def _valid_timestamp(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _validate_record(record) -> dict:
    if not isinstance(record, dict):
        raise ValueError("claim record is not an object")
    state_name = record.get("state")
    allowed = {
        "pending_delivery": {"schema", "state", "claim_id", "digest", "generated_at"},
        "available": {
            "schema",
            "state",
            "claim_id",
            "digest",
            "generated_at",
            "delivered_at",
        },
        "consumed": {"schema", "state", "claim_id", "generated_at", "consumed_at"},
    }
    if state_name not in allowed or set(record) != allowed[state_name]:
        raise ValueError("claim record fields or state are invalid")
    if record.get("schema") != SCHEMA:
        raise ValueError("claim record schema is invalid")
    claim_id = record.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id or len(claim_id) > 256:
        raise ValueError("claim identifier is invalid")
    if not _valid_timestamp(record.get("generated_at")):
        raise ValueError("claim generation timestamp is invalid")
    if state_name in {"pending_delivery", "available"}:
        digest = record.get("digest")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("claim digest is invalid")
        if any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("claim digest is invalid")
    if state_name == "available":
        delivered_at = record.get("delivered_at")
        if not _valid_timestamp(delivered_at) or delivered_at < record["generated_at"]:
            raise ValueError("claim delivery timestamp is invalid")
    if state_name == "consumed":
        consumed_at = record.get("consumed_at")
        if not _valid_timestamp(consumed_at) or consumed_at < record["generated_at"]:
            raise ValueError("claim consumption timestamp is invalid")
    return dict(record)


def _read_record(cfg, *, allow_missing: bool = False) -> tuple[dict | None, os.stat_result | None]:
    from freq.core.read_source_epoch import _first

    path = claim_state_path(cfg)
    try:
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
    except FileNotFoundError:
        if allow_missing:
            return None, None
        raise _state_unavailable("claim record is missing")
    except (OSError, ValueError) as exc:
        raise _state_unavailable(exc) from exc
    body_failure = None
    try:
        try:
            info = _validate_private_file(fd)
            chunks = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(map(len, chunks)) > 65536:
                    raise ValueError("claim record is too large")
            record = json.loads(b"".join(chunks).decode("utf-8"))
            return _validate_record(record), info
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise _state_unavailable(exc) from exc
    except BaseException as error:
        body_failure = error
        raise
    finally:
        try:
            os.close(fd)
        except BaseException as cleanup_error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(cleanup_error), Exception)
                    or issubclass(type(cleanup_error), MemoryError)):
                raise _first(body_failure, cleanup_error) from None
            raise


def _atomic_write(cfg, record: dict, previous: os.stat_result | None = None) -> os.stat_result:
    from freq.core.read_source_epoch import _first

    directory = _claim_dir(cfg)
    path = claim_state_path(cfg)
    temp_path = os.path.join(directory, f".{_STATE_NAME}.{secrets.token_hex(8)}.tmp")
    dir_fd = -1
    temp_fd = -1
    body_failure = None
    try:
        try:
            dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW
            dir_fd = os.open(directory, dir_flags)
            temp_fd = os.open(
                temp_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
                0o600,
            )
            _validate_private_file(temp_fd, repair_mode=False)
            if previous is not None:
                os.fchown(temp_fd, previous.st_uid, previous.st_gid)
            payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            offset = 0
            while offset < len(payload):
                written = os.write(temp_fd, payload[offset:])
                if written <= 0:
                    raise OSError("short claim-state write")
                offset += written
            os.fsync(temp_fd)
            closing_temp_fd = temp_fd
            temp_fd = -1  # No further close attempt; physical completion is unknown.
            os.close(closing_temp_fd)
            os.replace(temp_path, path)
            os.fsync(dir_fd)
            state_fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
            state_failure = None
            try:
                return _validate_private_file(state_fd)
            except BaseException as error:
                state_failure = error
                raise
            finally:
                try:
                    os.close(state_fd)
                except BaseException as cleanup_error:
                    if state_failure is not None and (
                            not issubclass(type(state_failure), Exception)
                            or issubclass(type(state_failure), MemoryError)
                            or not issubclass(type(cleanup_error), Exception)
                            or issubclass(type(cleanup_error), MemoryError)):
                        raise _first(state_failure, cleanup_error) from None
                    raise
        except (OSError, ValueError, TypeError) as exc:
            raise _state_unavailable(exc) from exc
    except BaseException as error:
        body_failure = error
        raise
    finally:
        cleanup_failed = False
        try:
            if temp_fd >= 0:
                closing_temp_fd = temp_fd
                temp_fd = -1  # Attempt consumed, not a release or completion claim.
                os.close(closing_temp_fd)
        except BaseException as cleanup_error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(cleanup_error), Exception)
                    or issubclass(type(cleanup_error), MemoryError)):
                body_failure = _first(body_failure, cleanup_error)
            else:
                body_failure = cleanup_error
            cleanup_failed = True
        try:
            if dir_fd >= 0:
                os.close(dir_fd)
        except BaseException as cleanup_error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(cleanup_error), Exception)
                    or issubclass(type(cleanup_error), MemoryError)):
                body_failure = _first(body_failure, cleanup_error)
            else:
                body_failure = cleanup_error
            cleanup_failed = True
        try:
            os.unlink(temp_path)
        except BaseException as cleanup_error:
            if (issubclass(type(cleanup_error), OSError)
                    and not issubclass(type(cleanup_error), MemoryError)):
                pass
            else:
                if body_failure is not None and (
                        not issubclass(type(body_failure), Exception)
                        or issubclass(type(body_failure), MemoryError)
                        or not issubclass(type(cleanup_error), Exception)
                        or issubclass(type(cleanup_error), MemoryError)):
                    body_failure = _first(body_failure, cleanup_error)
                else:
                    body_failure = cleanup_error
                cleanup_failed = True
        if cleanup_failed:
            raise body_failure from None


def _digest(candidate: str) -> str:
    return hashlib.sha256(_DIGEST_DOMAIN + candidate.encode("utf-8")).hexdigest()


@dataclass
class ClaimTransaction:
    cfg: object
    _record: dict | None = None
    _file_info: os.stat_result | None = None

    def _ensure_loaded(self) -> None:
        if self._record is None or self._file_info is None:
            self._record, self._file_info = _read_record(self.cfg)

    @property
    def state_name(self) -> str:
        self._ensure_loaded()
        assert self._record is not None
        return self._record["state"]

    @property
    def claim_id(self) -> str:
        self._ensure_loaded()
        assert self._record is not None
        return self._record["claim_id"]

    def matches(self, candidate) -> bool:
        if self.state_name != "available":
            return False
        assert self._record is not None
        if not isinstance(candidate, str) or not candidate or len(candidate) > 256:
            return False
        try:
            candidate_digest = _digest(candidate)
        except UnicodeEncodeError:
            return False
        return hmac.compare_digest(self._record["digest"], candidate_digest)

    def consume(self, *, now: float | None = None) -> None:
        if self.state_name == "consumed":
            return
        assert self._record is not None and self._file_info is not None
        consumed_at = time.time() if now is None else now
        record = {
            "schema": SCHEMA,
            "state": "consumed",
            "claim_id": self._record["claim_id"],
            "generated_at": self._record["generated_at"],
            "consumed_at": consumed_at,
        }
        _validate_record(record)
        self._file_info = _atomic_write(self.cfg, record, self._file_info)
        self._record = record


@contextlib.contextmanager
def locked_first_admin_claim(cfg) -> Iterator[ClaimTransaction]:
    from freq.core.read_source_epoch import _first

    lock_fd = _open_lock(cfg)
    acquire_returned = False
    body_failure = None
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        acquire_returned = True
        yield ClaimTransaction(cfg)
    except BaseException as error:
        body_failure = error
        raise
    finally:
        cleanup_failed = False
        try:
            if acquire_returned:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except BaseException as cleanup_error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(cleanup_error), Exception)
                    or issubclass(type(cleanup_error), MemoryError)):
                body_failure = _first(body_failure, cleanup_error)
            else:
                body_failure = cleanup_error
            cleanup_failed = True
        try:
            os.close(lock_fd)
        except BaseException as cleanup_error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(cleanup_error), Exception)
                    or issubclass(type(cleanup_error), MemoryError)):
                body_failure = _first(body_failure, cleanup_error)
            else:
                body_failure = cleanup_error
            cleanup_failed = True
        if cleanup_failed:
            raise body_failure from None


def _prepare_zero_state(
    cfg,
    *,
    deliver: Callable[[str, str, float], None],
    now: float,
) -> dict:
    from freq.core.read_source_epoch import _first

    lock_fd = _open_lock(cfg)
    acquire_returned = False
    body_failure = None
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        acquire_returned = True
        record, info = _read_record(cfg, allow_missing=True)
        if record is not None and record["state"] == "available":
            return {
                "state": "available",
                "claim_id": record["claim_id"],
                "generated": False,
                "delivered": False,
            }
        if record is not None and record["state"] == "consumed":
            return {
                "state": "consumed",
                "claim_id": record["claim_id"],
                "generated": False,
                "delivered": False,
            }

        claim_id = secrets.token_hex(16)
        secret = secrets.token_urlsafe(32)
        pending = {
            "schema": SCHEMA,
            "state": "pending_delivery",
            "claim_id": claim_id,
            "digest": _digest(secret),
            "generated_at": now,
        }
        info = _atomic_write(cfg, pending, info)
        try:
            deliver(claim_id, secret, now)
        except MemoryError:
            raise
        except Exception as exc:
            raise ClaimStateError(f"claim delivery failed: {exc}") from exc
        available = {
            **pending,
            "state": "available",
            "delivered_at": now,
        }
        _atomic_write(cfg, available, info)
        return {
            "state": "available",
            "claim_id": claim_id,
            "generated": True,
            "delivered": True,
        }
    except BaseException as error:
        body_failure = error
        raise
    finally:
        cleanup_failed = False
        try:
            if acquire_returned:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except BaseException as cleanup_error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(cleanup_error), Exception)
                    or issubclass(type(cleanup_error), MemoryError)):
                body_failure = _first(body_failure, cleanup_error)
            else:
                body_failure = cleanup_error
            cleanup_failed = True
        try:
            os.close(lock_fd)
        except BaseException as cleanup_error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(cleanup_error), Exception)
                    or issubclass(type(cleanup_error), MemoryError)):
                body_failure = _first(body_failure, cleanup_error)
            else:
                body_failure = cleanup_error
            cleanup_failed = True
        if cleanup_failed:
            raise body_failure from None


def prepare_first_admin_claim(
    cfg,
    *,
    users_present: bool,
    setup_complete: bool,
    deliver: Callable[[str, str, float], None],
    warn: Callable[[str], None],
    now: float | None = None,
) -> dict:
    """Reconcile configured state or prepare exactly one first-boot claim."""
    observed_at = time.time() if now is None else now
    if users_present or setup_complete:
        claim_id = ""
        try:
            with locked_first_admin_claim(cfg) as transaction:
                claim_id = transaction.claim_id
                if transaction.state_name != "consumed":
                    transaction.consume(now=observed_at)
        except ClaimStateError as exc:
            warn(f"First-admin claim cleanup skipped after setup: {exc}")
        result = {"state": "configured", "generated": False, "delivered": False}
        if claim_id:
            result["claim_id"] = claim_id
        return result
    return _prepare_zero_state(cfg, deliver=deliver, now=observed_at)
