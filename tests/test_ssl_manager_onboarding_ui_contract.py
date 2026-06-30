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
        "CERT_CLOUDFLARE_TOKEN:'/api/cert/lifecycle/cloudflare-token'",
        "certAdoptPreview:certAdoptPreview",
        "certTrustedProxyPreview:certTrustedProxyPreview",
        "certProvisionPreview:certProvisionPreview",
        "certCloudflareTokenValidate:certCloudflareTokenValidate",
        "certCloudflareTokenSave:certCloudflareTokenSave",
        'data-action="certAdoptPreview"',
        'data-action="certTrustedProxyPreview"',
        'data-action="certProvisionPreview"',
        'data-action="certCloudflareTokenValidate"',
        'data-action="certCloudflareTokenSave"',
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


def test_ssl_manager_uses_actionable_state_language():
    js = cert_js_slice()

    assert "Setup State" in js
    assert "SETUP NEEDED" in js
    assert "Setup gap" in js
    assert "adopted external" in js
    assert "externally managed" in js
    assert "external / existing-dns" in js
    assert "external existing" in js
    assert "renewal external" in js
    assert "No DNS preview yet" in js
    assert "No certificate inventory yet" in js
    assert "Base domain is needed before direct certificate provisioning." in js
    assert "No cert deploy targets configured or inferred yet" not in js
    assert "No DNS records planned yet" not in js
    assert "No certificate inventory data yet" not in js
    assert "Configured</span>" not in js


def test_ssl_manager_targets_render_as_compact_truth_table():
    js = cert_js_slice()
    css = read(APP_CSS)

    assert "cert-target-table-wrap" in js
    assert "cert-target-table" in js
    assert "<th>Scope</th>" in js
    assert "<th>Endpoint</th>" in js
    assert "proxy route" in js
    assert "direct mgmt" in js
    assert "legacy direct" in js
    assert "cert-target-card" not in js
    assert ".cert-target-table-wrap" in css
    assert "overflow: auto" in css


def test_ssl_manager_cloudflare_token_is_write_only_product_secret():
    js = read(APP_JS)
    css = read(APP_CSS)

    assert "cert-cloudflare-token" in js
    assert "Paste Cloudflare DNS token once" in js
    assert "never echo secret value" in js
    assert "Secret value was not returned by the API." in js
    assert "Save the Cloudflare token before provisioning" in js
    assert "CERT_CLOUDFLARE_TOKEN" in js
    assert "cloudflare_token_path:tokenPath" in js
    assert "cert-provision-token-path" not in js
    assert "Cloudflare token path" not in js
    assert ".cert-token-panel" in css
    assert ".cert-token-form" in css


def test_ssl_manager_is_mode_aware_after_configuration():
    js = cert_js_slice()
    css = read(APP_CSS)

    assert "setupReady?'SSL Operations':'SSL Setup'" in js
    assert "_certSetPanelTitle('cert-actions','Preview / Apply')" in js
    assert "_certSetPanelHidden('cert-actions',setupReady)" in js
    assert "setupReady?'DNS Truth':'DNS Plan'" in js
    assert "Change SSL setup / provisioning" in js
    assert "cert-advanced-setup" in js
    assert "Reconcile Targets" in js
    assert "Refresh Inventory" in js
    assert "Verify Coverage" in js
    assert "VERIFY COVERAGE" in js
    assert "RECONCILE TARGETS" in js
    assert "REFRESH INVENTORY" in js
    assert "Verify / reconcile target" in js
    assert "All SSL targets" in js
    assert "cert-ops-target" in js
    assert "cert-result-inline" in js
    assert "Latest SSL operation output" in js
    assert 'var setupChoices=\'<div class="cert-choice-grid">\';' in js
    assert "if(configured)" in js
    assert "h+=setupChoices+setupState;" in js
    assert "actions.innerHTML=setupReady?'':_renderCertActions" in js
    assert "_certSetPanelHidden('cert-result',setupReady)" in js
    assert ".cert-advanced-setup" in css
    assert ".cert-advanced-body" in css
    assert ".cert-ops-target" in css
    assert ".cert-inline-result" in css


def test_ssl_onboarding_layout_has_responsive_cards():
    css = read(APP_CSS)

    required = [
        ".cert-onboarding",
        ".cert-dashboard-state",
        ".cert-choice-grid",
        ".cert-empty-state",
        ".cert-provider-card",
        ".cert-defaults-card",
        "@media(max-width: 1200px)",
        "@media(max-width: 720px)",
    ]
    for token in required:
        assert token in css
