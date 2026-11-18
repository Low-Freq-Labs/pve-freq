"""Fail-closed contracts shared by OPNsense setup, runtime, and removal."""

from __future__ import annotations

import hashlib
import re


_TLS_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MODES = {
    "web": ("username", "password"),
    "api": ("api_key", "api_secret"),
}
_SECRET_FIELDS = {"password", "api_key", "api_secret"}
_ALLOWED_FIELDS = {
    "bootstrap_mode",
    "username",
    "password",
    "api_key",
    "api_secret",
    "tls_sha256",
    "trust_on_first_use",
}


class OPNsenseContractError(ValueError):
    """A bounded operator-correctable OPNsense contract failure."""

    def __init__(self, code: str, message: str, field: str = "", status: int = 422):
        super().__init__(message)
        self.code = code
        self.field = field
        self.status = status
        self.details: list[dict] = []


def certificate_sha256(certificate_der: bytes) -> str:
    """Return the canonical lowercase SHA-256 digest of one DER leaf cert."""
    if not isinstance(certificate_der, bytes) or not certificate_der:
        raise ValueError("a non-empty DER certificate is required")
    return hashlib.sha256(certificate_der).hexdigest()


def normalize_fingerprint(value: str) -> str:
    """Normalize a displayed SHA-256 pin while rejecting ambiguous text."""
    normalized = str(value or "").strip().lower().replace(":", "")
    if not _TLS_SHA256.fullmatch(normalized):
        raise OPNsenseContractError(
            "opnsense_tls_invalid",
            "TLS fingerprint must be exactly 32 SHA-256 bytes.",
            "tls_sha256",
        )
    return normalized


def _clean_secret(value, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 4096
        or "\x00" in value
        or "\n" in value
        or "\r" in value
    ):
        raise OPNsenseContractError(
            "opnsense_credential_invalid",
            "Credential value is missing or unsafe.",
            field,
        )
    return value


def validate_bootstrap(body: dict) -> dict:
    """Validate one ephemeral WebGUI or API bootstrap credential set.

    Bootstrap credentials are transaction inputs.  The returned mapping is
    intentionally not a durable managed-credential record.
    """
    if not isinstance(body, dict):
        raise OPNsenseContractError(
            "opnsense_invalid_request", "JSON object required.", status=400
        )
    unknown = sorted(set(body) - _ALLOWED_FIELDS)
    if unknown:
        raise OPNsenseContractError(
            "opnsense_unsupported_field",
            "Unsupported OPNsense bootstrap field.",
            unknown[0],
        )
    mode = str(body.get("bootstrap_mode") or "").strip().lower()
    if mode not in _MODES:
        raise OPNsenseContractError(
            "opnsense_bootstrap_mode_required",
            "bootstrap_mode must be web or api.",
            "bootstrap_mode",
        )

    required = set(_MODES[mode])
    forbidden = (_SECRET_FIELDS | {"username"}) - required
    for field in sorted(required):
        _clean_secret(body.get(field), field)
    for field in sorted(forbidden):
        if field in body:
            raise OPNsenseContractError(
                "opnsense_cross_mode_credential",
                "Credential field does not belong to the selected bootstrap mode.",
                field,
            )

    has_pin = bool(body.get("tls_sha256"))
    has_tofu = body.get("trust_on_first_use") is True
    if has_pin == has_tofu:
        raise OPNsenseContractError(
            "opnsense_tls_choice_required",
            "Provide one TLS fingerprint or explicitly confirm trust on first use.",
            "tls_sha256",
        )

    normalized = {"bootstrap_mode": mode}
    for field in _MODES[mode]:
        normalized[field] = _clean_secret(body.get(field), field)
    if has_pin:
        normalized["tls_sha256"] = normalize_fingerprint(body["tls_sha256"])
    else:
        normalized["trust_on_first_use"] = True
    return normalized


_FAILURES = {
    "tls_untrusted": (
        409,
        "opnsense_tls_untrusted",
        "OPNsense certificate requires explicit trust.",
        "tls_sha256",
    ),
    "pin_mismatch": (
        409,
        "opnsense_tls_pin_mismatch",
        "Observed OPNsense certificate does not match the bound fingerprint.",
        "tls_sha256",
    ),
    "auth": (401, "opnsense_auth_failed", "OPNsense authentication failed.", "credentials"),
    "enrollment": (
        502,
        "opnsense_enrollment_failed",
        "OPNsense enrollment did not complete.",
        "",
    ),
    "rollback": (
        502,
        "opnsense_enrollment_rollback_failed",
        "OPNsense enrollment failed and rollback is incomplete.",
        "",
    ),
    "retrust": (
        409,
        "opnsense_retrust_failed",
        "OPNsense certificate replacement was not accepted.",
        "tls_sha256",
    ),
    "rerun": (
        502,
        "opnsense_rerun_failed",
        "Managed OPNsense credentials could not be verified.",
        "",
    ),
    "cleanup_partial": (
        502,
        "opnsense_cleanup_partial",
        "OPNsense cleanup is incomplete.",
        "",
    ),
    "remote": (502, "opnsense_remote_failed", "OPNsense request failed.", ""),
}


def public_failure(kind: str, *, details: list[dict] | None = None) -> tuple[int, dict]:
    """Project one closed, stable, secret-free public failure envelope."""
    status, code, message, field = _FAILURES.get(kind, _FAILURES["remote"])
    return status, {
        "ok": False,
        "code": code,
        "message": message,
        "field": field,
        "details": list(details or [])[:20],
    }


def managed_state_payload(
    *,
    managed: bool,
    tls_sha256: str,
    managed_user_count: int,
    managed_key_count: int,
    remote_present: bool,
    local_present: bool,
    **_ignored,
) -> dict:
    """Return the entire non-secret enrollment/removal state surface."""
    pin = normalize_fingerprint(tls_sha256) if tls_sha256 else ""
    return {
        "managed": bool(managed),
        "tls_sha256": pin,
        "managed_user_count": max(0, int(managed_user_count)),
        "managed_key_count": max(0, int(managed_key_count)),
        "remote_present": bool(remote_present),
        "local_present": bool(local_present),
    }
