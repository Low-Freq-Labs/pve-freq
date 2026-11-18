"""Core infrastructure dashboard actions must be safe and truthful."""

from ast import FunctionDef, Import, ImportFrom, parse
from pathlib import Path

from freq.modules import serve
from freq.services import device_command


def test_device_command_output_redacts_wireguard_secrets():
    assert serve._redact_device_command_output is device_command.redact_device_command_output
    redact_device_command_output = device_command.redact_device_command_output

    repo_root = Path(__file__).parent.parent
    serve_defs = {
        node.name
        for node in parse((repo_root / "freq/modules/serve.py").read_text()).body
        if isinstance(node, FunctionDef)
    }
    service_tree = parse((repo_root / "freq/services/device_command.py").read_text())
    service_defs = {
        node.name
        for node in service_tree.body
        if isinstance(node, FunctionDef)
    }
    service_imports = []
    for node in service_tree.body:
        if isinstance(node, Import):
            service_imports.extend(imported.name for imported in node.names)
        elif isinstance(node, ImportFrom) and node.module:
            service_imports.append(node.module)
    assert "_redact_device_command_output" not in serve_defs
    assert "redact_device_command_output" in service_defs
    assert service_imports == ["re", "collections.abc", "dataclasses", "typing"]

    raw = """interface: tun_wg0
  public key: public-value
  private key: not-for-dashboard
  listening port: 51820
peer: abc
  preshared key: also-not-for-dashboard
"""
    expected = """interface: tun_wg0
  public key: public-value
  private key: [redacted]
  listening port: 51820
peer: abc
  preshared key: [redacted]
"""
    mixed_case = (
        "PRIVATE KEY:not-visible\n"
        "\tPreShared Key : also-hidden\n"
        "public key: visible\n"
        "private key without colon\n"
    )
    mixed_case_expected = (
        "PRIVATE KEY:[redacted]\n"
        "\tPreShared Key : [redacted]\n"
        "public key: visible\n"
        "private key without colon\n"
    )
    cases = (
        (raw, expected),
        (mixed_case, mixed_case_expected),
        (None, ""),
        (0, ""),
        (123, "123"),
    )

    for value, exact in cases:
        assert redact_device_command_output(value) == exact
