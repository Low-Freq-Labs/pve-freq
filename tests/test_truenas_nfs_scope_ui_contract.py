"""Public TrueNAS NFS form contract for explicit export scope selection."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
APP_JS = (ROOT / "freq/data/web/js/app.js").read_text(encoding="utf-8")


def _function_source(name: str) -> str:
    marker = f"function {name}("
    start = APP_JS.index(marker)
    brace = APP_JS.index("{", start)
    depth = 0
    quote = ""
    escaped = False
    for index in range(brace, len(APP_JS)):
        char = APP_JS[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return APP_JS[start : index + 1]
    raise AssertionError(f"unterminated JavaScript function: {name}")


def _assert_nfs_form_requires_visible_operator_selected_scope():
    form = _function_source("tnWriteShare")

    assert "options:['smb','nfs']" in form
    assert "NFS allowed clients (CIDR/IP list)" in form
    assert "only to the exact networks or host addresses entered here" in form
    assert "no scope is selected automatically" in form
    assert "body.networks=scopes.values" in form
    assert "if(v.type==='nfs')" in form
    assert "Enter at least one NFS client network or host address" in form
    assert "Invalid NFS CIDR/IP value" in form
    assert "for only these clients?" in form
    assert "when:{id:'type',value:'nfs'}" in form

    network_field = form[form.index("{id:'networks'") :].split(",when:", 1)[0]
    assert "value:" not in network_field
    assert "10.25." not in form
    assert "0.0.0.0/0" not in form
    assert "::/0" not in form


def _assert_shared_write_form_renders_multiline_scope_help():
    form = _function_source("_writeForm")
    assert "f.type==='textarea'" in form
    assert "rows" in form
    assert "f.help" in form
    assert "row.hidden=!visible" in form
    assert "source.addEventListener('change',sync)" in form


def _assert_client_parser_matches_cidr_and_ip_families():
    functions = "\n".join(
        _function_source(name)
        for name in (
            "_isIpv4Literal",
            "_ipv6GroupCount",
            "_isIpv6Literal",
            "_isNetworkScopeEntry",
            "_parseNetworkScopes",
        )
    )
    valid = [
        "192.0.2.1",
        "192.0.2.23/24",
        "0.0.0.0/32",
        "2001:db8::1",
        "2001:db8::1/64",
        "::1",
        "1:2:3:4:5:6:7:8",
        "::ffff:192.0.2.1",
    ]
    invalid = [
        "",
        "192.0.2.999",
        "192.0.2.01",
        "192.0.2.1/33",
        "192.0.2.1/-1",
        "2001:db8::1/129",
        "2001::db8::1",
        "gggg::1",
        "example.test",
    ]
    script = (
        functions
        + "\nconst valid="
        + json.dumps(valid)
        + ";\nconst invalid="
        + json.dumps(invalid)
        + ";\nprocess.stdout.write(JSON.stringify({"
        + "valid:valid.map(_isNetworkScopeEntry),"
        + "invalid:invalid.map(_isNetworkScopeEntry),"
        + "parsed:_parseNetworkScopes('192.0.2.0/24, 2001:db8::/64\\n192.0.2.9').values"
        + "}));"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(result.stdout)
    assert observed["valid"] == [True] * len(valid)
    assert observed["invalid"] == [False] * len(invalid)
    assert observed["parsed"] == ["192.0.2.0/24", "2001:db8::/64", "192.0.2.9"]


def assert_truenas_nfs_scope_ui_contract():
    """Run the explicit-scope UI contract inside its existing table owner."""
    _assert_nfs_form_requires_visible_operator_selected_scope()
    _assert_shared_write_form_renders_multiline_scope_help()
    _assert_client_parser_matches_cidr_and_ip_families()
