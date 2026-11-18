"""Durable non-secret state for setup and init control workflows."""

import fcntl
import json
import os
import secrets
import stat
import time

from freq.core.log import _redact
from freq.core.types import INIT_PHASES, _InitControlState

SCHEMA = "zero-state-web-v1"
SETUP_TTL_SECONDS = 3600
_STATE_FILENAME = "zero-state-web.json"
_PHASES = {
    "collecting",
    "discovering",
    "selecting",
    "credentials",
    "ready",
    "initializing",
    "blocked",
}
_INIT_CONTROL_PAYLOADS = {
    _InitControlState.CANCEL_REQUESTED: b"cancel_requested\n",
    _InitControlState.POINT_OF_NO_RETURN: b"point_of_no_return\n",
}
_INIT_STATUS_PUBLIC_SCHEMA = "pve-freq-init-status-public-v1"
_INIT_STATUS_SCHEMAS = {"pve-freq-init-status-v1", "pve-freq-init-status-v2"}


def _is_init_control_run_id(run_id):
    """Return whether one value is the canonical private init run identity."""
    return (
        isinstance(run_id, str)
        and len(run_id) == 32
        and all(character in "0123456789abcdef" for character in run_id)
    )


def _init_control_path(cfg, run_id):
    """Return one canonical run-scoped control path without mutating disk."""
    data_dir = getattr(cfg, "data_dir", None)
    if (
        not isinstance(data_dir, str)
        or not data_dir
        or data_dir != data_dir.strip()
        or not os.path.isabs(data_dir)
        or data_dir.startswith(os.path.sep * 2)
        or data_dir != os.path.normpath(data_dir)
        or data_dir == os.path.sep
    ):
        raise ValueError("init control data directory must be canonical and absolute")
    if not _is_init_control_run_id(run_id):
        raise ValueError("init control run id must be exactly 32 lowercase hex characters")
    return os.path.join(data_dir, "init-control", f"{run_id}.state")


def _directory_open_flags():
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _open_init_data_dir(cfg, *, create):
    """Open the canonical data directory without following path-component links."""
    data_dir = os.path.dirname(
        os.path.dirname(_init_control_path(cfg, "0" * 32))
    )
    components = data_dir.removeprefix(os.path.sep).split(os.path.sep)
    from freq.core.read_source_epoch import _first

    if create:
        from freq.core.read_source_epoch import retire_process_reads

        retire_process_reads()
    current_fd = os.open(os.path.sep, _directory_open_flags())
    try:
        for index, component in enumerate(components):
            next_fd = None
            created = False
            try:
                next_fd = os.open(
                    component,
                    _directory_open_flags(),
                    dir_fd=current_fd,
                )
            except FileNotFoundError:
                if not create or index != len(components) - 1:
                    raise
                try:
                    os.mkdir(component, 0o700, dir_fd=current_fd)
                    created = True
                except FileExistsError:
                    pass
                next_fd = os.open(
                    component,
                    _directory_open_flags(),
                    dir_fd=current_fd,
                )
            try:
                if created:
                    os.fchmod(next_fd, 0o700)
                if create and index == len(components) - 1:
                    os.fsync(current_fd)
                closing_current_fd = current_fd
                current_fd = None  # No retry after an unknown close failure.
                os.close(closing_current_fd)
            except BaseException as error:
                if next_fd is not None:
                    closing_next_fd = next_fd
                    next_fd = None  # Attempt bookkeeping, not a completion claim.
                    try:
                        os.close(closing_next_fd)
                    except BaseException as cleanup_error:
                        if (issubclass(type(cleanup_error), OSError)
                                and not issubclass(type(cleanup_error), MemoryError)):
                            pass  # Preserve original ordinary next-close OSError ignore.
                        elif (not issubclass(type(error), Exception)
                                or issubclass(type(error), MemoryError)
                                or not issubclass(type(cleanup_error), Exception)
                                or issubclass(type(cleanup_error), MemoryError)):
                            raise _first(error, cleanup_error) from None
                        else:
                            raise
                raise
            current_fd = next_fd
            next_fd = None
        return current_fd
    except BaseException as error:
        if current_fd is not None:
            closing_current_fd = current_fd
            current_fd = None  # Attempt consumed, not physical release.
            try:
                os.close(closing_current_fd)
            except BaseException as cleanup_error:
                if (not issubclass(type(error), Exception)
                        or issubclass(type(error), MemoryError)
                        or not issubclass(type(cleanup_error), Exception)
                        or issubclass(type(cleanup_error), MemoryError)):
                    raise _first(error, cleanup_error) from None
                raise
        raise


def _open_init_control_dir(cfg, *, create):
    """Open the private control directory relative to a verified data-dir fd."""
    from freq.core.read_source_epoch import _first

    data_fd = _open_init_data_dir(cfg, create=create)
    control_fd = None
    body_failure = None
    try:
        try:
            control_fd = os.open(
                "init-control",
                _directory_open_flags(),
                dir_fd=data_fd,
            )
        except FileNotFoundError:
            if not create:
                raise
            try:
                os.mkdir("init-control", 0o700, dir_fd=data_fd)
            except FileExistsError:
                pass
            control_fd = os.open(
                "init-control",
                _directory_open_flags(),
                dir_fd=data_fd,
            )
        try:
            if create:
                os.fchmod(control_fd, 0o700)
                os.fsync(control_fd)
                os.fsync(data_fd)
            return control_fd
        except BaseException as error:
            closing_control_fd = control_fd
            control_fd = None  # Close eligibility consumed, not physical release.
            try:
                os.close(closing_control_fd)
            except BaseException as cleanup_error:
                if (not issubclass(type(error), Exception)
                        or issubclass(type(error), MemoryError)
                        or not issubclass(type(cleanup_error), Exception)
                        or issubclass(type(cleanup_error), MemoryError)):
                    raise _first(error, cleanup_error) from None
                raise
            raise
    except BaseException as error:
        body_failure = error
        raise
    finally:
        try:
            os.close(data_fd)
        except BaseException as cleanup_error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(cleanup_error), Exception)
                    or issubclass(type(cleanup_error), MemoryError)):
                body_failure = _first(body_failure, cleanup_error)
            else:
                body_failure = cleanup_error
            if control_fd is not None:
                # Parent close aborted the pending return of this known FD.
                closing_control_fd = control_fd
                control_fd = None  # No retry after this attempt, even if it fails.
                try:
                    os.close(closing_control_fd)
                except BaseException as cleanup_error:
                    if (not issubclass(type(body_failure), Exception)
                            or issubclass(type(body_failure), MemoryError)
                            or not issubclass(type(cleanup_error), Exception)
                            or issubclass(type(cleanup_error), MemoryError)):
                        body_failure = _first(body_failure, cleanup_error)
                    else:
                        body_failure = cleanup_error
            raise body_failure from None


def _prepare_init_control_dir(cfg):
    """Durably prepare one private dir for future run-control transitions."""
    control_dir = os.path.dirname(_init_control_path(cfg, "0" * 32))
    control_fd = _open_init_control_dir(cfg, create=True)
    os.close(control_fd)
    return control_dir


def _capture_init_control_topology(cfg):
    """Capture whether command-entry init control directories already exist."""
    control_dir = os.path.dirname(_init_control_path(cfg, "0" * 32))
    data_dir = os.path.dirname(control_dir)
    data_dir_existed = os.path.lexists(data_dir)
    control_dir_existed = os.path.lexists(control_dir)
    if control_dir_existed and not data_dir_existed:
        raise RuntimeError("init control topology changed during capture")
    return {
        "data_dir_existed": data_dir_existed,
        "control_dir_existed": control_dir_existed,
    }


def _open_absolute_directory(path):
    """Open one canonical absolute directory without following component links."""
    if (
        not isinstance(path, str)
        or not path
        or path != path.strip()
        or not os.path.isabs(path)
        or path.startswith(os.path.sep * 2)
        or path != os.path.normpath(path)
    ):
        raise ValueError("directory path must be canonical and absolute")
    from freq.core.read_source_epoch import _first

    current_fd = os.open(os.path.sep, _directory_open_flags())
    try:
        components = (
            []
            if path == os.path.sep
            else path.removeprefix(os.path.sep).split(os.path.sep)
        )
        for component in components:
            next_fd = os.open(
                component,
                _directory_open_flags(),
                dir_fd=current_fd,
            )
            closing_current_fd = current_fd
            current_fd = None  # Do not retry this close after unknown failure.
            try:
                os.close(closing_current_fd)
            except BaseException as error:
                closing_next_fd = next_fd
                next_fd = None  # Known unreturned next FD receives one attempt.
                try:
                    os.close(closing_next_fd)
                except BaseException as cleanup_error:
                    if (not issubclass(type(error), Exception)
                            or issubclass(type(error), MemoryError)
                            or not issubclass(type(cleanup_error), Exception)
                            or issubclass(type(cleanup_error), MemoryError)):
                        raise _first(error, cleanup_error) from None
                    raise
                raise
            current_fd = next_fd
            next_fd = None
        return current_fd
    except BaseException as error:
        if current_fd is not None:
            closing_current_fd = current_fd
            current_fd = None  # Attempt consumed, not physical release.
            try:
                os.close(closing_current_fd)
            except BaseException as cleanup_error:
                if (not issubclass(type(error), Exception)
                        or issubclass(type(error), MemoryError)
                        or not issubclass(type(cleanup_error), Exception)
                        or issubclass(type(cleanup_error), MemoryError)):
                    raise _first(error, cleanup_error) from None
                raise
        raise


def _rollback_init_control_topology(cfg, topology):
    """Remove only empty init control directories created after capture."""
    if (
        not isinstance(topology, dict)
        or set(topology) != {"data_dir_existed", "control_dir_existed"}
        or any(type(value) is not bool for value in topology.values())
    ):
        raise TypeError("init control topology snapshot is invalid")
    if topology["control_dir_existed"] and not topology["data_dir_existed"]:
        raise ValueError("init control topology snapshot is inconsistent")

    control_dir = os.path.dirname(_init_control_path(cfg, "0" * 32))
    data_dir = os.path.dirname(control_dir)
    if topology["control_dir_existed"]:
        return
    if not os.path.lexists(data_dir):
        if topology["data_dir_existed"]:
            raise FileNotFoundError(data_dir)
        return

    from freq.core.read_source_epoch import _first, retire_process_reads

    retire_process_reads()
    data_fd = _open_init_data_dir(cfg, create=False)
    body_failure = None
    try:
        try:
            os.rmdir(os.path.basename(control_dir), dir_fd=data_fd)
        except FileNotFoundError:
            pass
        else:
            os.fsync(data_fd)
    except BaseException as error:
        body_failure = error
        raise
    finally:
        try:
            os.close(data_fd)
        except BaseException as cleanup_error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(cleanup_error), Exception)
                    or issubclass(type(cleanup_error), MemoryError)):
                raise _first(body_failure, cleanup_error) from None
            raise

    if topology["data_dir_existed"]:
        return
    parent_fd = _open_absolute_directory(os.path.dirname(data_dir))
    body_failure = None
    try:
        try:
            os.rmdir(os.path.basename(data_dir), dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        else:
            os.fsync(parent_fd)
    except BaseException as error:
        body_failure = error
        raise
    finally:
        try:
            os.close(parent_fd)
        except BaseException as cleanup_error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(cleanup_error), Exception)
                    or issubclass(type(cleanup_error), MemoryError)):
                raise _first(body_failure, cleanup_error) from None
            raise


def _transition_init_control(cfg, run_id, requested_state):
    """Serialize one exact pre-PONR transition under an exclusive file lock."""
    if not isinstance(requested_state, _InitControlState) or requested_state not in {
        _InitControlState.CANCEL_REQUESTED,
        _InitControlState.POINT_OF_NO_RETURN,
    }:
        raise TypeError("unsupported init control transition")
    filename = os.path.basename(_init_control_path(cfg, run_id))
    from freq.core.read_source_epoch import _first, retire_process_reads

    retire_process_reads()

    flags = os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_fd = _open_init_control_dir(cfg, create=False)
    try:
        try:
            fd = os.open(
                filename,
                flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            fd = os.open(filename, flags, 0o600, dir_fd=directory_fd)
    except BaseException as error:
        try:
            os.close(directory_fd)
        except BaseException as cleanup_error:
            if (not issubclass(type(error), Exception)
                    or issubclass(type(error), MemoryError)
                    or not issubclass(type(cleanup_error), Exception)
                    or issubclass(type(cleanup_error), MemoryError)):
                raise _first(error, cleanup_error) from None
            raise
        raise
    body_failure = None
    try:
        control_stat = os.fstat(fd)
        if not stat.S_ISREG(control_stat.st_mode) or control_stat.st_nlink != 1:
            raise OSError("init control path is not a private regular file")
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        stream_failure = None
        try:
            with os.fdopen(fd, "r+b", closefd=False) as control_file:
                try:
                    raw = control_file.read()
                    if raw == b"":
                        current_state = _InitControlState.PRE_PONR
                    elif raw == _INIT_CONTROL_PAYLOADS[_InitControlState.CANCEL_REQUESTED]:
                        current_state = _InitControlState.CANCEL_REQUESTED
                    elif raw == _INIT_CONTROL_PAYLOADS[_InitControlState.POINT_OF_NO_RETURN]:
                        current_state = _InitControlState.POINT_OF_NO_RETURN
                    else:
                        raise ValueError("invalid init control state")

                    if current_state is _InitControlState.PRE_PONR:
                        os.fsync(directory_fd)

                    final_state = (
                        requested_state
                        if current_state is _InitControlState.PRE_PONR
                        else current_state
                    )
                    if final_state is not current_state:
                        control_file.seek(0)
                        control_file.truncate()
                        control_file.write(_INIT_CONTROL_PAYLOADS[final_state])
                        control_file.flush()
                        os.fsync(control_file.fileno())
                    return final_state
                except BaseException as error:
                    stream_failure = error
                    raise
        except BaseException as error:
            if stream_failure is not None and (
                    not issubclass(type(stream_failure), Exception)
                    or issubclass(type(stream_failure), MemoryError)
                    or not issubclass(type(error), Exception)
                    or issubclass(type(error), MemoryError)):
                raise _first(stream_failure, error) from None
            raise
    except BaseException as error:
        body_failure = error
        raise
    finally:
        failure = body_failure
        cleanup_failed = False
        try:
            os.close(fd)
        except BaseException as error:
            cleanup_failed = True
            if failure is not None and (
                    not issubclass(type(failure), Exception)
                    or issubclass(type(failure), MemoryError)
                    or not issubclass(type(error), Exception)
                    or issubclass(type(error), MemoryError)):
                failure = _first(failure, error)
            else:
                failure = error
        try:
            os.close(directory_fd)
        except BaseException as error:
            cleanup_failed = True
            if failure is not None and (
                    not issubclass(type(failure), Exception)
                    or issubclass(type(failure), MemoryError)
                    or not issubclass(type(error), Exception)
                    or issubclass(type(error), MemoryError)):
                failure = _first(failure, error)
            else:
                failure = error
        if cleanup_failed:
            raise failure from None


def _request_init_cancel(cfg, run_id):
    """Request cancellation iff the durable PONR claim has not won."""
    return _transition_init_control(cfg, run_id, _InitControlState.CANCEL_REQUESTED)


def _claim_init_point_of_no_return(cfg, run_id):
    """Claim PONR iff a durable cancellation request has not won."""
    return _transition_init_control(
        cfg,
        run_id,
        _InitControlState.POINT_OF_NO_RETURN,
    )


def _rollback_cancelled_init_control(cfg, run_id):
    """Remove one cancelled pre-PONR run artifact after its child unwinds."""
    filename = os.path.basename(_init_control_path(cfg, run_id))
    from freq.core.read_source_epoch import _first, retire_process_reads

    retire_process_reads()
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_fd = _open_init_control_dir(cfg, create=False)
    try:
        fd = os.open(filename, flags, dir_fd=directory_fd)
    except BaseException as error:
        try:
            os.close(directory_fd)
        except BaseException as cleanup_error:
            if (not issubclass(type(error), Exception)
                    or issubclass(type(error), MemoryError)
                    or not issubclass(type(cleanup_error), Exception)
                    or issubclass(type(cleanup_error), MemoryError)):
                raise _first(error, cleanup_error) from None
            raise
        raise
    body_failure = None
    try:
        control_stat = os.fstat(fd)
        if not stat.S_ISREG(control_stat.st_mode) or control_stat.st_nlink != 1:
            raise OSError("init control path is not a private regular file")
        fcntl.flock(fd, fcntl.LOCK_EX)
        stream_failure = None
        try:
            with os.fdopen(fd, "rb", closefd=False) as control_file:
                try:
                    if control_file.read() != _INIT_CONTROL_PAYLOADS[_InitControlState.CANCEL_REQUESTED]:
                        raise ValueError("init control rollback requires cancelled pre-PONR state")
                except BaseException as error:
                    stream_failure = error
                    raise
        except BaseException as error:
            if stream_failure is not None and (
                    not issubclass(type(stream_failure), Exception)
                    or issubclass(type(stream_failure), MemoryError)
                    or not issubclass(type(error), Exception)
                    or issubclass(type(error), MemoryError)):
                raise _first(stream_failure, error) from None
            raise
        control_stat = os.fstat(fd)
        if not stat.S_ISREG(control_stat.st_mode) or control_stat.st_nlink != 1:
            raise OSError("init control path is not a private regular file")
        os.unlink(filename, dir_fd=directory_fd)
        os.fsync(directory_fd)
    except BaseException as error:
        body_failure = error
        raise
    finally:
        failure = body_failure
        cleanup_failed = False
        try:
            os.close(fd)
        except BaseException as error:
            cleanup_failed = True
            if failure is not None and (
                    not issubclass(type(failure), Exception)
                    or issubclass(type(failure), MemoryError)
                    or not issubclass(type(error), Exception)
                    or issubclass(type(error), MemoryError)):
                failure = _first(failure, error)
            else:
                failure = error
        try:
            os.close(directory_fd)
        except BaseException as error:
            cleanup_failed = True
            if failure is not None and (
                    not issubclass(type(failure), Exception)
                    or issubclass(type(failure), MemoryError)
                    or not issubclass(type(error), Exception)
                    or issubclass(type(error), MemoryError)):
                failure = _first(failure, error)
            else:
                failure = error
        if cleanup_failed:
            raise failure from None


def _project_init_status(cfg):
    """Return one secret-free init-status view shared by CLI and web."""
    marker_path = os.path.join(cfg.conf_dir, ".initialized")
    status_path = os.path.join(cfg.conf_dir, "init-status.json")
    marker_exists = os.path.isfile(marker_path)
    try:
        with open(status_path, encoding="utf-8") as status_file:
            payload = json.load(status_file)
    except FileNotFoundError:
        payload = None
    except (OSError, ValueError, TypeError):
        payload = False

    def projection(state, *, initialized=False, phase=0, phase_key="", reason=""):
        return {
            "schema": _INIT_STATUS_PUBLIC_SCHEMA,
            "state": state,
            "initialized": initialized,
            "current_phase": phase,
            "current_phase_key": phase_key,
            "reason": reason,
        }

    if payload is None:
        if marker_exists:
            return projection(
                "succeeded",
                initialized=True,
                reason="freq init completed",
            )
        return projection("not_started", reason="freq init has not started")
    if payload is False or not isinstance(payload, dict):
        return projection("unknown", reason="init status is unreadable")
    if payload.get("schema") not in _INIT_STATUS_SCHEMAS:
        return projection("unknown", reason="init status schema is unsupported")

    phase_missing = "current_phase" not in payload
    phase_key_missing = "current_phase_key" not in payload
    if phase_missing != phase_key_missing:
        return projection("unknown", reason="init status phase identity is invalid")
    if phase_missing:
        phase = 0
        phase_key = ""
    else:
        phase = payload["current_phase"]
        phase_key = payload["current_phase_key"]
        if type(phase) is not int or not isinstance(phase_key, str):
            return projection("unknown", reason="init status phase identity is invalid")
        if phase == 0:
            phase_is_valid = phase_key == ""
        else:
            phase_is_valid = (
                1 <= phase <= len(INIT_PHASES)
                and phase_key == INIT_PHASES[phase - 1].key
            )
        if not phase_is_valid:
            return projection("unknown", reason="init status phase identity is invalid")

    raw_reason = payload.get("reason", "")
    failed_checks = payload.get("failed_checks", [])
    if not isinstance(raw_reason, str) or not isinstance(failed_checks, list) or any(
        not isinstance(item, str) for item in failed_checks
    ):
        return projection("unknown", reason="init status failure detail is invalid")
    reason = raw_reason.strip() or next(
        (item.strip() for item in failed_checks if item.strip()),
        "",
    )
    reason = _redact(reason)[:240]
    state = payload.get("state")
    initialized = payload.get("initialized")
    if not isinstance(initialized, bool):
        return projection("unknown", reason="init status completion truth is invalid")

    if marker_exists:
        if state in {None, "succeeded"} and initialized is True:
            return projection(
                "succeeded",
                initialized=True,
                phase=phase,
                phase_key=phase_key,
                reason=reason or "freq init completed",
            )
        return projection(
            "inconsistent",
            phase=phase,
            phase_key=phase_key,
            reason="init status conflicts with initialized marker",
        )
    if state == "running" and initialized is False:
        return projection(
            "running",
            phase=phase,
            phase_key=phase_key,
            reason=reason,
        )
    if (state in {None, "failed"}) and initialized is False and reason:
        return projection(
            "failed",
            phase=phase,
            phase_key=phase_key,
            reason=reason,
        )
    if state == "succeeded" or initialized is True:
        return projection(
            "inconsistent",
            phase=phase,
            phase_key=phase_key,
            reason="init status claims success without initialized marker",
        )
    return projection("unknown", reason="init status state is invalid")


def setup_state_path(cfg) -> str:
    return os.path.join(cfg.data_dir, "setup", _STATE_FILENAME)


def _atomic_write(path: str, payload: dict) -> None:
    from freq.core.read_source_epoch import retire_process_reads

    retire_process_reads()
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    os.chmod(tmp, 0o600)
    if os.path.exists(path):
        try:
            stat = os.stat(path)
            os.chown(tmp, stat.st_uid, stat.st_gid)
        except OSError:
            pass
    os.replace(tmp, path)


def clear_setup_state(cfg) -> None:
    from freq.core.read_source_epoch import retire_process_reads

    retire_process_reads()
    path = setup_state_path(cfg)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def load_setup_state(cfg, *, now: float | None = None) -> dict:
    """Load active state, deleting expired or malformed state fail-closed."""
    path = setup_state_path(cfg)
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return {}
    except PermissionError:
        # Callers must surface unreadable state as fail-closed blocked truth;
        # attempting cleanup here would turn a read failure into a second,
        # uncaught unlink failure.
        raise
    except (OSError, ValueError, TypeError):
        clear_setup_state(cfg)
        return {}
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        clear_setup_state(cfg)
        return {}
    clock = time.time() if now is None else now
    last_activity = float(state.get("last_activity_at") or state.get("created_at") or 0)
    if not last_activity or clock - last_activity > SETUP_TTL_SECONDS:
        clear_setup_state(cfg)
        return {}
    return state


def ensure_setup_state(cfg, username: str, *, now: float | None = None) -> dict:
    """Return the active setup identity, creating it when absent or expired."""
    clock = time.time() if now is None else now
    state = load_setup_state(cfg, now=clock)
    if state:
        if state.get("username") != username:
            raise ValueError("setup state belongs to another operator")
        return state
    state = {
        "schema": SCHEMA,
        "setup_id": secrets.token_urlsafe(24),
        "username": username,
        "phase": "collecting",
        "created_at": clock,
        "updated_at": clock,
        "last_activity_at": clock,
        "active_discovery_id": None,
        "active_contract_id": None,
        "active_init_job_id": None,
    }
    _atomic_write(setup_state_path(cfg), state)
    return state


def update_setup_state(cfg, *, now: float | None = None, **updates) -> dict:
    """Update allowlisted setup metadata without accepting arbitrary phases."""
    clock = time.time() if now is None else now
    state = load_setup_state(cfg, now=clock)
    if not state:
        raise ValueError("setup state is missing or expired")
    if "phase" in updates and updates["phase"] not in _PHASES:
        raise ValueError(f"invalid setup phase: {updates['phase']}")
    allowed = {
        "phase",
        "active_discovery_id",
        "active_contract_id",
        "active_init_job_id",
        "last_error_code",
    }
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported setup state fields: {', '.join(sorted(unknown))}")
    state.update(updates)
    state["updated_at"] = clock
    state["last_activity_at"] = clock
    _atomic_write(setup_state_path(cfg), state)
    return state


def touch_setup_state(cfg, *, now: float | None = None) -> dict:
    return update_setup_state(cfg, now=now)
