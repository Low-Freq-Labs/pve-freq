from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "freq/data/web/app.html"
APP_JS = ROOT / "freq/data/web/js/app.js"
APP_CSS = ROOT / "freq/data/web/css/app.css"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def cert_section_html() -> str:
    src = read(APP_HTML)
    start = src.index('id="certs-view"')
    end = src.index("<!-- ============================================================", start + 1)
    return src[start:end]


def cert_js_slice() -> str:
    src = read(APP_JS)
    start = src.index("function _certText")
    end = src.index("function loadDnsPage", start)
    return src[start:end]


def test_ssl_manager_is_onboarding_not_config_editor():
    html = cert_section_html()
    js = cert_js_slice()

    assert "Onboarding Choices" in html
    assert "Preview / Apply" in html
    assert "Dashboard HTTPS" in js
    assert "App Trust" in js
    assert "Adopt Existing SSL" in js
    assert "Provision Direct Target Certs" in js

    forbidden = [
        "Config path",
        "config_block",
        "[cert_management]",
        "PREVIEW BOOTSTRAP",
        "APPLY BOOTSTRAP",
    ]
    for token in forbidden:
        assert token not in html
        assert token not in js


def test_ssl_manager_uses_current_onboarding_endpoints_and_actions():
    js = read(APP_JS)

    required = [
        "CERT_ONBOARDING:'/api/cert/lifecycle/onboarding'",
        "CERT_ADOPT_EXISTING:'/api/cert/lifecycle/adopt-existing'",
        "CERT_TRUSTED_PROXY:'/api/cert/lifecycle/trusted-proxy'",
        "certAdoptPreview:certAdoptPreview",
        "certTrustedProxyPreview:certTrustedProxyPreview",
        "certProvisionPreview:certProvisionPreview",
        'data-action="certAdoptPreview"',
        'data-action="certTrustedProxyPreview"',
        'data-action="certProvisionPreview"',
    ]
    for token in required:
        assert token in js


def test_ssl_manager_consumes_array_shaped_backend_contract():
    js = cert_js_slice()

    assert "Array.isArray(paths)" in js
    assert "paths[i].id===id" in js
    assert "Array.isArray(providers)" in js
    assert "apply_mutations" in js
    assert "p.status||p.support_level||'supported'" in js


def test_ssl_manager_separates_cert_truth_https_gap_and_app_trust():
    js = cert_js_slice()

    assert "served certificate truth" in js
    assert "dashboard_https" in js
    assert "trusted_proxy" in js
    assert "This is separate from certificate serving truth." in js
    assert "Targets" in js


def test_ssl_onboarding_layout_has_responsive_cards():
    css = read(APP_CSS)

    required = [
        ".cert-onboarding",
        ".cert-dashboard-state",
        ".cert-choice-grid",
        ".cert-provider-card",
        ".cert-defaults-card",
        "@media(max-width: 1200px)",
        "@media(max-width: 720px)",
    ]
    for token in required:
        assert token in css
