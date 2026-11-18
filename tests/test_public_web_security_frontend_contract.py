"""Public web security frontend contract.

Backend commit a12dee9 moved the dashboard toward cookie-authenticated
browser sessions with CSRF and terminal WebSocket nonces. These tests pin the
browser side of that contract so old bearer-token and bare-WS assumptions do
not drift back into app.js.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
APP_JS = REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js"


def _js() -> str:
    return APP_JS.read_text()


def _function_body(source: str, name: str) -> str:
    marker = f"function {name}"
    start = source.find(marker)
    assert start != -1, f"{name} missing from app.js"
    end = source.find("\nfunction ", start + len(marker))
    return source[start:end if end != -1 else len(source)]


def test_auth_fetch_uses_cookie_csrf_not_browser_bearer():
    body = _function_body(_js(), "_authFetch")

    assert "_withCsrfHeader(opts.headers, opts.method || 'GET')" in body
    assert "credentials = 'same-origin'" in body
    assert "Authorization" not in body
    assert "Bearer" not in body


def test_login_and_session_verify_capture_csrf_token():
    source = _js()
    login = _function_body(source, "doLogin")
    check_session = _function_body(source, "_checkSession")

    assert "var _csrfToken='';" in source
    assert "function _rememberAuthResponse" in source
    assert "_rememberAuthResponse(d);" in login
    assert "_rememberAuthResponse(d);" in check_session
    assert "_browserSessionActive=true" in login
    assert "_browserSessionActive=true" in check_session


def test_bare_logout_and_password_rotation_still_send_csrf():
    source = _js()
    logout = _function_body(source, "doLogout")
    change_pw = _function_body(source, "_submitChangePassword")

    assert "_authFetch('/api/auth/logout" not in logout
    assert "fetch('/api/auth/logout'" in logout
    assert "_withCsrfHeader({},'POST')" in logout

    assert "_authFetch(API.AUTH_CHANGE_PW" not in change_pw
    assert "fetch(API.AUTH_CHANGE_PW" in change_pw
    assert "_withCsrfHeader({'Content-Type':'application/json'},'POST')" in change_pw


def test_ui_event_logger_uses_same_origin_csrf_when_available():
    body = _function_body(_js(), "_uiLog")

    assert "credentials:'same-origin'" in body
    assert "_withCsrfHeader({'Content-Type':'application/json'},'POST')" in body


def test_terminal_websocket_appends_backend_nonce():
    source = _js()
    terminal = _function_body(source, "openTerminal")

    assert "d.ws_nonce" in terminal
    assert "terminal nonce missing" in terminal
    assert "nonce='+encodeURIComponent(d.ws_nonce)" in terminal
    assert "terminal/ws?session='+d.session" not in terminal


def test_vault_credential_reveal_uses_same_origin_csrf_api_call():
    body = _function_body(_js(), "vaultCredentialReveal")

    assert "_authFetch(API.VAULT_CREDENTIAL_REVEAL" in body
    assert "method:'POST'" in body
    assert "'Content-Type':'application/json'" in body
    assert "JSON.stringify({id:id,scope:scope})" in body
