"""Transactional OPNsense managed-identity lifecycle.

Remote transport is supplied by the caller.  This keeps the transaction owner
independent of HTTP/WebGUI bootstrap mode while making its ordering testable.
"""

from __future__ import annotations

import os

from freq.core.opnsense_enrollment import managed_state_payload, normalize_fingerprint


class OPNsenseLifecycleError(RuntimeError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _state(pin, *, user_count, key_count, remote, local):
    return managed_state_payload(
        managed=bool(remote and local),
        tls_sha256=pin,
        managed_user_count=user_count,
        managed_key_count=key_count,
        remote_present=remote,
        local_present=local,
    )


def enroll_managed_identity(
    session,
    managed_username: str,
    tls_sha256: str,
    *,
    load_local,
    store_local,
):
    """Create/reuse exactly one managed user and one verified API key pair."""
    pin = normalize_fingerprint(tls_sha256)
    local = load_local() or {}
    local_key = str(local.get("api_key") or "")
    local_secret = str(local.get("api_secret") or "")
    if local_key and local_secret and session.verify_credentials(local_key, local_secret):
        user_present = bool(session.managed_user_present(managed_username))
        keys = session.managed_keys(managed_username) if user_present else []
        if user_present and len(keys) == 1:
            return _state(pin, user_count=1, key_count=1, remote=True, local=True)

    created_user = False
    new_key_id = ""
    try:
        if not session.managed_user_present(managed_username):
            session.add_managed_user(managed_username)
            created_user = True

        for row in session.managed_keys(managed_username):
            key_id = str((row or {}).get("id") or "")
            if key_id:
                session.delete_managed_key(key_id)
        if session.managed_keys(managed_username):
            raise OPNsenseLifecycleError("enrollment", "stale managed API keys remain")

        generated = session.add_managed_key(managed_username) or {}
        new_key_id = str(generated.get("id") or "")
        api_key = str(generated.get("key") or "")
        api_secret = str(generated.get("secret") or "")
        if not new_key_id or not api_key or not api_secret:
            raise OPNsenseLifecycleError("enrollment", "managed API key response is incomplete")
        if not session.verify_credentials(api_key, api_secret):
            raise OPNsenseLifecycleError("enrollment", "managed API credentials failed probe")
        if not store_local(api_key, api_secret, pin):
            raise OPNsenseLifecycleError("enrollment", "managed credentials were not persisted")
        keys = session.managed_keys(managed_username)
        if len(keys) != 1:
            raise OPNsenseLifecycleError("enrollment", "managed API key count is not stable")
        return _state(pin, user_count=1, key_count=1, remote=True, local=True)
    except Exception as exc:
        rollback_ok = True
        if new_key_id:
            session.delete_managed_key(new_key_id)
            rollback_ok = not session.managed_keys(managed_username)
        if created_user:
            session.delete_managed_user(managed_username)
            rollback_ok = rollback_ok and not session.managed_user_present(managed_username)
        if not rollback_ok:
            raise OPNsenseLifecycleError(
                "rollback", "enrollment failed and remote rollback is incomplete"
            ) from exc
        if isinstance(exc, OPNsenseLifecycleError):
            raise
        raise OPNsenseLifecycleError("enrollment", "OPNsense enrollment failed") from exc


def remove_managed_identity(
    session,
    managed_username: str,
    tls_sha256: str,
    *,
    clear_local,
):
    """Verify remote absence before atomically clearing local credentials."""
    pin = normalize_fingerprint(tls_sha256)
    if session.managed_user_present(managed_username):
        for row in session.managed_keys(managed_username):
            key_id = str((row or {}).get("id") or "")
            if key_id:
                session.delete_managed_key(key_id)
        if session.managed_keys(managed_username):
            raise OPNsenseLifecycleError("cleanup_partial", "managed API keys remain")
        session.delete_managed_user(managed_username)
    if session.managed_user_present(managed_username):
        raise OPNsenseLifecycleError("cleanup_partial", "managed user remains")
    if not clear_local():
        raise OPNsenseLifecycleError("cleanup_partial", "local managed credentials remain")
    return _state(pin, user_count=0, key_count=0, remote=False, local=False)


def _toml_string(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def persist_non_secret_config(cfg, host: str, pin: str) -> bool:
    """Atomically persist only the OPNsense host and bound leaf fingerprint."""
    from freq.core.read_source_epoch import source_write

    with source_write():
        pin = normalize_fingerprint(pin)
        path = os.path.join(cfg.conf_dir, "freq.toml")
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return False

        section_start = None
        section_end = len(lines)
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "[infrastructure]":
                section_start = index
                continue
            if section_start is not None and index > section_start and stripped.startswith("["):
                section_end = index
                break
        if section_start is None:
            if lines and lines[-1].strip():
                lines.append("\n")
            section_start = len(lines)
            lines.extend(["[infrastructure]\n"])
            section_end = len(lines)

        updates = {
            "opnsense_ip": _toml_string(host),
            "opnsense_tls_sha256": _toml_string(pin),
        }
        found = set()
        for index in range(section_start + 1, section_end):
            key = lines[index].split("=", 1)[0].strip() if "=" in lines[index] else ""
            if key in updates:
                lines[index] = f"{key} = {updates[key]}\n"
                found.add(key)
        missing = [f"{key} = {updates[key]}\n" for key in updates if key not in found]
        if missing:
            lines[section_end:section_end] = missing

        tmp = f"{path}.opnsense.tmp"
        try:
            old = os.stat(path)
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.writelines(lines)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, old.st_mode & 0o777)
            try:
                os.chown(tmp, old.st_uid, old.st_gid)
            except PermissionError:
                pass
            os.replace(tmp, path)
            directory_fd = os.open(os.path.dirname(path), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return True
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return False


def deploy_from_init(ip, ctx, auth_pass, auth_key, auth_user):
    """Init adapter. API/WebGUI bootstrap material is carried in ``ctx``."""
    if not isinstance(ctx, dict):
        return False
    cfg = ctx.get("cfg")
    raw = ctx.get("_active_opnsense_credentials")
    if cfg is None or not isinstance(raw, dict):
        return False
    mode = str(raw.get("bootstrap_mode") or "").strip().lower()
    bootstrap = {"bootstrap_mode": mode}
    if mode == "web":
        bootstrap.update(
            username=raw.get("username") or raw.get("user") or "",
            password=raw.get("password") or "",
        )
    elif mode == "api":
        bootstrap.update(
            api_key=raw.get("api_key") or "",
            api_secret=raw.get("api_secret") or "",
        )
    else:
        return False
    if raw.get("tls_sha256"):
        bootstrap["tls_sha256"] = raw["tls_sha256"]
    elif raw.get("trust_on_first_use") is True:
        bootstrap["trust_on_first_use"] = True
    else:
        return False
    try:
        from freq.api.opnsense import enroll_with_bootstrap

        state = enroll_with_bootstrap(cfg, ip, bootstrap)
        return bool(state.get("managed"))
    except Exception:
        return False


def remove_from_init(ip, svc_name, key_path):
    """Legacy remover cannot invent re-entry authority; fail closed."""
    return False, "OPNsense removal requires explicit WebGUI or API credential re-entry"
