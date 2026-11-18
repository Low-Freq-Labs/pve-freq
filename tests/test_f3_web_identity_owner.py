"""Failing-first Web owners for the E1 F3 portable identity contract."""

from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_HTML = ROOT / "freq" / "data" / "web" / "setup.html"
SETUP_JS = ROOT / "freq" / "data" / "web" / "js" / "setup.js"
BROWSER_SPEC = ROOT / "tests" / "e2e" / "zero-state-web-ux.spec.js"


class _SetupDocument(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = {}
        self.text = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "input" and values.get("id"):
            self.inputs[values["id"]] = values

    def handle_data(self, data):
        self.text.append(data)


def _setup_document():
    document = _SetupDocument()
    document.feed(SETUP_HTML.read_text(encoding="utf-8"))
    return document


class TestF3WebIdentityOwner:
    def test_setup_bootstrap_default_and_role_copy_are_portable(self):
        document = _setup_document()
        bootstrap = document.inputs["bootstrap-user"]
        copy = " ".join(" ".join(document.text).split()).casefold()

        assert bootstrap.get("value") == "root"
        assert "required" in bootstrap
        assert "existing ssh login" in copy
        assert "used only" in copy
        assert "created separately" in copy

    def test_service_account_control_owns_authoritative_equality_error(self):
        document = _setup_document()
        service = document.inputs["service-account"]
        copy = " ".join(" ".join(document.text).split()).casefold()

        assert service.get("value") == "freq-admin"
        assert service.get("data-api-field") == "service_account.username"
        assert "must differ from the bootstrap" in copy

    def test_setup_javascript_preserves_values_and_clears_rejected_secrets(self):
        source = SETUP_JS.read_text(encoding="utf-8")

        assert "bootstrap:{username:trim('bootstrap-user'),password:$('bootstrap-pass').value}" in source
        assert "service_account:{username:trim('service-account'),password:$('service-pass').value}" in source
        assert ".catch(function(error){$('service-pass').value='';$('service-pass2').value='';setError(error.message,error.field,error.details);}" in source

    def test_hermetic_chromium_owner_carries_the_f3_identity_challenge(self):
        source = BROWSER_SPEC.read_text(encoding="utf-8")

        required_fragments = (
            "inputValue()).toBe('root')",
            "fill('site-bootstrap')",
            "service_account_matches_bootstrap",
            "getAttribute('data-api-field')).toBe('service_account.username')",
            "await expect.soft(serviceAccount).toBeFocused()",
            "await expect.soft(page.locator('#service-pass')).toHaveValue('')",
            "expect(rejectedStatus.active_init_job_id).toBeFalsy()",
        )
        for fragment in required_fragments:
            assert fragment in source
