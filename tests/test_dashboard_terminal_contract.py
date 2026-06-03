"""Dashboard terminal browser contract.

The terminal API correctly rejects GET for mutating session operations.
The browser client must therefore call those endpoints with POST too;
otherwise the first operator click fails even though backend enforcement
tests pass.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


def _endpoint_snippet(source: str, endpoint: str) -> str:
    index = source.find(endpoint)
    assert index != -1, f"{endpoint} is missing from app.js"
    return source[index:index + 800]


def test_terminal_dashboard_mutations_use_post():
    source = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()

    for endpoint in (
        "/api/terminal/open",
        "/api/terminal/resize",
        "/api/terminal/close",
    ):
        snippet = _endpoint_snippet(source, endpoint)
        assert "method:'POST'" in snippet or 'method:"POST"' in snippet


def test_known_dashboard_write_actions_use_post():
    source = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()

    for endpoint in (
        "/api/rules/create",
        "/api/rules/update",
        "/api/rules/delete",
        "/api/playbooks/step",
        "API.PLAYBOOKS_CREATE",
        "API.BACKUP_CREATE",
        "API.TREND_SNAPSHOT",
        "/api/vm/resize?vmid=",
        "/api/containers/action?host=docker-dev",
        "/api/containers/action?host='+encodeURIComponent(host)",
    ):
        snippet = _endpoint_snippet(source, endpoint)
        assert "method:'POST'" in snippet or 'method:\"POST\"' in snippet


def test_known_dashboard_read_views_do_not_use_post():
    source = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()

    for endpoint in (
        "var urls={show:API.SWITCH_SHOW",
        "var url=type==='health'?API.STACK_HEALTH:API.STACK_STATUS",
    ):
        snippet = _endpoint_snippet(source, endpoint)
        assert "method:'POST'" not in snippet and 'method:"POST"' not in snippet
