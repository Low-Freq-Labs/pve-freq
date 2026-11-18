"""Encrypted credential vault for FREQ.

Domain: freq secure <vault-get|vault-set|vault-list|vault-delete|vault-export>

AES-256-CBC encrypted credential store. Secrets stored as HOST|KEY|VALUE
pipe-delimited entries, encrypted at rest via OpenSSL. Key derived from
/etc/machine-id so the vault is machine-bound. v1.0.0 compatible.

Replaces: HashiCorp Vault ($1,152/mo+ post-IBM), plaintext .env files,
          password managers for infrastructure secrets

Architecture:
    - Layer: core credential storage, safe for API consumers to import downward
    - Encryption: OpenSSL aes-256-cbc with PBKDF2 key derivation
    - Key source: SHA256 of /etc/machine-id (machine-bound, no master password)
    - Storage: single encrypted file in conf/vault.enc
    - Format: pipe-delimited HOST|KEY|VALUE, one entry per line (pre-encryption)

Design decisions:
    - Machine-bound key, not user-bound. The vault belongs to the FREQ
      installation, not a person. Any FREQ user on this machine can access it.
      This is intentional — FREQ is a shared infrastructure tool.
"""

import getpass
import hashlib
import os
import subprocess
import threading

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.read_source_epoch import source_write
from freq.core.vault_key_input import _VaultKeyReadDuty, _VaultKeyReadUnavailable
from freq.core.vault_decrypt_input import _VaultDecryptReadDuty, _VaultDecryptReadUnavailable
from freq.core.vault_pipe_input import _VaultPipeReadDuty, _VaultPipeReadUnavailable
from freq.core.vault_child_input import _VaultChildReadDuty, _VaultChildReadUnavailable
from freq.core.vault_child_context import _VaultChildContextDuty, _VaultChildContextUnavailable
from freq.core.vault_child_constructor import _VaultChildConstructorDuty, _VaultChildConstructorUnavailable

# Vault timeouts
VAULT_CRYPTO_TIMEOUT = 10
_VAULT_LOCK = threading.RLock()


_VAULT_KEY_READ_OMITTED = object()


class _VaultKeyReadContext:
    """Observe the original built-in file protocol, without another close."""
    __slots__ = ('leaf', 'exit_method')

    def __init__(self, leaf):
        self.leaf = leaf
        self.exit_method = None

    def __enter__(self):
        leaf = self.leaf
        handle = leaf.handle
        leaf.enter_stage = 'pending'
        enter = type(handle).__enter__
        self.exit_method = type(handle).__exit__
        entered = enter(handle)
        leaf.entered_handle = entered
        leaf.enter_stage = 'returned'
        return entered

    def __exit__(self, kind, failure, traceback):
        leaf = self.leaf
        leaf.exit_stage = 'pending'
        result = self.exit_method(leaf.handle, kind, failure, traceback)
        leaf.exit_stage = 'returned'
        return result


def _vault_key(*, _key_read=_VAULT_KEY_READ_OMITTED) -> str:
    """Derive encryption key from machine-id (SHA256 hex digest).

    Same derivation as v1.0.0 bash: cat /etc/machine-id | openssl dgst -sha256
    """
    if _key_read is _VAULT_KEY_READ_OMITTED:
        for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
            try:
                with open(path) as f:
                    machine_id = f.read().strip()
                    return hashlib.sha256(machine_id.encode()).hexdigest()
            except FileNotFoundError:
                continue
        return ""
    if type(_key_read) is not _VaultKeyReadDuty:
        raise _VaultKeyReadUnavailable()
    try:
        _key_read.enter_reader()
        for leaf in _key_read.leaves:
            if leaf.used:
                _key_read.refuse()
            leaf.used = True
            leaf.outcome = 'pending'
            # Allocate protocol metadata before the original open. The same
            # returned file receives the same raw body in its original exit.
            leaf.context = _VaultKeyReadContext(leaf)
            leaf.open_stage = 'pending'
            try:
                handle = open(leaf.path)
                leaf.handle = handle
                leaf.open_stage = 'returned'
            except FileNotFoundError as failure:
                leaf.remember(failure)
                leaf.open_stage = leaf.outcome = 'reported-missing'
                continue
            except BaseException as failure:
                leaf.remember(failure)
                raise leaf.failure from None
            try:
                with leaf.context as f:
                    try:
                        if f is not handle:
                            raise _VaultKeyReadUnavailable()
                        leaf.body_stage = leaf.read_stage = 'pending'
                        machine_id = f.read()
                        leaf.read_stage = 'returned'
                        leaf.hash_stage = 'pending'
                        machine_id = machine_id.strip()
                        key = hashlib.sha256(machine_id.encode()).hexdigest()
                        leaf.hash_stage = leaf.body_stage = 'returned'
                    except BaseException as failure:
                        leaf.body_failure = failure
                        leaf.remember(failure)
                        raise
            except BaseException as failure:
                leaf.context_failure = failure
                leaf.remember(failure)
            if leaf.failure is not None:
                if (issubclass(type(leaf.failure), FileNotFoundError)
                        and leaf.failure is leaf.body_failure
                        and leaf.context_failure is leaf.body_failure
                        and leaf.enter_stage == 'returned'
                        and leaf.entered_handle is handle
                        and leaf.exit_stage == 'returned'):
                    leaf.outcome = 'reported-missing'
                    continue
                raise leaf.failure from None
            if (leaf.enter_stage != 'returned' or leaf.exit_stage != 'returned'
                    or leaf.body_stage != 'returned'):
                _key_read.refuse()
            leaf.outcome = 'key'
            _key_read.outcome = 'key'
            _key_read.reader_stage = 'returned'
            return key
        _key_read.outcome = 'empty'
        _key_read.reader_stage = 'returned'
        return ''
    except BaseException as failure:
        _key_read.remember(failure)
        raise _key_read.failure from None


def _exit_required_openssl_child_context(child, cleanup, exit_method, kind, body, traceback):
    """Draft fixed intended context duties; no physical/resource grant."""
    if type(cleanup) is not _VaultChildContextDuty:
        raise _VaultChildContextUnavailable()
    try:
        cleanup.enter(child, child.handle, body)
        handle = cleanup.handle
        if (type(handle) is not subprocess.Popen
                or exit_method is not subprocess.Popen.__exit__):
            cleanup.refuse()
        cleanup.selector_stage = 'pending'
        special = kind == KeyboardInterrupt
        cleanup.mode = 'keyboard-original' if special else 'normal'
        cleanup.selector_stage = 'returned'
        if special:
            cleanup.special_stage = 'pending'
            try:
                result = exit_method(handle, kind, body, traceback)
            except BaseException as failure:
                cleanup.special_failure = failure
                cleanup.remember(failure)
            else:
                cleanup.special_stage = 'returned'
            # Stored original Control must not disappear after delegated exit.
            if cleanup.failure is not None:
                raise cleanup.failure from None
            cleanup.refuse()
        for leaf, name in zip(cleanup.leaves, ('stdout', 'stderr', 'stdin')):
            try:
                if leaf.root is not cleanup or leaf.name != name or leaf.used:
                    cleanup.refuse()
                leaf.used = True
                leaf.lookup_stage = 'pending'
                stream = getattr(handle, name)
                leaf.handle = stream
                leaf.lookup_stage = 'returned'
                leaf.truth_stage = 'pending'
                present = bool(stream)
                leaf.truth_stage = 'returned'
                if not present:
                    if stream is not None:
                        cleanup.refuse()
                    leaf.outcome = 'absent-field'
                    continue
                leaf.outcome = 'present-field'
                leaf.close_stage = 'pending'
                stream.close()
                leaf.close_stage = 'returned'
            except BaseException as failure:
                leaf.remember(failure)
        cleanup.wait_stage = 'pending'
        try:
            handle.wait()
        except BaseException as failure:
            cleanup.wait_failure = failure
            cleanup.remember(failure)
        else:
            cleanup.wait_stage = 'returned'
        if cleanup.failure is not None:
            raise cleanup.failure from None
        cleanup.helper_stage = 'returned'
        return None
    except BaseException as failure:
        cleanup.remember(failure)
        raise cleanup.failure from None


class _VaultChildReadContext:
    """Observe the returned Popen protocol; no manual stream close or wait."""
    __slots__ = ('root', 'exit_method', 'cleanup')

    def __init__(self, root):
        self.root = root
        self.exit_method = None
        self.cleanup = root.context_read

    def __enter__(self):
        root, handle = self.root, self.root.handle
        root.enter_stage = 'pending'
        self.exit_method = type(handle).__exit__
        enter = type(handle).__enter__
        process = enter(handle)
        root.entered_handle = process
        root.enter_stage = 'returned'
        return process

    def __exit__(self, kind, failure, traceback):
        root = self.root
        root.exit_stage = 'pending'
        cleanup = self.cleanup
        result = _exit_required_openssl_child_context(
            root, cleanup, self.exit_method, kind, failure, traceback)
        if type(cleanup) is not _VaultChildContextDuty:
            raise _VaultChildContextUnavailable()
        cleanup.caller_returned = True
        if (root.context_read is not cleanup or not cleanup.matches(root)
                or not cleanup.known()):
            cleanup.refuse()
        root.exit_stage = 'returned'
        return result


def _construct_required_openssl_child(args, *, stdin, stdout, stderr, pass_fds, _constructor):
    """Draft supported plain allocation/init split; holds unknown partial self."""
    if type(_constructor) is not _VaultChildConstructorDuty:
        raise _VaultChildConstructorUnavailable()
    root = _constructor
    try:
        root.enter(root.child_read, args, stdin, stdout, stderr, pass_fds)
        root.class_stage = 'pending'
        provider = subprocess.Popen
        if type(provider) is not type:
            root.refuse()
        bases, mapping = provider.__bases__, provider.__dict__
        initializer = mapping.get('__init__')
        if (type(bases) is not tuple or len(bases) != 1 or bases[0] is not object
                or '__new__' in mapping or provider.__new__ is not object.__new__
                or type(initializer) is not type(_construct_required_openssl_child)):
            root.refuse()
        root.provider, root.initializer = provider, initializer
        root.class_stage = 'returned'
        root.allocation_stage = 'pending'
        handle = object.__new__(provider)
        root.handle = handle
        root.allocation_stage = 'returned'
        if (type(handle) is not provider or subprocess.Popen is not provider
                or provider.__dict__.get('__init__') is not initializer
                or not root.matches(root.child_read)):
            root.refuse()
        root.init_stage = 'pending'
        outcome = initializer(handle, args, stdin=stdin, stdout=stdout,
                              stderr=stderr, pass_fds=pass_fds)
        root.init_stage = 'returned'
        root.policy_stage = 'pending'
        if outcome is not None:
            root.outcome = 'invalid-return'
            root.refuse()
        root.outcome = 'none'
        root.policy_stage = 'returned'
        if root.failure is not None:
            raise root.failure from None
        if (subprocess.Popen is not provider
                or provider.__dict__.get('__init__') is not initializer
                or not root.matches(root.child_read)):
            root.refuse()
        root.helper_stage = 'returned'
        return handle
    except BaseException as failure:
        root.remember(failure)
        # No extra close/signal/wait/__del__/retry/GC after partial init.
        raise root.failure from None


def _run_required_openssl_child(args, *, input, capture_output, timeout, pass_fds, _child):
    """Fixed POSIX run subset with the original Popen context, no native proof."""
    if type(_child) is not _VaultChildReadDuty:
        raise _VaultChildReadUnavailable()
    try:
        _child.enter(args, input, capture_output, timeout, pass_fds)
        _child.context = _VaultChildReadContext(_child)
        constructor = _child.constructor_read
        if (type(constructor) is not _VaultChildConstructorDuty
                or not constructor.matches(_child) or not constructor.unused()):
            _child.refuse()
        _child.constructor_stage = 'pending'
        handle = _construct_required_openssl_child(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, pass_fds=pass_fds, _constructor=constructor,
        )
        _child.handle = handle
        constructor.caller_returned = True
        if (_child.constructor_read is not constructor or not constructor.matches(_child)
                or handle is not constructor.handle or not constructor.known()
                or subprocess.Popen is not constructor.provider
                or constructor.provider.__dict__.get('__init__') is not constructor.initializer):
            constructor.refuse()
        _child.constructor_stage = 'returned'
        try:
            with _child.context as process:
                try:
                    if process is not handle:
                        _child.refuse()
                    _child.body_stage = _child.communicate_stage = 'pending'
                    try:
                        pair = process.communicate(input, timeout=timeout)
                        _child.communicate_stage = 'returned'
                        _child.unpack_stage = 'pending'
                        stdout, stderr = pair
                        _child.unpack_stage = 'returned'
                    except subprocess.TimeoutExpired as failure:
                        _child.remember(0, failure)
                        _child.kill_stage = 'pending'
                        process.kill()
                        _child.kill_stage = 'returned'
                        _child.timeout_wait_stage = 'pending'
                        process.wait()
                        _child.timeout_wait_stage = 'returned'
                        raise _child.failure from None
                    except BaseException as failure:
                        _child.remember(0, failure)
                        _child.kill_stage = 'pending'
                        process.kill()
                        _child.kill_stage = 'returned'
                        raise _child.failure from None
                    _child.poll_stage = 'pending'
                    retcode = process.poll()
                    _child.poll_stage = _child.body_stage = 'returned'
                except BaseException as failure:
                    _child.remember(1, failure)
                    # Deliver the selected original raw body to original exit.
                    raise _child.failure from None
        except BaseException as failure:
            _child.context_failure = failure
            _child.remember(2, failure)
        if _child.failure is not None:
            raise _child.failure from None
        if (_child.enter_stage != 'returned' or _child.entered_handle is not handle
                or _child.exit_stage != 'returned' or _child.body_stage != 'returned'):
            _child.refuse()
        _child.result_stage = 'pending'
        result = subprocess.CompletedProcess(process.args, retcode, stdout, stderr)
        _child.result_stage = 'returned'
        _child.helper_stage = 'returned'
        return result
    except BaseException as failure:
        _child.remember(3, failure)
        raise _child.failure from None


_VAULT_PIPE_READ_OMITTED = object()


def _run_openssl_with_key(args: list, key: str, stdin_data: bytes = b"", *, _pipe=_VAULT_PIPE_READ_OMITTED) -> subprocess.CompletedProcess:
    """Run openssl with the password supplied via an inherited pipe FD.

    F4 of R-SECURITY-TRUST-AUDIT-20260413P. Pre-fix the vault key was
    interpolated into the openssl command line as `-pass pass:KEY`, which
    landed the key in argv → /proc/<pid>/cmdline → world-readable on
    Linux. Even though the vault's documented threat model already says
    any local FREQ user can derive the key from /etc/machine-id, the
    cmdline form added a window where any non-FREQ process scraping
    /proc/<pid>/cmdline could grab the key without ever touching the
    machine-id file.

    The fd: form passes the key via an inherited pipe descriptor:
    openssl reads it from FD N, never sees argv. The descriptor is
    passed via subprocess.pass_fds so the child inherits it.
    """
    if _pipe is _VAULT_PIPE_READ_OMITTED:
        # Allocate raw storage before the original native pipe acquisition.
        failures = [None] * 3
        write_close_entered = read_close_entered = False
        result = None
        r_fd, w_fd = os.pipe()
        try:
            try:
                os.write(w_fd, key.encode() + b"\n")
                write_close_entered = True
                os.close(w_fd)
                result = subprocess.run(
                    args + ["-pass", f"fd:{r_fd}"],
                    input=stdin_data,
                    capture_output=True,
                    timeout=VAULT_CRYPTO_TIMEOUT,
                    pass_fds=[r_fd],
                )
            except BaseException as failure:
                failures[0] = failure
        finally:
            if not write_close_entered:
                # An uncertain close is consumed before entry, never retried.
                write_close_entered = True
                try:
                    os.close(w_fd)
                except BaseException as failure:
                    failures[1] = failure
            # Independent original read-end cleanup still runs if write close failed.
            if not read_close_entered:
                read_close_entered = True
                try:
                    os.close(r_fd)
                except BaseException as failure:
                    failures[2] = failure
        first = None
        for failure in failures:
            if failure is not None and (first is None
                    or issubclass(type(first), Exception) and (
                        not issubclass(type(failure), Exception)
                        or not issubclass(type(first), MemoryError)
                        and issubclass(type(failure), MemoryError))):
                first = failure
        if first is not None:
            raise first from None
        return result
    if type(_pipe) is not _VaultPipeReadDuty:
        raise _VaultPipeReadUnavailable()
    write_close_entered = read_close_entered = False
    result = None
    try:
        _pipe.enter(args)
        child_read = _pipe.child_read
        if (type(child_read) is not _VaultChildReadDuty
                or not child_read.matches(_pipe) or child_read.used is not False):
            _pipe.refuse()
        if type(stdin_data) is not bytes or stdin_data != b'':
            _pipe.refuse()
        _pipe.pair_stage = 'pending'
        pair = os.pipe()
        _pipe.pair = pair
        _pipe.pair_stage = 'returned'
        _pipe.unpack_stage = 'pending'
        r_fd, w_fd = pair
        _pipe.read_fd, _pipe.write_fd = r_fd, w_fd
        _pipe.unpack_stage = 'returned'
        if not _pipe.pair_known():
            _pipe.refuse()
    except BaseException as failure:
        # No guessed close after unknown return/unpack; retain the actual pair.
        _pipe.remember(0, failure)
        raise _pipe.failure from None
    try:
        try:
            _pipe.payload_stage = 'pending'
            payload = key.encode() + b'\n'
            _pipe.payload_stage = 'returned'
            _pipe.write_stage = 'pending'
            _pipe.write_count = os.write(w_fd, payload)
            _pipe.write_stage = 'returned'
            write_close_entered = True
            _pipe.write_close_stage = 'pending'
            os.close(w_fd)
            _pipe.write_close_stage = 'returned'
            _pipe.process_stage = 'pending'
            result = _run_required_openssl_child(
                args + ['-pass', f'fd:{r_fd}'],
                input=stdin_data,
                capture_output=True,
                timeout=VAULT_CRYPTO_TIMEOUT,
                pass_fds=[r_fd], _child=child_read,
            )
            child_read.caller_returned = True
            if (_pipe.child_read is not child_read or not child_read.matches(_pipe)
                    or not child_read.known()):
                child_read.refuse()
            _pipe.process_stage = 'returned'
        except BaseException as failure:
            _pipe.remember(0, failure)
    finally:
        if not write_close_entered:
            write_close_entered = True
            _pipe.write_close_stage = 'pending'
            try:
                os.close(w_fd)
            except BaseException as failure:
                _pipe.remember(1, failure)
            else:
                _pipe.write_close_stage = 'returned'
        if not read_close_entered:
            read_close_entered = True
            _pipe.read_close_stage = 'pending'
            try:
                os.close(r_fd)
            except BaseException as failure:
                _pipe.remember(2, failure)
            else:
                _pipe.read_close_stage = 'returned'
    if _pipe.failure is not None:
        raise _pipe.failure from None
    _pipe.helper_stage = 'returned'
    return result


def _encrypt(plaintext: str, key: str, vault_path: str) -> bool:
    """Encrypt plaintext and write to vault file.

    R-REDTEAM-SECURITY-ASSAULT-20260413T T-9: writes are now atomic
    (openssl -out tmp → os.rename). Pre-fix `openssl enc -out` wrote
    directly to the live vault path, so a concurrent reader during
    the ~100ms encrypt window saw a half-written file and got an
    empty decrypt — observable as transient `/api/auth/login` 401s
    right after `freq user dashboard-passwd` landed a new password
    hash (the 401/401/200 sequence Finn reported on 5005).

    Also preserves the existing file's uid/gid before rename so a
    sudo'd CLI write (e.g. `sudo freq user dashboard-passwd`) doesn't
    flip ownership to root:root and lock the dashboard service account
    out of its own vault until someone manually chowns it back.
    """
    tmp_path = vault_path + ".tmp"
    try:
        r = _run_openssl_with_key(
            ["openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2", "-out", tmp_path],
            key,
            stdin_data=plaintext.encode(),
        )
        if r.returncode != 0:
            logger.error(f"vault encrypt failed: {r.stderr.decode()}")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False

        # Preserve existing vault ownership so a sudo'd write doesn't
        # flip uid/gid to root. First write of a fresh vault will keep
        # the tmp file's original ownership (whatever the caller is).
        if os.path.exists(vault_path):
            try:
                st = os.stat(vault_path)
                os.chown(tmp_path, st.st_uid, st.st_gid)
            except OSError as e:
                logger.warn(f"vault chown preserve failed: {e}")

        try:
            os.chmod(tmp_path, 0o600)
        except OSError as e:
            logger.warn(f"vault chmod failed: {e}")

        # Atomic rename — concurrent readers see either the old file
        # or the new file, never a partial one.
        os.rename(tmp_path, vault_path)
        return True
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.error(f"vault encrypt error: {e}")
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False


_VAULT_DECRYPT_READ_OMITTED = object()


def _decrypt(key: str, vault_path: str, *, _read=_VAULT_DECRYPT_READ_OMITTED) -> str:
    """Decrypt vault file and return plaintext."""
    if _read is _VAULT_DECRYPT_READ_OMITTED:
        if not os.path.exists(vault_path):
            return ""
        try:
            r = _run_openssl_with_key(
                ["openssl", "enc", "-aes-256-cbc", "-d", "-salt", "-pbkdf2", "-in", vault_path],
                key,
            )
            if r.returncode == 0:
                return r.stdout.decode("utf-8")
            return ""
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
            return ""
    if type(_read) is not _VaultDecryptReadDuty:
        raise _VaultDecryptReadUnavailable()
    try:
        _read.enter_helper(vault_path)
        _read.exists_stage = 'pending'
        exists = os.path.exists(vault_path)
        _read.exists_stage = 'returned'
        if not exists:
            _read.exists_outcome = 'missing'
            _read.outcome = 'missing-policy-empty'
            _read.helper_stage = 'returned'
            return ''
        _read.exists_outcome = 'present'
        try:
            try:
                _read.provider_stage = 'pending'
                pipe_read = _read.pipe_read
                if (type(pipe_read) is not _VaultPipeReadDuty
                        or pipe_read.decrypt_read is not _read
                        or pipe_read.lookup is not _read.lookup
                        or pipe_read.key_read is not _read.key_read
                        or pipe_read.directory is not _read.directory
                        or pipe_read.launch is not _read.launch or pipe_read.job is not _read.job
                        or pipe_read.cfg is not _read.cfg or pipe_read.used is not False):
                    _read.refuse()
                r = _run_openssl_with_key(
                    ["openssl", "enc", "-aes-256-cbc", "-d", "-salt", "-pbkdf2", "-in", vault_path],
                    key, _pipe=pipe_read,
                )
                if type(pipe_read) is not _VaultPipeReadDuty:
                    raise _VaultPipeReadUnavailable()
                pipe_read.caller_returned = True
                if (_read.pipe_read is not pipe_read or pipe_read.decrypt_read is not _read
                        or not pipe_read.known()):
                    pipe_read.refuse()
                _read.provider_stage = 'returned'
                _read.status_stage = 'pending'
                if r.returncode == 0:
                    _read.status_stage = 'returned'
                    _read.status_outcome = 'zero'
                    _read.decode_stage = 'pending'
                    plaintext = r.stdout.decode("utf-8")
                    _read.decode_stage = 'returned'
                    _read.outcome = 'decoded'
                    _read.helper_stage = 'returned'
                    return plaintext
                _read.status_stage = 'returned'
                _read.status_outcome = 'nonzero'
                _read.outcome = 'nonzero-policy-empty'
                _read.helper_stage = 'returned'
                return ''
            except BaseException as failure:
                # Observe raw before applying the exact original caught policy.
                _read.raw_failure = failure
                raise
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as failure:
            if issubclass(type(failure), MemoryError):
                raise
            _read.ignored_failure = failure
            _read.outcome = 'caught-policy-empty'
            _read.helper_stage = 'returned'
            return ''
    except BaseException as failure:
        _read.remember(failure)
        raise _read.failure from None


def _parse_entries(plaintext: str) -> list:
    """Parse vault plaintext into list of (host, key, value) tuples."""
    entries = []
    for line in plaintext.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|", 2)
        if len(parts) == 3:
            entries.append((parts[0], parts[1], parts[2]))
    return entries


def _serialize_entries(entries: list) -> str:
    """Serialize entries back to pipe-delimited format."""
    lines = ["# FREQ Vault — encrypted credential store"]
    for host, key, value in sorted(entries, key=lambda e: (e[0], e[1])):
        lines.append(f"{host}|{key}|{value}")
    return "\n".join(lines) + "\n"


def vault_init(cfg: FreqConfig) -> bool:
    """Initialize an empty vault."""
    from freq.core.read_source_epoch import _first

    with source_write():
        body_failure = None
        try:
            with _VAULT_LOCK:
                try:
                    key = _vault_key()
                    if not key:
                        return False

                    vault_dir = cfg.vault_dir
                    vault_path = cfg.vault_file

                    os.makedirs(vault_dir, mode=0o700, exist_ok=True)
                    if os.path.exists(vault_path):
                        return True
                    return _encrypt("# FREQ Vault — initialized\n", key, vault_path)
                except BaseException as error:
                    body_failure = error
                    raise
        except BaseException as error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(error), Exception)
                    or issubclass(type(error), MemoryError)):
                raise _first(body_failure, error) from None
            raise


def vault_update(cfg: FreqConfig, host: str, updates: dict[str, str | None]) -> bool:
    """Atomically set or delete several exact-namespace credentials."""
    if not isinstance(updates, dict) or not updates:
        return True
    from freq.core.read_source_epoch import _first

    with source_write():
        body_failure = None
        try:
            with _VAULT_LOCK:
                try:
                    key = _vault_key()
                    if not key:
                        return False
                    plaintext = _decrypt(key, cfg.vault_file)
                    entries = _parse_entries(plaintext)
                    changed_keys = set(updates)
                    entries = [(h, k, v) for h, k, v in entries if not (h == host and k in changed_keys)]
                    entries.extend(
                        (host, cred_key, value)
                        for cred_key, value in updates.items()
                        if value is not None
                    )
                    return _encrypt(_serialize_entries(entries), key, cfg.vault_file)
                except BaseException as error:
                    body_failure = error
                    raise
        except BaseException as error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(error), Exception)
                    or issubclass(type(error), MemoryError)):
                raise _first(body_failure, error) from None
            raise


def vault_set(cfg: FreqConfig, host: str, cred_key: str, value: str) -> bool:
    """Store a credential in the vault."""
    return vault_update(cfg, host, {cred_key: value})


def vault_get(cfg: FreqConfig, host: str, cred_key: str, *, _key_read=_VAULT_KEY_READ_OMITTED) -> str:
    """Retrieve a credential from the vault.

    Tries exact host match first, falls back to DEFAULT.
    """
    if _key_read is not _VAULT_KEY_READ_OMITTED:
        if type(_key_read) is not _VaultKeyReadDuty:
            raise _VaultKeyReadUnavailable()
        _key_read.enter_request(cfg, host, cred_key)
    failures = [None] * 2
    result = None

    def lookup():
        if _key_read is _VAULT_KEY_READ_OMITTED:
            key = _vault_key()
        else:
            key = _vault_key(_key_read=_key_read)
            _key_read.caller_returned = True
            if not _key_read.known():
                _key_read.refuse()
        if not key:
            return ""

        if _key_read is _VAULT_KEY_READ_OMITTED:
            plaintext = _decrypt(key, cfg.vault_file)
        else:
            decrypt_read = _key_read.lookup.decrypt_read
            if type(decrypt_read) is not _VaultDecryptReadDuty:
                raise _VaultDecryptReadUnavailable()
            try:
                decrypt_read.enter_request(_key_read, cfg)
                decrypt_read.path_stage = 'pending'
                vault_path = cfg.vault_file
                decrypt_read.candidate_path = vault_path
                decrypt_read.path_stage = 'returned'
                plaintext = _decrypt(key, vault_path, _read=decrypt_read)
                decrypt_read.caller_returned = True
                if not decrypt_read.known():
                    decrypt_read.refuse()
            except BaseException as failure:
                decrypt_read.remember(failure)
                raise decrypt_read.failure from None
        entries = _parse_entries(plaintext)

        # Exact match
        for h, k, v in entries:
            if h == host and k == cred_key:
                return v

        # Fallback to DEFAULT
        for h, k, v in entries:
            if h == "DEFAULT" and k == cred_key:
                return v

        return ""

    try:
        with _VAULT_LOCK:
            try:
                result = lookup()
            except BaseException as failure:
                failures[0] = failure
                # Original context still receives the same raw body error.
                raise
    except BaseException as failure:
        failures[1] = failure
    first = None
    for failure in failures:
        if failure is not None and (first is None
                or issubclass(type(first), Exception) and (
                    not issubclass(type(failure), Exception)
                    or not issubclass(type(first), MemoryError)
                    and issubclass(type(failure), MemoryError))):
            first = failure
    if first is not None:
        raise first from None
    return result


def vault_delete(cfg: FreqConfig, host: str, cred_key: str) -> bool:
    """Delete a credential from the vault."""
    from freq.core.read_source_epoch import _first

    with source_write():
        body_failure = None
        try:
            with _VAULT_LOCK:
                try:
                    key = _vault_key()
                    if not key:
                        return False

                    plaintext = _decrypt(key, cfg.vault_file)
                    entries = _parse_entries(plaintext)
                    new_entries = [(h, k, v) for h, k, v in entries if not (h == host and k == cred_key)]

                    if len(new_entries) == len(entries):
                        return False  # Nothing was deleted

                    return _encrypt(_serialize_entries(new_entries), key, cfg.vault_file)
                except BaseException as error:
                    body_failure = error
                    raise
        except BaseException as error:
            if body_failure is not None and (
                    not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)
                    or not issubclass(type(error), Exception)
                    or issubclass(type(error), MemoryError)):
                raise _first(body_failure, error) from None
            raise


def vault_list(cfg: FreqConfig) -> list:
    """List all vault entries (values masked for passwords)."""
    with _VAULT_LOCK:
        key = _vault_key()
        if not key:
            return []

        plaintext = _decrypt(key, cfg.vault_file)
        return _parse_entries(plaintext)


def cmd_vault(cfg: FreqConfig, pack, args) -> int:
    """Vault command dispatcher."""
    action = getattr(args, "action", None)

    if not action:
        fmt.error("Usage: freq vault <init|set|get|delete|list> [key] [value]")
        fmt.info("  freq vault init                    Initialize vault")
        fmt.info("  freq vault list                    List stored credentials")
        fmt.info("  freq vault set <key> <value>       Store a credential")
        fmt.info("  freq vault get <key>               Retrieve a credential")
        fmt.info("  freq vault delete <key>            Delete a credential")
        return 1

    if action == "init":
        return _vault_cmd_init(cfg)
    elif action == "list":
        return _vault_cmd_list(cfg)
    elif action == "set":
        return _vault_cmd_set(cfg, args)
    elif action == "get":
        return _vault_cmd_get(cfg, args)
    elif action == "delete":
        return _vault_cmd_delete(cfg, args)
    else:
        fmt.error(f"Unknown vault action: {action}")
        return 1


def _vault_cmd_init(cfg: FreqConfig) -> int:
    """Initialize the vault."""
    fmt.header("Vault Init")
    fmt.blank()

    if os.path.exists(cfg.vault_file):
        fmt.line(f"{fmt.C.YELLOW}Vault already exists at: {cfg.vault_file}{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}Use 'freq vault list' to see contents.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.step_start("Initializing encrypted vault")
    if vault_init(cfg):
        fmt.step_ok(f"Vault created at {cfg.vault_file}")
        logger.info("vault initialized", path=cfg.vault_file)
    else:
        fmt.step_fail("Failed to initialize vault")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.blank()
    fmt.footer()
    return 0


def _vault_cmd_list(cfg: FreqConfig) -> int:
    """List all vault entries."""
    fmt.header("Vault")
    fmt.blank()

    if not os.path.exists(cfg.vault_file):
        fmt.line(f"{fmt.C.YELLOW}Vault not initialized. Run: freq vault init{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    entries = vault_list(cfg)
    if not entries:
        fmt.line(f"{fmt.C.GRAY}Vault is empty.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.table_header(
        ("HOST", 16),
        ("KEY", 24),
        ("VALUE", 20),
    )

    for host, key, value in entries:
        # Mask passwords
        if "pass" in key.lower() or "secret" in key.lower() or "token" in key.lower():
            display_value = "********"
        else:
            display_value = value if len(value) <= 20 else value[:17] + "..."

        fmt.table_row(
            (host, 16),
            (f"{fmt.C.CYAN}{key}{fmt.C.RESET}", 24),
            (f"{fmt.C.DIM}{display_value}{fmt.C.RESET}", 20),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.GRAY}{len(entries)} credential(s) stored{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _vault_cmd_set(cfg: FreqConfig, args) -> int:
    """Store a credential."""
    cred_key = getattr(args, "key", None)
    value = getattr(args, "value", None)
    host = getattr(args, "host", None) or "DEFAULT"

    if not cred_key:
        fmt.error("Usage: freq vault set <key> <value> [--host <host>]")
        return 1

    # Prompt for value if not provided (for passwords)
    if not value:
        try:
            value = getpass.getpass(f"  Value for '{cred_key}': ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if not value:
            fmt.error("Value cannot be empty.")
            return 1

    # Ensure vault exists
    if not os.path.exists(cfg.vault_file):
        vault_init(cfg)

    if vault_set(cfg, host, cred_key, value):
        fmt.success(f"Stored: {host}|{cred_key}")
        logger.info(f"vault set: {host}|{cred_key}")
        return 0
    else:
        fmt.error("Failed to store credential.")
        return 1


def _vault_cmd_get(cfg: FreqConfig, args) -> int:
    """Retrieve a credential."""
    cred_key = getattr(args, "key", None)
    host = getattr(args, "host", None) or "DEFAULT"

    if not cred_key:
        fmt.error("Usage: freq vault get <key> [--host <host>]")
        return 1

    value = vault_get(cfg, host, cred_key)
    if value:
        print(value)
        return 0
    else:
        fmt.error(f"Not found: {host}|{cred_key}")
        return 1


def _vault_cmd_delete(cfg: FreqConfig, args) -> int:
    """Delete a credential."""
    cred_key = getattr(args, "key", None)
    host = getattr(args, "host", None) or "DEFAULT"

    if not cred_key:
        fmt.error("Usage: freq vault delete <key> [--host <host>]")
        return 1

    if vault_delete(cfg, host, cred_key):
        fmt.success(f"Deleted: {host}|{cred_key}")
        logger.info(f"vault delete: {host}|{cred_key}")
        return 0
    else:
        fmt.error(f"Not found: {host}|{cred_key}")
        return 1
