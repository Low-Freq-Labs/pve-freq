"""Docker Compose first-run contract."""

from pathlib import Path


def test_default_compose_uses_named_state_volumes():
    """Default compose must not bind-mount missing ./conf or ./data as root."""
    compose = Path("docker-compose.yml").read_text()

    assert "freq-conf:/opt/pve-freq/conf" in compose
    assert "freq-data:/opt/pve-freq/data" in compose
    assert "freq-etc:/etc/freq" in compose
    assert "./conf:/opt/pve-freq/conf" not in compose
    assert "./data:/opt/pve-freq/data" not in compose
    assert "\nvolumes:\n  freq-conf:\n  freq-data:\n  freq-etc:\n" in compose


def test_default_compose_allows_web_init_sudo_path():
    """Web init runs from a non-root dashboard and needs sudo inside Docker."""
    compose = Path("docker-compose.yml").read_text()

    assert "no-new-privileges:true" not in compose
    assert "read_only: true" not in compose


def test_docker_image_installs_sudo_for_web_init():
    """The non-root Docker dashboard must be able to launch sudo freq init."""
    dockerfile = Path("Dockerfile").read_text()

    assert " sudo " in dockerfile
    assert "/etc/sudoers.d/freq" in dockerfile
    assert "NOPASSWD:ALL" in dockerfile
