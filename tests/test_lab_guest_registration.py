"""Synthetic local manifest/credential checks; no provider qualification."""
import dataclasses
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from freq.services import lab_guest_registration as registration


NOW = datetime.datetime(2026, 11, 13, 12, tzinfo=datetime.timezone.utc)


@pytest.fixture(scope="module")
def synthetic_ca(tmp_path_factory):
    root = tmp_path_factory.mktemp("lab-test-ca")
    try:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-days", "1", "-subj", "/CN=Fictional lab CA", "-keyout", str(root / "key"),
                        "-out", str(root / "ca.pem"), "-addext", "basicConstraints=critical,CA:TRUE"],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        yield (root / "ca.pem").read_bytes()
    finally:
        shutil.rmtree(root)


@pytest.fixture
def manifest(tmp_path, synthetic_ca):
    secret, ca = tmp_path / "token", tmp_path / "ca.pem"
    secret.write_bytes(b"fictional-token\n")
    secret.chmod(0o600)
    ca.write_bytes(synthetic_ca)
    ca.chmod(0o644)
    document = {
        "schema": "pve-freq-lab-guest-v1", "registration_id": "11111111222233334444555555555555",
        "qualified_at": "2026-11-13T00:00:00Z", "expires_at": "2026-11-14T00:00:00+00:00",
        "lab_only": True, "estate": "fictional-estate", "provider": "pve.example.invalid",
        "node": "fictional-pve", "guest_type": "qemu", "vmid": 5000, "name": "fictional-lab",
        "instance_uuid": "12345678-1234-5678-9123-123456789abc",
        "allowed_actions": ["status", "start", "shutdown"],
        "credentials": {"token_id": "reader@pve!lab", "token_secret_file": str(secret), "ca_file": str(ca)},
        "qualification_ref": "fictional-evidence-ref",
    }
    path = tmp_path / "lab-guest.json"

    def write():
        path.write_text(json.dumps(document), encoding="utf-8")
        path.chmod(0o600)

    write()
    return SimpleNamespace(cfg=SimpleNamespace(conf_dir=str(tmp_path)), document=document,
                           path=path, secret=secret, ca=ca, write=write)


def test_frozen_registration_hashes_complete_bytes_and_public_view_has_no_credentials(manifest):
    record = registration.load_registration(manifest.cfg, now=lambda: NOW)
    assert dataclasses.is_dataclass(record)
    assert record.revision == hashlib.sha256(manifest.path.read_bytes()).hexdigest()
    assert record.allowed_actions == ("status", "start", "shutdown")
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.vmid = 1
    public = record.public_view()
    assert public["lab_only"] is True
    assert public["vmid"] == 5000
    assert not {"credentials", "token_id", "token_secret_file", "ca_file", "qualification_ref"} & public.keys()
    assert "reader@pve!lab" not in json.dumps(public) + repr(record)
    assert str(manifest.secret) not in json.dumps(public) + repr(record)
    manifest.path.write_bytes(manifest.path.read_bytes() + b"\n")
    assert registration.load_registration(manifest.cfg, now=NOW.timestamp()).revision != record.revision


@pytest.mark.parametrize("field,value", [
    ("schema", "wrong"), ("lab_only", 1), ("guest_type", "lxc"), ("vmid", True),
    ("vmid", 0), ("vmid", 1.5), ("vmid", 2**53), ("name", "  "), ("name", "bad\nname"),
    ("node", "../other"), ("node", "pve:8006"), ("provider", "https://example.invalid"),
    ("provider", "example.invalid:8006"), ("provider", "::1%lo"),
    ("instance_uuid", "12345678123456789123123456789abc"),
    ("registration_id", "not-a-uuid"), ("qualified_at", "2026-11-13T00:00:00"),
    ("expires_at", "2026-11-14T00:00:00+01:00"), ("allowed_actions", ["start"]),
    ("allowed_actions", ["status", "stop"]), ("allowed_actions", ["status", "reset"]),
    ("allowed_actions", ["status", "status"]), ("allowed_actions", ["status", []]),
])
def test_invalid_manifest_values_refuse_without_exposing_input(manifest, field, value):
    manifest.document[field] = value
    manifest.write()
    with pytest.raises(registration.RegistrationError) as failure:
        registration.load_registration(manifest.cfg, now=NOW)
    assert failure.value.code == "invalid_registration"
    assert str(failure.value) == "invalid_registration"


@pytest.mark.parametrize("mutation", ["extra", "missing", "duplicate", "nonfinite"])
def test_schema_is_exact_and_duplicate_or_nonfinite_json_is_invalid(manifest, mutation):
    if mutation == "extra":
        manifest.document["extra"] = "private-input"
        manifest.write()
    elif mutation == "missing":
        del manifest.document["name"]
        manifest.write()
    elif mutation == "duplicate":
        manifest.path.write_text(manifest.path.read_text().replace('"vmid": 5000', '"vmid": 1, "vmid": 5000'))
    else:
        manifest.path.write_text(manifest.path.read_text().replace('"vmid": 5000', '"vmid": NaN'))
    with pytest.raises(registration.RegistrationError, match="^invalid_registration$"):
        registration.load_registration(manifest.cfg, now=NOW)


@pytest.mark.parametrize("instant", ["2026-11-12T12:00:00+00:00", "2026-11-14T00:00:00+00:00"])
def test_future_qualification_or_expired_manifest_is_stale(manifest, instant):
    with pytest.raises(registration.RegistrationError, match="^registration_expired$"):
        registration.load_registration(manifest.cfg, now=datetime.datetime.fromisoformat(instant))


@pytest.mark.parametrize("mode", [0o620, 0o602, 0o666])
def test_writable_manifest_is_rejected(manifest, mode):
    manifest.path.chmod(mode)
    with pytest.raises(registration.RegistrationError, match="^registration_unavailable$"):
        registration.load_registration(manifest.cfg, now=NOW)


@pytest.mark.parametrize("kind", ["missing", "symlink", "hardlink", "oversize", "directory", "wrong-owner"])
def test_manifest_file_must_be_bounded_owned_single_regular_file(manifest, monkeypatch, kind):
    if kind == "wrong-owner":
        monkeypatch.setattr(registration.os, "geteuid", lambda: os.getuid() + 1)
    elif kind == "oversize":
        manifest.path.write_bytes(b" " * (registration.MAX_MANIFEST + 1))
    elif kind == "hardlink":
        os.link(manifest.path, manifest.path.with_name("linked"))
    else:
        manifest.path.unlink()
        if kind == "symlink":
            manifest.path.symlink_to(manifest.secret)
        elif kind == "directory":
            manifest.path.mkdir()
    with pytest.raises(registration.RegistrationError, match="^registration_unavailable$"):
        registration.load_registration(manifest.cfg, now=NOW)


@pytest.mark.parametrize("kind", ["mode", "symlink", "hardlink", "relative", "noncanonical", "oversize", "nonascii", "newline", "missing"])
def test_secret_reference_requires_canonical_owned_600_bounded_ascii_file(manifest, kind):
    if kind == "mode":
        manifest.secret.chmod(0o640)
    elif kind == "hardlink":
        os.link(manifest.secret, manifest.secret.with_name("linked-token"))
    elif kind == "relative":
        manifest.document["credentials"]["token_secret_file"] = "token"
    elif kind == "noncanonical":
        manifest.document["credentials"]["token_secret_file"] = str(manifest.secret.parent) + "/./token"
    elif kind == "oversize":
        manifest.secret.write_bytes(b"x" * (registration.MAX_SECRET + 1))
    elif kind == "nonascii":
        manifest.secret.write_bytes(b"\xff")
    elif kind == "newline":
        manifest.secret.write_bytes(b"first\nsecond")
    else:
        manifest.secret.unlink()
        if kind == "symlink":
            manifest.secret.symlink_to(manifest.ca)
    manifest.write()
    with pytest.raises(registration.RegistrationError, match="^credentials_unavailable$"):
        registration.load_registration(manifest.cfg, now=NOW)


def test_symlink_parent_is_refused_even_for_regular_secret(manifest):
    alias = manifest.secret.parent / "alias"
    alias.symlink_to(manifest.secret.parent, target_is_directory=True)
    manifest.document["credentials"]["token_secret_file"] = str(alias / "token")
    manifest.write()
    with pytest.raises(registration.RegistrationError, match="^credentials_unavailable$"):
        registration.load_registration(manifest.cfg, now=NOW)


@pytest.mark.parametrize("kind", ["invalid", "oversize", "writable", "symlink"])
def test_ca_is_bounded_non_writable_real_certificate_file(manifest, kind):
    if kind == "invalid":
        manifest.ca.write_bytes(b"not-a-certificate")
    elif kind == "oversize":
        manifest.ca.write_bytes(b"x" * (registration.MAX_CA + 1))
    elif kind == "writable":
        manifest.ca.chmod(0o666)
    else:
        manifest.ca.unlink()
        manifest.ca.symlink_to(manifest.secret)
    with pytest.raises(registration.RegistrationError, match="^credentials_unavailable$"):
        registration.load_registration(manifest.cfg, now=NOW)


def test_memory_error_propagates(manifest, monkeypatch):
    def fail(*_args):
        raise MemoryError("synthetic")
    monkeypatch.setattr(registration.os, "read", fail)
    with pytest.raises(MemoryError):
        registration.load_registration(manifest.cfg, now=NOW)


def test_manifest_mutation_during_read_is_refused(manifest, monkeypatch):
    original = registration.os.read
    changed = [False]

    def changing_read(fd, size):
        chunk = original(fd, size)
        if not changed[0]:
            changed[0] = True
            manifest.path.write_bytes(manifest.path.read_bytes() + b" ")
        return chunk

    monkeypatch.setattr(registration.os, "read", changing_read)
    with pytest.raises(registration.RegistrationError, match="^registration_unavailable$"):
        registration.load_registration(manifest.cfg, now=NOW)


@pytest.mark.parametrize("change", ["unknown-field", "missing-field", "header-injection", "wrong-owner"])
def test_credential_schema_identity_and_owner_are_enforced(manifest, monkeypatch, change):
    credentials = manifest.document["credentials"]
    if change == "unknown-field":
        credentials["password"] = "fictional"
    elif change == "missing-field":
        del credentials["ca_file"]
    elif change == "header-injection":
        credentials["token_id"] = "reader@pve!lab\r\nInjected: value"
    else:
        original_read = registration._protected_read

        def wrong_owner(path, limit, **kwargs):
            if kwargs.get("secret"):
                actual = registration.os.geteuid()
                with monkeypatch.context() as context:
                    context.setattr(registration.os, "geteuid", lambda: actual + 1)
                    return original_read(path, limit, **kwargs)
            return original_read(path, limit, **kwargs)

        monkeypatch.setattr(registration, "_protected_read", wrong_owner)
    manifest.write()
    expected = "credentials_unavailable" if change == "wrong-owner" else "invalid_registration"
    with pytest.raises(registration.RegistrationError, match="^" + expected + "$"):
        registration.load_registration(manifest.cfg, now=NOW)
