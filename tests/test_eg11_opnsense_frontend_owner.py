"""Failing-first source owners for the EG11 OPNsense browser consumers."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP_JS = ROOT / "freq/data/web/js/setup.js"
APP_HTML = ROOT / "freq/data/web/app.html"
APP_JS = ROOT / "freq/data/web/js/app.js"
BROWSER_OWNER = ROOT / "tests/e2e/eg11-opnsense-settings.spec.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_setup_owns_explicit_mode_tls_choice_and_secret_boundary() -> None:
    source = _read(SETUP_JS)

    for token in (
        "function opnsenseCredentialCard(",
        "bootstrap_mode",
        "trust_on_first_use",
        "tls_sha256",
        "item.secrets[field]=value",
        "field('api_key','API key'",
        "field('api_secret','API secret'",
        "field('password','WebGUI password'",
        "data-opn-mode-fields",
    ):
        assert token in source
    assert "item.trust_on_first_use=true" in source
    assert "localStorage" not in source


def test_settings_surface_owns_nonsecret_state_and_ephemeral_controls() -> None:
    html = _read(APP_HTML)
    source = _read(APP_JS)

    for node_id in (
        "opn-enrollment-state",
        "opn-enrollment-form",
        "opn-bootstrap-mode",
        "opn-tls-sha256",
        "opn-trust-on-first-use",
        "opn-retrust-compare",
        "opn-remove-confirm",
        "opn-bootstrap-password",
        "opn-bootstrap-api-key",
        "opn-bootstrap-api-secret",
    ):
        assert f'id="{node_id}"' in html
    assert 'id="opn-trust-on-first-use" type="checkbox" data-opn-field="trust_on_first_use"' in html

    for token in (
        "OPN_ENROLLMENT:'/api/opnsense/enrollment'",
        "OPN_RETRUST:'/api/opnsense/retrust'",
        "OPN_REMOVE:'/api/opnsense/remove'",
        "function loadOpnsenseEnrollment(",
        "function opnEnrollmentSubmit(",
        "function opnRetrustSubmit(",
        "function opnRemoveSubmit(",
        "function _opnClearSecrets(",
        "payload.confirm_replace=true",
        "managed_user_count",
        "managed_key_count",
        "remote_present",
        "local_present",
    ):
        assert token in source
    assert "loadSettingsPage(){loadOpnsenseEnrollment();" in source
    assert "localStorage.setItem('opnsense" not in source
    assert "sessionStorage.setItem('opnsense" not in source


def test_real_browser_owner_binds_mode_errors_retrust_and_remove() -> None:
    source = _read(BROWSER_OWNER)

    for token in (
        "mode-specific ephemeral enrollment",
        "field-focused closed failure",
        "explicit certificate replacement",
        "credential-gated removal",
        "opnsense-bootstrap-secret",
        "confirm_replace",
        "opnsense_credential_invalid",
        "setup card active API mode success",
        "setup card failure clears active secret",
        "downstream auth 401 preserves the PVE-FREQ session",
        "generic 401 on the OPNsense route still logs out",
    ):
        assert token in source


def test_opnsense_downstream_auth_classification_is_closed_by_exact_code() -> None:
    source = _read(APP_JS)

    assert "expectedCode!=='opnsense_auth_failed'" in source
    assert "data.code===expectedCode" in source
    assert "downstreamAuthCode:'opnsense_auth_failed'" in source
