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
    assert "/home/freq:uid=1000,gid=1000,mode=755" in compose


def test_default_compose_mounts_web_init_input_contract():
    """Web Init must see operator-provided host setup input paths."""
    compose = Path("docker-compose.yml").read_text()

    assert "${FREQ_INIT_INPUTS_DIR:-/root/freq-init-inputs}:/freq-init-inputs:ro" in compose


def test_docker_image_installs_sudo_for_web_init():
    """The non-root Docker dashboard must be able to launch sudo freq init."""
    dockerfile = Path("Dockerfile").read_text()

    assert " sudo " in dockerfile
    assert "/etc/sudoers.d/freq" in dockerfile
    assert "NOPASSWD:ALL" in dockerfile


def test_docker_image_installs_ping_for_discovery():
    """Zero-state discovery should not warn just because slim image lacks ping."""
    dockerfile = Path("Dockerfile").read_text()

    assert "iputils-ping" in dockerfile


def test_docker_profile_is_explicitly_serve_only():
    """Docker owns lifecycle and must not imply host-systemd equivalence."""
    compose = Path("docker-compose.yml").read_text()
    dockerfile = Path("Dockerfile").read_text()
    readme = Path("README.md").read_text()

    assert "Runtime contract: Docker is intentionally serve-only" in compose
    assert "FREQ_DIR=/opt/pve-freq" in compose
    assert 'org.lowfreqlabs.freq.deployment-profile="serve-only"' in dockerfile
    assert "intentionally **serve-only**" in readme
    assert 'CMD ["serve"]' in dockerfile
