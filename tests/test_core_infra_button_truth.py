"""Core infrastructure dashboard actions must be safe and truthful."""

from freq.modules.serve import _redact_device_command_output


def test_device_command_output_redacts_wireguard_secrets():
    raw = """interface: tun_wg0
  public key: public-value
  private key: not-for-dashboard
  listening port: 51820
peer: abc
  preshared key: also-not-for-dashboard
"""
    out = _redact_device_command_output(raw)
    assert "not-for-dashboard" not in out
    assert "also-not-for-dashboard" not in out
    assert "private key: [redacted]" in out
    assert "preshared key: [redacted]" in out
    assert "public-value" in out
