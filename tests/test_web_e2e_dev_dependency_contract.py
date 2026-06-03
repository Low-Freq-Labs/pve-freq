"""Dev-only browser test dependency contract.

The shipped dashboard remains zero-dependency client-side. Playwright is allowed
only as a development verification dependency so the operator UI can be clicked
and proven without adding runtime frontend dependencies.
"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_package_json_has_no_runtime_dependencies():
    package = json.loads((ROOT / "package.json").read_text())
    assert package.get("private") is True
    assert package.get("dependencies", {}) == {}


def test_playwright_is_the_only_dev_dependency():
    package = json.loads((ROOT / "package.json").read_text())
    assert set(package.get("devDependencies", {}).keys()) == {"@playwright/test"}


def test_e2e_docs_pin_zero_dependency_client_contract():
    docs = (ROOT / "docs" / "WEB-E2E-TESTING.md").read_text()
    assert "zero-dependency" in docs
    assert "development-only" in docs
    assert "@playwright/test" in docs
