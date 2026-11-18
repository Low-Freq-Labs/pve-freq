"""OPNsense REST API integration for FREQ.

Who:   OPNsense firewall management via its native REST API.
What:  Read/write endpoints for system status, services, firewall rules,
       DHCP reservations, DNS overrides, WireGuard peers, firmware, reboot.
Why:   Direct API integration — no SSH required. OPNsense exposes a full
       REST API with key+secret auth, unlike pfSense which needs SSH+PHP.
Where: Routes registered at /api/opnsense/*.
When:  Registered in the unified fail-closed route registry.
"""

import base64
import http.client
import json
import re
import ssl
from html.parser import HTMLParser
import urllib.parse

from freq.api.auth import check_session_role as _check_session_role
from freq.api.helpers import get_json_body, json_response, require_post
from freq.core import log as logger
from freq.core.config import load_config
from freq.core.opnsense_enrollment import (
    OPNsenseContractError,
    certificate_sha256,
    managed_state_payload,
    normalize_fingerprint,
    public_failure,
    validate_bootstrap,
)
from freq.core.opnsense_lifecycle import (
    OPNsenseLifecycleError,
    enroll_managed_identity,
    persist_non_secret_config,
    remove_managed_identity,
)
from freq.core.vault import vault_get, vault_update

# OPNsense uses UUID-v4 format for resource identifiers
_SAFE_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_CSRF_HEADER_TOKEN = re.compile(
    r"setRequestHeader\(\s*['\"]X-CSRFToken['\"]\s*,\s*['\"]([^'\"]+)['\"]"
)

# -- Helpers -----------------------------------------------------------------


def _failure(kind, *, details=None):
    status, payload = public_failure(kind, details=details)
    return {**payload, "status": status}


def _failure_message(failure) -> str:
    if isinstance(failure, dict):
        return str(failure.get("message") or "OPNsense request failed.")
    return "OPNsense request failed."


def _send_opn_failure(handler, failure):
    if not isinstance(failure, dict):
        failure = _failure("remote")
    status = int(failure.get("status") or 502)
    payload = {key: value for key, value in failure.items() if key != "status"}
    json_response(handler, payload, status)


def _target(cfg) -> tuple[str, int]:
    parsed = urllib.parse.urlsplit(f"https://{cfg.opnsense_ip}")
    if not parsed.hostname:
        raise ValueError("OPNsense host is invalid")
    return parsed.hostname, parsed.port or 443


def _unverified_context():
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _observed_tls_sha256(host, port=443, timeout=5):
    """Observe only the leaf certificate; no HTTP credential is sent."""
    connection = http.client.HTTPSConnection(
        host, port=port, timeout=timeout, context=_unverified_context()
    )
    try:
        connection.connect()
        return certificate_sha256(connection.sock.getpeercert(binary_form=True))
    finally:
        connection.close()


def _pinned_request(host, port, expected_pin, path, method, body, api_key, api_secret):
    """Verify the leaf on the same socket before sending Authorization."""
    connection = http.client.HTTPSConnection(
        host, port=port, timeout=15, context=_unverified_context()
    )
    try:
        connection.connect()
        observed = certificate_sha256(connection.sock.getpeercert(binary_form=True))
        if observed != expected_pin:
            return None, _failure(
                "pin_mismatch",
                details=[{"bound": expected_pin, "observed": observed}],
            )
        credentials = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        headers = {"Authorization": f"Basic {credentials}", "Accept": "application/json"}
        encoded = None
        if body is not None:
            encoded = json.dumps(body, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        connection.request(method, f"/api/{path.lstrip('/')}", body=encoded, headers=headers)
        response = connection.getresponse()
        raw = response.read(1024 * 1024)
        content_type = str(response.getheader("Content-Type") or "").lower()
        if response.status in {401, 403} or 300 <= response.status < 400 or "text/html" in content_type:
            return None, _failure("auth")
        if response.status < 200 or response.status >= 300:
            return None, _failure(
                "remote", details=[{"http_status": int(response.status)}]
            )
        if not raw:
            return {}, None
        try:
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, _failure("remote", details=[{"reason": "invalid_json"}])
        if not isinstance(parsed, (dict, list)):
            return None, _failure("remote", details=[{"reason": "invalid_json_shape"}])
        return parsed, None
    finally:
        connection.close()


class _LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = {}

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "input":
            return
        row = {str(key).lower(): value for key, value in attrs}
        if str(row.get("type") or "").lower() == "hidden" and row.get("name"):
            self.hidden[str(row["name"])] = str(row.get("value") or "")


def _response_cookies(response) -> str:
    values = []
    for key, value in response.getheaders():
        if key.lower() == "set-cookie":
            pair = str(value).split(";", 1)[0].strip()
            if pair:
                values.append(pair)
    return "; ".join(values)


class _BootstrapSession:
    """One pinned, ephemeral OPNsense bootstrap transaction."""

    def __init__(self, host, pin, bootstrap):
        parsed = urllib.parse.urlsplit(f"https://{host}")
        if not parsed.hostname:
            raise OPNsenseLifecycleError("remote", "invalid OPNsense host")
        self.host = parsed.hostname
        self.port = parsed.port or 443
        self.pin = normalize_fingerprint(pin)
        self.bootstrap = validate_bootstrap(bootstrap)
        self.connection = None
        self.cookie = ""
        self.csrf_name = ""
        self.csrf_value = ""
        self._user_row = None

    def _connect(self):
        connection = http.client.HTTPSConnection(
            self.host, port=self.port, timeout=15, context=_unverified_context()
        )
        connection.connect()
        observed = certificate_sha256(connection.sock.getpeercert(binary_form=True))
        if observed != self.pin:
            connection.close()
            raise OPNsenseLifecycleError("pin_mismatch", "OPNsense TLS pin changed")
        return connection

    def open(self):
        if self.bootstrap["bootstrap_mode"] == "web":
            self.connection = self._connect()
            self.connection.request("GET", "/")
            response = self.connection.getresponse()
            raw = response.read(1024 * 1024)
            if response.status < 200 or response.status >= 400:
                raise OPNsenseLifecycleError("auth", "OPNsense login page unavailable")
            parser = _LoginForm()
            parser.feed(raw.decode("utf-8", "ignore"))
            hidden = dict(parser.hidden)
            self.csrf_name = next(iter(hidden), "")
            self.csrf_value = hidden.get(self.csrf_name, "")
            form = {
                **hidden,
                "usernamefld": self.bootstrap["username"],
                "passwordfld": self.bootstrap["password"],
                "login": "1",
            }
            encoded = urllib.parse.urlencode(form).encode()
            self.connection.request(
                "POST",
                "/",
                body=encoded,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cookie": _response_cookies(response),
                },
            )
            login = self.connection.getresponse()
            body = login.read(1024 * 1024)
            self.cookie = _response_cookies(login)
            if (
                login.status < 200
                or login.status >= 400
                or b"usernamefld" in body.lower()
                or not self.cookie
            ):
                raise OPNsenseLifecycleError("auth", "OPNsense WebGUI authentication failed")
            if self.connection.sock is None:
                self.connection = self._connect()
            self.connection.request(
                "GET",
                "/ui/core/dashboard",
                headers={"Cookie": self.cookie, "Accept": "text/html"},
            )
            dashboard = self.connection.getresponse()
            dashboard_body = dashboard.read(1024 * 1024)
            if dashboard.status < 200 or dashboard.status >= 300:
                raise OPNsenseLifecycleError(
                    "auth", "OPNsense authenticated dashboard unavailable"
                )
            match = _CSRF_HEADER_TOKEN.search(
                dashboard_body.decode("utf-8", "ignore")
            )
            if not match:
                raise OPNsenseLifecycleError(
                    "auth", "OPNsense WebGUI CSRF token unavailable"
                )
            self.csrf_value = match.group(1)
        return self

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _api(self, path, method="POST", body=None, *, pair=None):
        connection = self.connection if self.bootstrap["bootstrap_mode"] == "web" and pair is None else self._connect()
        close_after = connection is not self.connection
        try:
            if connection.sock is None:
                raise OPNsenseLifecycleError("remote", "pinned OPNsense session closed")
            observed = certificate_sha256(connection.sock.getpeercert(binary_form=True))
            if observed != self.pin:
                raise OPNsenseLifecycleError("pin_mismatch", "OPNsense TLS pin changed")
            headers = {"Accept": "application/json"}
            if pair is not None:
                key, secret = pair
                token = base64.b64encode(f"{key}:{secret}".encode()).decode()
                headers["Authorization"] = f"Basic {token}"
            elif self.bootstrap["bootstrap_mode"] == "api":
                token = base64.b64encode(
                    f"{self.bootstrap['api_key']}:{self.bootstrap['api_secret']}".encode()
                ).decode()
                headers["Authorization"] = f"Basic {token}"
            else:
                headers["Cookie"] = self.cookie
                if self.csrf_value:
                    headers["X-CSRFToken"] = self.csrf_value
            encoded = None
            if body is not None:
                encoded = json.dumps(body, separators=(",", ":")).encode()
                headers["Content-Type"] = "application/json"
            connection.request(method, f"/api/{path.lstrip('/')}", body=encoded, headers=headers)
            response = connection.getresponse()
            raw = response.read(1024 * 1024)
            content_type = str(response.getheader("Content-Type") or "").lower()
            if response.status in {401, 403} or 300 <= response.status < 400 or "text/html" in content_type:
                raise OPNsenseLifecycleError("auth", "OPNsense authentication failed")
            if response.status < 200 or response.status >= 300:
                raise OPNsenseLifecycleError("remote", f"OPNsense HTTP {response.status}")
            if not raw:
                return {}
            try:
                result = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise OPNsenseLifecycleError("remote", "OPNsense returned invalid JSON") from exc
            if not isinstance(result, (dict, list)):
                raise OPNsenseLifecycleError("remote", "OPNsense returned invalid JSON shape")
            return result
        finally:
            if close_after:
                connection.close()

    @staticmethod
    def _rows(data):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("rows", "items", "users", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    def _find_user(self, username):
        rows = self._rows(self._api("auth/user/search", body={}))
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("username") or row.get("user") or "")
            if name == username:
                self._user_row = row
                return row
        self._user_row = None
        return None

    def verify_credentials(self, key, secret):
        try:
            self._api("core/system/status", method="GET", pair=(key, secret))
            return True
        except OPNsenseLifecycleError:
            return False

    def managed_user_present(self, username):
        return self._find_user(username) is not None

    def add_managed_user(self, username):
        self._api(
            "auth/user/add",
            body={
                "user": {
                    "name": username,
                    "shell": "/sbin/nologin",
                    "authorizedkeys": "",
                    "priv": "page-all",
                }
            },
        )
        if not self.managed_user_present(username):
            raise OPNsenseLifecycleError("enrollment", "managed user was not created")

    def managed_keys(self, username):
        rows = self._rows(self._api("auth/user/search_api_key", method="GET"))
        result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            owner = str(row.get("username") or row.get("user") or row.get("name") or "")
            if owner != username:
                continue
            key_id = str(row.get("id") or row.get("uuid") or row.get("key_id") or "")
            if key_id:
                result.append({"id": key_id})
        return result

    def delete_managed_key(self, key_id):
        encoded = urllib.parse.quote(str(key_id), safe="")
        self._api(f"auth/user/del_api_key/{encoded}", body={})

    def add_managed_key(self, username):
        data = self._api(f"auth/user/add_api_key/{urllib.parse.quote(username, safe='')}", body={})
        row = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
        row = row if isinstance(row, dict) else {}
        api_key = str(row.get("key") or row.get("api_key") or "")
        key_id = str(row.get("id") or row.get("uuid") or row.get("key_id") or "")
        if api_key and not key_id:
            # OPNsense Auth/Api/UserController returns the key and one-time
            # secret from add_api_key.  Its delete endpoint takes the search
            # inventory's base64(key) identifier.
            key_id = base64.b64encode(api_key.encode("utf-8")).decode("ascii")
        return {
            "id": key_id,
            "key": api_key,
            "secret": str(row.get("secret") or row.get("api_secret") or ""),
        }

    def delete_managed_user(self, username):
        row = self._find_user(username) or {}
        uuid = str(row.get("uuid") or row.get("id") or "")
        if uuid:
            self._api(f"auth/user/del/{urllib.parse.quote(uuid, safe='')}", body={})


def _opn_request(cfg, path, method="GET", body=None):
    """Make a request to the OPNsense REST API.

    Builds the URL from cfg.opnsense_ip, authenticates with API key+secret
    from the FREQ vault, and returns parsed JSON.

    Args:
        cfg:    FreqConfig instance with opnsense_ip set.
        path:   API path (e.g. "core/system/status"). No leading slash.
        method: HTTP method — GET or POST.
        body:   Optional dict to send as JSON body (POST only).

    Returns:
        (data_dict, None) on success.
        (None, error_string) on failure.
    """
    try:
        host, port = _target(cfg)
        expected = normalize_fingerprint(getattr(cfg, "opnsense_tls_sha256", ""))
    except (ValueError, TypeError):
        return None, _failure("tls_untrusted")
    try:
        observed = _observed_tls_sha256(host, port=port)
    except (OSError, ssl.SSLError, http.client.HTTPException, ValueError):
        return None, _failure("remote", details=[{"reason": "tls_observation_failed"}])
    if observed != expected:
        return None, _failure(
            "pin_mismatch", details=[{"bound": expected, "observed": observed}]
        )

    api_key = vault_get(cfg, "opnsense", "api_key")
    api_secret = vault_get(cfg, "opnsense", "api_secret")
    if not api_key or not api_secret:
        return None, _failure("auth")
    try:
        return _pinned_request(host, port, expected, path, method, body, api_key, api_secret)
    except (OSError, ssl.SSLError, http.client.HTTPException, ValueError):
        logger.warn("api_opnsense: pinned request failed", endpoint=path)
        return None, _failure("remote")


def _require_opnsense_admin(handler):
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return None
    return load_config()


def _managed_username(cfg) -> str:
    return str(getattr(cfg, "ssh_service_account", "") or "freq-admin")


def _local_pair(cfg) -> dict:
    return {
        "api_key": vault_get(cfg, "opnsense", "api_key"),
        "api_secret": vault_get(cfg, "opnsense", "api_secret"),
    }


def _store_local_pair(cfg, host, api_key, api_secret, pin) -> bool:
    old = _local_pair(cfg)
    if not vault_update(
        cfg, "opnsense", {"api_key": api_key, "api_secret": api_secret}
    ):
        return False
    stored = _local_pair(cfg)
    if stored != {"api_key": api_key, "api_secret": api_secret}:
        vault_update(
            cfg,
            "opnsense",
            {
                "api_key": old.get("api_key") or None,
                "api_secret": old.get("api_secret") or None,
            },
        )
        return False
    if not persist_non_secret_config(cfg, host, pin):
        vault_update(
            cfg,
            "opnsense",
            {
                "api_key": old.get("api_key") or None,
                "api_secret": old.get("api_secret") or None,
            },
        )
        return False
    cfg.opnsense_ip = host
    cfg.opnsense_tls_sha256 = pin
    return True


def _clear_local_pair(cfg) -> bool:
    if not vault_update(cfg, "opnsense", {"api_key": None, "api_secret": None}):
        return False
    return not any(_local_pair(cfg).values())


def _bootstrap_body(body) -> tuple[str, dict]:
    if not isinstance(body, dict):
        raise OPNsenseContractError(
            "opnsense_invalid_request", "JSON object required.", status=400
        )
    allowed = {
        "host", "bootstrap_mode", "username", "password", "api_key", "api_secret",
        "tls_sha256", "trust_on_first_use", "confirm_replace",
    }
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise OPNsenseContractError(
            "opnsense_unsupported_field", "Unsupported OPNsense field.", unknown[0]
        )
    host = str(body.get("host") or "").strip()
    if not host or len(host) > 255 or any(ch in host for ch in "/?#@"):
        raise OPNsenseContractError(
            "opnsense_host_invalid", "OPNsense host is invalid.", "host"
        )
    bootstrap = {key: value for key, value in body.items() if key not in {"host", "confirm_replace"}}
    return host, validate_bootstrap(bootstrap)


def _require_bound_removal_target(cfg, host: str) -> None:
    """Prevent one device's re-entry credentials from clearing another's state."""
    try:
        bound_host, bound_port = _target(cfg)
        candidate = urllib.parse.urlsplit(f"https://{host}")
        candidate_host = candidate.hostname
        candidate_port = candidate.port or 443
    except (TypeError, ValueError) as exc:
        raise OPNsenseContractError(
            "opnsense_remove_target_mismatch",
            "Removal target does not match the managed OPNsense device.",
            "host",
            409,
        ) from exc
    if not candidate_host or (candidate_host.lower(), candidate_port) != (
        bound_host.lower(),
        bound_port,
    ):
        raise OPNsenseContractError(
            "opnsense_remove_target_mismatch",
            "Removal target does not match the managed OPNsense device.",
            "host",
            409,
        )


def _observed_and_bound_pin(host, bootstrap) -> str:
    parsed = urllib.parse.urlsplit(f"https://{host}")
    if not parsed.hostname:
        raise OPNsenseLifecycleError("remote", "invalid OPNsense host")
    try:
        observed = _observed_tls_sha256(parsed.hostname, port=parsed.port or 443)
    except (OSError, ssl.SSLError, http.client.HTTPException, ValueError) as exc:
        raise OPNsenseLifecycleError("remote", "certificate observation failed") from exc
    supplied = bootstrap.get("tls_sha256")
    if supplied and normalize_fingerprint(supplied) != observed:
        raise OPNsenseLifecycleError("pin_mismatch", "supplied TLS fingerprint differs")
    return observed


def _send_contract_failure(handler, exc):
    payload = {
        "ok": False,
        "code": exc.code,
        "message": str(exc),
        "field": exc.field,
        "details": list(exc.details),
    }
    json_response(handler, payload, exc.status)


def _send_lifecycle_failure(handler, exc):
    kind = exc.kind if exc.kind in {
        "pin_mismatch", "auth", "enrollment", "rollback", "retrust",
        "rerun", "cleanup_partial", "remote",
    } else "remote"
    status, payload = public_failure(kind)
    json_response(handler, payload, status)


def _current_managed_state(cfg):
    local = _local_pair(cfg)
    pin = str(getattr(cfg, "opnsense_tls_sha256", "") or "")
    host = str(getattr(cfg, "opnsense_ip", "") or "")
    if not host or not pin or not all(local.values()):
        return managed_state_payload(
            managed=False,
            tls_sha256=pin,
            managed_user_count=0,
            managed_key_count=0,
            remote_present=False,
            local_present=bool(all(local.values())),
        )
    bootstrap = {
        "bootstrap_mode": "api",
        "api_key": local["api_key"],
        "api_secret": local["api_secret"],
        "tls_sha256": pin,
    }
    session = _BootstrapSession(host, pin, bootstrap).open()
    try:
        username = _managed_username(cfg)
        present = session.managed_user_present(username)
        keys = session.managed_keys(username) if present else []
        return managed_state_payload(
            managed=present and len(keys) == 1,
            tls_sha256=pin,
            managed_user_count=1 if present else 0,
            managed_key_count=len(keys),
            remote_present=present,
            local_present=True,
        )
    finally:
        session.close()


def enroll_with_bootstrap(cfg, host: str, bootstrap: dict) -> dict:
    """Shared init/Settings owner for one ephemeral enrollment transaction."""
    bootstrap = validate_bootstrap(bootstrap)
    pin = _observed_and_bound_pin(host, bootstrap)
    session = _BootstrapSession(host, pin, bootstrap).open()
    try:
        return enroll_managed_identity(
            session,
            _managed_username(cfg),
            pin,
            load_local=lambda: _local_pair(cfg),
            store_local=lambda key, secret, exact_pin: _store_local_pair(
                cfg, host, key, secret, exact_pin
            ),
        )
    finally:
        session.close()


def handle_opnsense_enrollment(handler):
    """GET/POST managed state or explicit WebGUI/API enrollment after setup."""
    cfg = _require_opnsense_admin(handler)
    if cfg is None:
        return
    if handler.command == "GET":
        try:
            state = _current_managed_state(cfg)
        except OPNsenseLifecycleError as exc:
            _send_lifecycle_failure(handler, exc)
            return
        json_response(handler, {"ok": True, "opnsense": state})
        return
    if require_post(handler, "OPNsense enrollment"):
        return
    try:
        host, bootstrap = _bootstrap_body(get_json_body(handler))
        state = enroll_with_bootstrap(cfg, host, bootstrap)
    except OPNsenseContractError as exc:
        _send_contract_failure(handler, exc)
        return
    except OPNsenseLifecycleError as exc:
        _send_lifecycle_failure(handler, exc)
        return
    json_response(handler, {"ok": True, "opnsense": state})


def handle_opnsense_retrust(handler):
    """POST explicit post-init certificate replacement and auth probe."""
    if require_post(handler, "OPNsense re-trust"):
        return
    cfg = _require_opnsense_admin(handler)
    if cfg is None:
        return
    body = get_json_body(handler)
    try:
        host, bootstrap = _bootstrap_body(body)
        observed = _observed_and_bound_pin(host, bootstrap)
        bound = str(getattr(cfg, "opnsense_tls_sha256", "") or "")
        if observed != bound and body.get("confirm_replace") is not True:
            status, payload = public_failure(
                "retrust", details=[{"bound": bound, "observed": observed}]
            )
            json_response(handler, payload, status)
            return
        session = _BootstrapSession(host, observed, bootstrap).open()
        try:
            if bootstrap["bootstrap_mode"] == "api":
                session._api("core/system/status", method="GET")
            else:
                session._api("core/system/status", method="GET")
        finally:
            session.close()
        if not persist_non_secret_config(cfg, host, observed):
            raise OPNsenseLifecycleError("retrust", "new TLS pin was not persisted")
        cfg.opnsense_ip = host
        cfg.opnsense_tls_sha256 = observed
        state = _current_managed_state(cfg)
    except OPNsenseContractError as exc:
        _send_contract_failure(handler, exc)
        return
    except OPNsenseLifecycleError as exc:
        _send_lifecycle_failure(handler, exc)
        return
    json_response(handler, {"ok": True, "opnsense": state})


def handle_opnsense_remove(handler):
    """POST explicit credential re-entry; remote absence precedes local clear."""
    if require_post(handler, "OPNsense removal"):
        return
    cfg = _require_opnsense_admin(handler)
    if cfg is None:
        return
    try:
        host, bootstrap = _bootstrap_body(get_json_body(handler))
        _require_bound_removal_target(cfg, host)
        pin = _observed_and_bound_pin(host, bootstrap)
        bound_pin = normalize_fingerprint(
            str(getattr(cfg, "opnsense_tls_sha256", "") or "")
        )
        if pin != bound_pin:
            status, payload = public_failure(
                "retrust", details=[{"bound": bound_pin, "observed": pin}]
            )
            json_response(handler, payload, status)
            return
        session = _BootstrapSession(host, pin, bootstrap).open()
        try:
            state = remove_managed_identity(
                session,
                _managed_username(cfg),
                pin,
                clear_local=lambda: _clear_local_pair(cfg),
            )
        finally:
            session.close()
    except OPNsenseContractError as exc:
        _send_contract_failure(handler, exc)
        return
    except OPNsenseLifecycleError as exc:
        _send_lifecycle_failure(handler, exc)
        return
    json_response(handler, {"ok": True, "opnsense": state})


def _require_opnsense(handler):
    """Check admin role and OPNsense config. Returns (cfg, ok).

    Sends an error response and returns (None, False) if the caller
    lacks admin privileges or OPNsense is not configured.
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return None, False
    cfg = load_config()
    if not cfg.opnsense_ip:
        json_response(handler, {"error": "OPNsense not configured"}, 400)
        return None, False
    return cfg, True


def _require_opnsense_read(handler):
    """Load config and verify OPNsense is configured. No role check.

    Read endpoints are available to any authenticated session.

    Returns (cfg, ok).
    """
    cfg = load_config()
    if not cfg.opnsense_ip:
        json_response(handler, {"error": "OPNsense not configured"}, 400)
        return None, False
    return cfg, True


def _firewall_safe_apply(cfg, mutation_path, mutation_body=None):
    """Apply a firewall mutation using the OPNsense savepoint pattern.

    OPNsense firewall changes use a transactional model:
      1. Create a savepoint (gets a revision UUID)
      2. Apply the mutation (add/delete rule)
      3. Apply the revision (activates the change)
      4. Cancel the rollback timer (commits permanently)

    If any step fails, OPNsense auto-rolls back after the timeout.

    Args:
        cfg:             FreqConfig instance.
        mutation_path:   API path for the mutation (e.g. "firewall/filter/addRule").
        mutation_body:   Optional dict body for the mutation POST.

    Returns:
        (result_dict, None) on success.
        (None, error_string) on failure.
    """
    # Step 1: Create savepoint
    sp_data, sp_err = _opn_request(cfg, "firewall/filter/savepoint", method="POST")
    if sp_err:
        return None, sp_err

    revision = sp_data.get("revision")
    if not revision:
        return None, "Savepoint returned no revision"

    # Step 2: Execute the mutation
    mut_data, mut_err = _opn_request(cfg, mutation_path, method="POST", body=mutation_body)
    if mut_err:
        return None, mut_err

    # Step 3: Apply the revision
    apply_data, apply_err = _opn_request(
        cfg,
        f"firewall/filter/apply/{revision}",
        method="POST",
    )
    if apply_err:
        return None, apply_err

    # Step 4: Cancel the rollback timer — commit permanently
    cancel_data, cancel_err = _opn_request(
        cfg,
        f"firewall/filter/cancelRollback/{revision}",
        method="POST",
    )
    if cancel_err:
        # Non-fatal: the change is applied, rollback timer just stays active
        return mut_data, cancel_err

    return mut_data, None


# -- Read Operations (no role check) -----------------------------------------


def handle_opnsense_status(handler):
    """GET /api/opnsense/status -- OPNsense system status.

    Returns system information from the OPNsense API including
    uptime, CPU, memory, and version details.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    data, err = _opn_request(cfg, "core/system/status")
    if err:
        _send_opn_failure(handler, err)
        return

    json_response(handler, {"ok": True, "status": data})


def handle_opnsense_services(handler):
    """GET /api/opnsense/services -- list OPNsense services and status.

    Returns the full service list with running/stopped state.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    data, err = _opn_request(cfg, "core/service/search")
    if err:
        _send_opn_failure(handler, err)
        return

    json_response(handler, {"ok": True, "services": data})


def handle_opnsense_rules(handler):
    """GET /api/opnsense/rules -- list OPNsense firewall filter rules.

    Uses POST with empty body to the searchRule endpoint, which is
    OPNsense's standard pattern for paginated search results.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    # OPNsense searchRule is a POST endpoint (search with empty filter)
    data, err = _opn_request(cfg, "firewall/filter/searchRule", method="POST", body={})
    if err:
        _send_opn_failure(handler, err)
        return

    json_response(handler, {"ok": True, "rules": data})


def handle_opnsense_dhcp(handler):
    """GET /api/opnsense/dhcp -- list Kea DHCP reservations.

    Returns static DHCP reservations from the Kea DHCPv4 service.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    data, err = _opn_request(cfg, "kea/dhcpv4/searchReservation", method="POST", body={})
    if err:
        _send_opn_failure(handler, err)
        return

    json_response(handler, {"ok": True, "reservations": data})


def handle_opnsense_dns(handler):
    """GET /api/opnsense/dns -- list Unbound DNS host overrides.

    Returns DNS override entries from the Unbound resolver.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    data, err = _opn_request(cfg, "unbound/settings/searchHostOverride", method="POST", body={})
    if err:
        _send_opn_failure(handler, err)
        return

    json_response(handler, {"ok": True, "overrides": data})


def handle_opnsense_wireguard(handler):
    """GET /api/opnsense/wireguard -- list WireGuard peers.

    Returns all configured WireGuard client peers.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    data, err = _opn_request(cfg, "wireguard/client/searchClient", method="POST", body={})
    if err:
        _send_opn_failure(handler, err)
        return

    json_response(handler, {"ok": True, "peers": data})


def handle_opnsense_firmware(handler):
    """GET /api/opnsense/firmware -- check OPNsense firmware/update status.

    Returns current firmware version and available updates.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    data, err = _opn_request(cfg, "core/firmware/status", method="POST")
    if err:
        _send_opn_failure(handler, err)
        return

    json_response(handler, {"ok": True, "firmware": data})


# -- Write Operations (admin only) -------------------------------------------


def handle_opnsense_service_action(handler):
    """POST /api/opnsense/service/action -- start/stop/restart a service.

    Body: {"service": "unbound", "action": "restart"}

    Supported actions: start, stop, restart.
    Calls the OPNsense core service control API.
    """
    if require_post(handler, "OPNsense service"):
        return
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    service = body.get("service", "").strip()
    action = body.get("action", "").strip()

    if not service:
        json_response(handler, {"error": "service is required"}, 400)
        return
    if action not in ("start", "stop", "restart"):
        json_response(handler, {"error": "action must be start, stop, or restart"}, 400)
        return

    data, err = _opn_request(cfg, f"core/service/{action}/{service}", method="POST")
    if err:
        _send_opn_failure(handler, err)
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": action,
            "service": service,
            "result": data,
        },
    )


def handle_opnsense_rule_add(handler):
    """POST /api/opnsense/rules/add -- add a firewall filter rule.

    Body: {
        "action": "pass",
        "direction": "in",
        "interface": "lan",
        "protocol": "TCP",
        "source": "any",
        "destination": "10.0.0.0/24",
        "port": "443",
        "description": "Allow HTTPS"
    }

    Uses the savepoint safety pattern: savepoint -> addRule -> apply -> cancelRollback.
    If apply fails, OPNsense automatically rolls back to the savepoint.
    """
    if require_post(handler, "OPNsense rule add"):
        return
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)

    # Validate required fields
    rule_action = body.get("action", "").strip()
    if rule_action not in ("pass", "block", "reject"):
        json_response(handler, {"error": "action must be pass, block, or reject"}, 400)
        return

    direction = body.get("direction", "in").strip()
    if direction not in ("in", "out"):
        json_response(handler, {"error": "direction must be in or out"}, 400)
        return

    interface = body.get("interface", "").strip()
    if not interface:
        json_response(handler, {"error": "interface is required"}, 400)
        return

    protocol = body.get("protocol", "").strip()
    source = body.get("source", "any").strip()
    destination = body.get("destination", "any").strip()
    port = body.get("port", "").strip()
    description = body.get("description", "Added by FREQ").strip()

    # Build rule payload per OPNsense API schema
    rule_body = {
        "rule": {
            "action": rule_action,
            "direction": direction,
            "interface": interface,
            "source_net": source,
            "destination_net": destination,
            "description": description,
            "enabled": "1",
        }
    }

    if protocol:
        rule_body["rule"]["protocol"] = protocol

    if port:
        rule_body["rule"]["destination_port"] = port

    data, err = _firewall_safe_apply(cfg, "firewall/filter/addRule", rule_body)
    if err:
        _send_opn_failure(handler, err)
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "add",
            "result": data,
        },
    )


def handle_opnsense_rule_delete(handler):
    """POST /api/opnsense/rules/delete -- delete a firewall filter rule.

    Body: {"uuid": "abc-123-def"}

    Uses the savepoint safety pattern: savepoint -> delRule -> apply -> cancelRollback.
    """
    if require_post(handler, "Firewall rule delete"):
        return
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    uuid = body.get("uuid", "").strip()

    if not uuid or not _SAFE_UUID.match(uuid):
        json_response(handler, {"error": "Valid UUID required (format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)"}, 400)
        return

    data, err = _firewall_safe_apply(cfg, f"firewall/filter/delRule/{uuid}")
    if err:
        _send_opn_failure(handler, err)
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "delete",
            "uuid": uuid,
            "result": data,
        },
    )


def handle_opnsense_dhcp_add(handler):
    """POST /api/opnsense/dhcp/add -- add a Kea DHCP reservation.

    Body: {"mac": "AA:BB:CC:DD:EE:FF", "ip": "10.0.0.50", "hostname": "myhost"}

    Adds the reservation then reconfigures the Kea service to apply.
    """
    if require_post(handler, "OPNsense DHCP add"):
        return
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    mac = body.get("mac", "").strip()
    ip = body.get("ip", "").strip()
    hostname = body.get("hostname", "").strip()

    if not mac:
        json_response(handler, {"error": "mac is required"}, 400)
        return
    if not ip:
        json_response(handler, {"error": "ip is required"}, 400)
        return

    reservation_body = {
        "reservation": {
            "hw_address": mac,
            "ip_address": ip,
        }
    }
    if hostname:
        reservation_body["reservation"]["hostname"] = hostname

    # Add the reservation
    data, err = _opn_request(cfg, "kea/dhcpv4/addReservation", method="POST", body=reservation_body)
    if err:
        _send_opn_failure(handler, err)
        return

    # Reconfigure Kea to apply
    _, reconf_err = _opn_request(cfg, "kea/service/reconfigure", method="POST")
    if reconf_err:
        json_response(
            handler,
            {
                "ok": True,
                "action": "add",
                "warning": _failure_message(reconf_err),
                "result": data,
            },
        )
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "add",
            "mac": mac,
            "ip": ip,
            "hostname": hostname,
            "result": data,
        },
    )


def handle_opnsense_dhcp_delete(handler):
    """POST /api/opnsense/dhcp/delete -- delete a Kea DHCP reservation.

    Body: {"uuid": "abc-123"}

    Deletes the reservation then reconfigures the Kea service to apply.
    """
    if require_post(handler, "DHCP reservation delete"):
        return
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    uuid = body.get("uuid", "").strip()

    if not uuid or not _SAFE_UUID.match(uuid):
        json_response(handler, {"error": "Valid UUID required"}, 400)
        return

    # Delete the reservation
    data, err = _opn_request(cfg, f"kea/dhcpv4/delReservation/{uuid}", method="POST")
    if err:
        _send_opn_failure(handler, err)
        return

    # Reconfigure Kea to apply
    _, reconf_err = _opn_request(cfg, "kea/service/reconfigure", method="POST")
    if reconf_err:
        json_response(
            handler,
            {
                "ok": True,
                "action": "delete",
                "uuid": uuid,
                "warning": _failure_message(reconf_err),
                "result": data,
            },
        )
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "delete",
            "uuid": uuid,
            "result": data,
        },
    )


def handle_opnsense_dns_add(handler):
    """POST /api/opnsense/dns/add -- add an Unbound DNS host override.

    Body: {"host": "myapp", "domain": "lab.local", "ip": "10.0.0.50"}

    Adds the override then reconfigures Unbound to apply.
    """
    if require_post(handler, "OPNsense DNS add"):
        return
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    host = body.get("host", "").strip()
    domain = body.get("domain", "").strip()
    ip = body.get("ip", "").strip()

    if not host:
        json_response(handler, {"error": "host is required"}, 400)
        return
    if not domain:
        json_response(handler, {"error": "domain is required"}, 400)
        return
    if not ip:
        json_response(handler, {"error": "ip is required"}, 400)
        return

    override_body = {
        "host": {
            "hostname": host,
            "domain": domain,
            "server": ip,
            "enabled": "1",
        }
    }

    # Add the host override
    data, err = _opn_request(cfg, "unbound/settings/addHostOverride", method="POST", body=override_body)
    if err:
        _send_opn_failure(handler, err)
        return

    # Reconfigure Unbound to apply
    _, reconf_err = _opn_request(cfg, "unbound/service/reconfigure", method="POST")
    if reconf_err:
        json_response(
            handler,
            {
                "ok": True,
                "action": "add",
                "warning": _failure_message(reconf_err),
                "result": data,
            },
        )
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "add",
            "host": host,
            "domain": domain,
            "ip": ip,
            "result": data,
        },
    )


def handle_opnsense_dns_delete(handler):
    """POST /api/opnsense/dns/delete -- delete an Unbound DNS host override.

    Body: {"uuid": "abc-123"}

    Deletes the override then reconfigures Unbound to apply.
    """
    if require_post(handler, "DNS override delete"):
        return
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    uuid = body.get("uuid", "").strip()

    if not uuid or not _SAFE_UUID.match(uuid):
        json_response(handler, {"error": "Valid UUID required"}, 400)
        return

    # Delete the host override
    data, err = _opn_request(cfg, f"unbound/settings/delHostOverride/{uuid}", method="POST")
    if err:
        _send_opn_failure(handler, err)
        return

    # Reconfigure Unbound to apply
    _, reconf_err = _opn_request(cfg, "unbound/service/reconfigure", method="POST")
    if reconf_err:
        json_response(
            handler,
            {
                "ok": True,
                "action": "delete",
                "uuid": uuid,
                "warning": _failure_message(reconf_err),
                "result": data,
            },
        )
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "delete",
            "uuid": uuid,
            "result": data,
        },
    )


def handle_opnsense_wg_add(handler):
    """POST /api/opnsense/wireguard/add -- add a WireGuard peer.

    Body: {
        "name": "peer1",
        "pubkey": "...",
        "tunneladdress": "10.25.100.5/32",
        "serveruuid": "..."
    }

    Adds the peer then reconfigures WireGuard to apply.
    """
    if require_post(handler, "WireGuard peer add"):
        return
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    name = body.get("name", "").strip()
    pubkey = body.get("pubkey", "").strip()
    tunneladdress = body.get("tunneladdress", "").strip()
    serveruuid = body.get("serveruuid", "").strip()

    if not name:
        json_response(handler, {"error": "name is required"}, 400)
        return
    if not pubkey:
        json_response(handler, {"error": "pubkey is required"}, 400)
        return
    if not tunneladdress:
        json_response(handler, {"error": "tunneladdress is required"}, 400)
        return

    client_body = {
        "client": {
            "name": name,
            "pubkey": pubkey,
            "tunneladdress": tunneladdress,
            "enabled": "1",
        }
    }
    if serveruuid:
        client_body["client"]["servers"] = serveruuid

    # Add the WireGuard peer
    data, err = _opn_request(cfg, "wireguard/client/addClient", method="POST", body=client_body)
    if err:
        _send_opn_failure(handler, err)
        return

    # Reconfigure WireGuard to apply
    _, reconf_err = _opn_request(cfg, "wireguard/service/reconfigure", method="POST")
    if reconf_err:
        json_response(
            handler,
            {
                "ok": True,
                "action": "add",
                "warning": _failure_message(reconf_err),
                "result": data,
            },
        )
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "add",
            "name": name,
            "pubkey": pubkey,
            "tunneladdress": tunneladdress,
            "result": data,
        },
    )


def handle_opnsense_reboot(handler):
    """POST /api/opnsense/reboot -- reboot OPNsense.

    Body: {"confirm": true}

    Requires explicit confirmation to prevent accidental reboots.
    This will take down the firewall and all network services.
    """
    if require_post(handler, "OPNsense reboot"):
        return
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    if not body.get("confirm"):
        json_response(handler, {"error": "Must set confirm: true"}, 400)
        return

    data, err = _opn_request(cfg, "core/system/reboot", method="POST")
    if err:
        _send_opn_failure(handler, err)
        return

    json_response(handler, {"ok": True, "message": "Reboot command sent", "result": data})


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register OPNsense API routes."""
    # Post-init lifecycle remains reachable after zero-state routes close.
    routes["/api/opnsense/enrollment"] = handle_opnsense_enrollment
    routes["/api/opnsense/retrust"] = handle_opnsense_retrust
    routes["/api/opnsense/remove"] = handle_opnsense_remove

    # Read operations (no role check)
    routes["/api/opnsense/status"] = handle_opnsense_status
    routes["/api/opnsense/services"] = handle_opnsense_services
    routes["/api/opnsense/rules"] = handle_opnsense_rules
    routes["/api/opnsense/dhcp"] = handle_opnsense_dhcp
    routes["/api/opnsense/dns"] = handle_opnsense_dns
    routes["/api/opnsense/wireguard"] = handle_opnsense_wireguard
    routes["/api/opnsense/firmware"] = handle_opnsense_firmware

    # Write operations (admin only)
    routes["/api/opnsense/rules/add"] = handle_opnsense_rule_add
    routes["/api/opnsense/rules/delete"] = handle_opnsense_rule_delete
    routes["/api/opnsense/dhcp/add"] = handle_opnsense_dhcp_add
    routes["/api/opnsense/dhcp/delete"] = handle_opnsense_dhcp_delete
    routes["/api/opnsense/dns/add"] = handle_opnsense_dns_add
    routes["/api/opnsense/dns/delete"] = handle_opnsense_dns_delete
    routes["/api/opnsense/wireguard/add"] = handle_opnsense_wg_add
    routes["/api/opnsense/service/action"] = handle_opnsense_service_action
    routes["/api/opnsense/reboot"] = handle_opnsense_reboot
