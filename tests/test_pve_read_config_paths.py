"""Configuration isolation checks using temporary files and fictional tokens.

No real credential store, vault crypto, SSH key discovery or provider is used.
"""
import builtins
import json
import os

import pytest

from freq.core import config
from freq.services import pve_transport


def defaults(tmp_path):
    cfg = config.FreqConfig(install_dir=str(tmp_path))
    config._resolve_paths(cfg)
    return cfg


def test_default_credentials_directory_unchanged(tmp_path):
    cfg = defaults(tmp_path)
    config._apply_toml(cfg, {})
    assert cfg.credentials_dir == "/etc/freq/credentials"
    assert cfg.pve_api_ca_file == ""


@pytest.mark.parametrize("suffix", ["credentials", "a/../credentials/", "credentials//."])
def test_absolute_credential_override_is_normalized(tmp_path, suffix):
    cfg = defaults(tmp_path)
    entered = str(tmp_path) + "/" + suffix
    config._apply_toml(cfg, {"paths": {"credentials_dir": entered}})
    assert cfg.credentials_dir == os.path.normpath(entered)
    assert cfg.vault_dir == str(tmp_path / "data" / "vault")


@pytest.mark.parametrize("entered", ["relative", "", "./credentials", "~/credentials",
                                      1, True, None, [], {}, "/tmp/\x00credentials",
                                      "/", "/tmp/..", "///", "//", "//a/.."])
def test_invalid_or_root_credential_override_rejected(tmp_path, entered):
    cfg = defaults(tmp_path)
    with pytest.raises(ValueError, match="absolute credential directory"):
        config._apply_toml(cfg, {"paths": {"credentials_dir": entered}})
    assert cfg.credentials_dir == "/etc/freq/credentials"


def test_ca_path_maps_to_verified_read_ca_field(tmp_path):
    cfg = defaults(tmp_path)
    path = str(tmp_path / "fictional-ca.pem")
    config._apply_toml(cfg, {"pve": {"api_ca_path": path, "api_verify_ssl": False}})
    assert cfg.pve_api_ca_file == path
    assert cfg.pve_api_verify_ssl is False


@pytest.fixture
def isolated_loader(monkeypatch):
    # Preserve actual TOML/config readers while preventing bootstrap side effects
    # and private home/key discovery unrelated to the path override.
    monkeypatch.setattr(config, "bootstrap_conf", lambda install_dir: False)
    monkeypatch.setattr(config, "_detect_ssh_key", lambda cfg: "")
    monkeypatch.setattr(config, "_detect_rsa_key", lambda cfg: "")
    monkeypatch.setattr(config, "validate_config", lambda cfg: [])
    for name in ("_config_cache", "_config_cache_ts", "_config_cache_install_dir",
                 "_config_cache_file_state"):
        monkeypatch.setattr(config, name, getattr(config, name))


def test_actual_loader_uses_override_before_explicit_token_read(
        tmp_path, monkeypatch, isolated_loader):
    root = tmp_path / "installation"
    (root / "conf").mkdir(parents=True)
    credentials = tmp_path / "isolated-credentials"
    credentials.mkdir()
    token = credentials / "fictional-token"
    token.write_text("fictional-read-token\n")
    ca = tmp_path / "fictional-ca.pem"
    (root / "conf" / "freq.toml").write_text(
        "[paths]\ncredentials_dir = " + json.dumps(str(credentials / ".")) +
        "\n[pve]\napi_token_id = 'fixture@pve!read'\napi_ca_path = " +
        json.dumps(str(ca)) + "\napi_token_secret_path = " + json.dumps(str(token)) + "\n"
    )
    monkeypatch.setenv("FREQ_DIR", str(root))
    original_apply, original_open = config._apply_toml, builtins.open
    applying, observed = [], []

    def apply(cfg, data):
        applying.append(cfg)
        return original_apply(cfg, data)

    def read(path, *args, **kwargs):
        if os.fspath(path) == str(token):
            assert applying[-1].credentials_dir == str(credentials)
            assert applying[-1].vault_dir == str(root / "data" / "vault")
            observed.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(config, "_apply_toml", apply)
    monkeypatch.setattr(builtins, "open", read)
    cfg = config.load_config(force=True)
    assert observed == [str(token)]
    assert cfg.install_dir == str(root)
    assert cfg.credentials_dir == str(credentials)
    assert cfg.pve_api_ca_file == str(ca)
    assert cfg.pve_api_token_secret == "fictional-read-token"


def test_actual_loader_then_runtime_fallback_uses_only_isolated_store(
        tmp_path, monkeypatch, isolated_loader):
    root = tmp_path / "installation"
    (root / "conf").mkdir(parents=True)
    credentials = tmp_path / "isolated-credentials"
    credentials.mkdir()
    (credentials / "pve-token-rw").write_text("fictional-fallback-token\n")
    (root / "conf" / "freq.toml").write_text(
        "[paths]\ncredentials_dir = " + json.dumps(str(credentials)) +
        "\n[pve]\napi_token_id = 'fixture@pve!read'\n"
    )
    monkeypatch.setenv("FREQ_DIR", str(root))
    cfg = config.load_config(force=True)
    original_open = builtins.open
    observed = []

    def only_fixture(path, *args, **kwargs):
        assert os.fspath(path) == str(credentials / "pve-token-rw")
        observed.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", only_fixture)
    assert pve_transport._runtime_pve_api_token_secret(cfg) == "fictional-fallback-token"
    assert observed == [str(credentials / "pve-token-rw")]
