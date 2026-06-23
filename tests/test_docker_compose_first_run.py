"""Docker Compose first-run contract."""

from pathlib import Path


def test_default_compose_uses_named_state_volumes():
    """Default compose must not bind-mount missing ./conf or ./data as root."""
    compose = Path("docker-compose.yml").read_text()

    assert "freq-conf:/opt/pve-freq/conf" in compose
    assert "freq-data:/opt/pve-freq/data" in compose
    assert "./conf:/opt/pve-freq/conf" not in compose
    assert "./data:/opt/pve-freq/data" not in compose
    assert "\nvolumes:\n  freq-conf:\n  freq-data:\n" in compose
