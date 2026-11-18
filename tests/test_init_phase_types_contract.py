"""Owner for the first typed init-orchestrator contract slice."""

import dataclasses
from types import MappingProxyType

import pytest

from freq.core.types import (
    INIT_PHASES,
    InitPhase2ResumeProvenance,
    PhaseIdentity,
    PhaseInput,
    PhaseResult,
    PhaseStatus,
    _init_cancellation_boundary,
    _InitCancellationBoundary,
    phase_catalog,
)


def test_phase_catalog_is_ordered_and_typed():
    assert phase_catalog() == INIT_PHASES
    assert [phase.number for phase in INIT_PHASES] == list(range(1, 14))
    assert all(isinstance(phase, PhaseIdentity) for phase in INIT_PHASES)
    assert phase_catalog(include_summary=False) == INIT_PHASES[:-1]
    assert _init_cancellation_boundary(INIT_PHASES[0]) is (
        _InitCancellationBoundary.POINT_OF_NO_RETURN
    )
    assert all(
        _init_cancellation_boundary(identity)
        is _InitCancellationBoundary.AFTER_POINT_OF_NO_RETURN
        for identity in INIT_PHASES[1:]
    )
    assert [
        _init_cancellation_boundary(identity)
        for identity in phase_catalog(include_summary=False)
    ] == [
        _init_cancellation_boundary(identity)
        for identity in phase_catalog()[:-1]
    ]
    assert [member.value for member in _InitCancellationBoundary] == [
        "point_of_no_return",
        "after_point_of_no_return",
    ]
    equal_but_foreign = PhaseIdentity(1, "prerequisites", "Prerequisites")
    assert equal_but_foreign == INIT_PHASES[0]
    assert equal_but_foreign is not INIT_PHASES[0]
    with pytest.raises(ValueError, match="canonical phase identity"):
        _init_cancellation_boundary(equal_but_foreign)
    for invalid in (None, "prerequisites", 1, object()):
        with pytest.raises(TypeError, match="requires PhaseIdentity"):
            _init_cancellation_boundary(invalid)


def test_phase_identity_is_immutable_and_validated():
    identity = PhaseIdentity(1, "prerequisites", "Prerequisites")
    with pytest.raises(dataclasses.FrozenInstanceError):
        identity.key = "changed"
    with pytest.raises(ValueError):
        PhaseIdentity(0, "bad", "Bad")
    with pytest.raises(ValueError):
        PhaseIdentity(1, "", "Bad")


def test_phase_input_freezes_context_without_aliasing():
    source = {"svc_name": "freq-admin", "device_creds": {"switch": {"user": "before"}}}
    value = PhaseInput(INIT_PHASES[0], source, dry_run=True)
    source["svc_name"] = "changed"
    source["device_creds"]["switch"]["user"] = "after"
    assert value.context["svc_name"] == "freq-admin"
    assert value.context["device_creds"]["switch"]["user"] == "before"
    assert value.dry_run is True
    with pytest.raises(TypeError):
        value.context["new"] = "value"


def test_phase_input_requires_typed_identity():
    with pytest.raises(TypeError):
        PhaseInput("prerequisites")


def test_phase_input_requires_top_level_mapping():
    for context in (None, [], set()):
        with pytest.raises(TypeError):
            PhaseInput(INIT_PHASES[0], context)


def test_phase_result_factories_are_typed_and_honest():
    identity = INIT_PHASES[11]
    success = PhaseResult.succeeded(identity, details={"passes": 2})
    failure = PhaseResult.failed(identity, "verification failed")
    skipped = PhaseResult.skipped(identity)
    assert success.status is PhaseStatus.SUCCEEDED
    assert failure.status is PhaseStatus.FAILED
    assert failure.error == "verification failed"
    assert skipped.status is PhaseStatus.SKIPPED


def test_failed_result_requires_error_and_success_cannot_have_one():
    identity = INIT_PHASES[0]
    with pytest.raises(ValueError):
        PhaseResult(identity, PhaseStatus.FAILED)
    with pytest.raises(ValueError):
        PhaseResult(identity, PhaseStatus.SUCCEEDED, error="unexpected")


def test_phase_result_requires_top_level_mapping_details():
    with pytest.raises(TypeError):
        PhaseResult(INIT_PHASES[0], PhaseStatus.SUCCEEDED, details=None)
    for details in (["value"], {"value"}):
        with pytest.raises(TypeError):
            PhaseResult.succeeded(INIT_PHASES[0], details=details)


def test_all_result_factories_reject_falsey_non_mapping_details():
    identity = INIT_PHASES[0]
    factories = (
        lambda details: PhaseResult.succeeded(identity, details=details),
        lambda details: PhaseResult.failed(identity, "failed", details=details),
        lambda details: PhaseResult.skipped(identity, details=details),
    )
    for factory in factories:
        for details in ([], set(), "", 0):
            with pytest.raises(TypeError):
                factory(details)


def test_phase_result_details_are_immutable_and_detached():
    details = {"count": 1, "rows": [1]}
    result = PhaseResult.succeeded(INIT_PHASES[0], details=details)
    details["count"] = 2
    details["rows"].append(2)
    assert result.details["count"] == 1
    assert result.details["rows"] == (1,)
    with pytest.raises(TypeError):
        result.details["count"] = 3


def test_failed_factory_rejects_absent_or_blank_errors_before_coercion():
    for error in (None, "", "   "):
        with pytest.raises(ValueError):
            PhaseResult.failed(INIT_PHASES[0], error)


def test_phase2_resume_provenance_is_exact_immutable_secret_free_and_validated():
    value = InitPhase2ResumeProvenance(
        config_fingerprint="a" * 64,
        bootstrap_user="root",
        bootstrap_auth="key",
    )
    assert dataclasses.asdict(value) == {
        "config_fingerprint": "a" * 64,
        "bootstrap_user": "root",
        "bootstrap_auth": "key",
        "mode": "headless",
        "version": 1,
    }
    password_auth = dataclasses.replace(value, bootstrap_auth="password")
    assert password_auth.bootstrap_auth == "password"
    alternate_identity = dataclasses.replace(
        value,
        config_fingerprint="0123456789abcdef" * 4,
        bootstrap_user="freq-bootstrap",
    )
    assert alternate_identity.config_fingerprint == "0123456789abcdef" * 4
    assert alternate_identity.bootstrap_user == "freq-bootstrap"
    payload = alternate_identity.to_payload()
    assert payload == {
        "schema": "pve-freq-init-phase2-provenance-v1",
        "config_fingerprint": "0123456789abcdef" * 4,
        "bootstrap_user": "freq-bootstrap",
        "bootstrap_auth": "key",
        "mode": "headless",
        "version": 1,
    }
    round_trip = InitPhase2ResumeProvenance.from_payload(payload)
    assert round_trip == alternate_identity
    assert round_trip is not alternate_identity
    mapping_round_trip = InitPhase2ResumeProvenance.from_payload(MappingProxyType(payload))
    assert mapping_round_trip == alternate_identity
    assert mapping_round_trip is not alternate_identity
    invalid_payloads = (
        None,
        {key: item for key, item in payload.items() if key != "version"},
        {**payload, "password": "must-not-exist"},
        {**payload, "unexpected_future_field": "must-not-exist"},
        {**payload, "schema": "wrong"},
        {**payload, "mode": "interactive"},
        {**payload, "config_fingerprint": "a" * 63},
    )
    for invalid_payload in invalid_payloads:
        with pytest.raises(ValueError):
            InitPhase2ResumeProvenance.from_payload(invalid_payload)
    payload["bootstrap_user"] = "changed-after-parse"
    assert alternate_identity.bootstrap_user == "freq-bootstrap"
    assert round_trip.bootstrap_user == "freq-bootstrap"
    with pytest.raises(dataclasses.FrozenInstanceError):
        value.bootstrap_user = "changed"
    with pytest.raises(TypeError):
        InitPhase2ResumeProvenance(
            config_fingerprint="a" * 64,
            bootstrap_user="root",
            bootstrap_auth="key",
            password="must-not-exist",
        )

    invalid_values = (
        ("config_fingerprint", "a" * 63),
        ("config_fingerprint", "A" * 64),
        ("config_fingerprint", "g" * 64),
        ("config_fingerprint", None),
        ("bootstrap_user", ""),
        ("bootstrap_user", " root "),
        ("bootstrap_user", None),
        ("bootstrap_auth", "token"),
        ("bootstrap_auth", None),
        ("mode", "interactive"),
        ("version", 2),
        ("version", True),
    )
    for field, invalid in invalid_values:
        values = {
            "config_fingerprint": "a" * 64,
            "bootstrap_user": "root",
            "bootstrap_auth": "password",
        }
        values[field] = invalid
        with pytest.raises(ValueError):
            InitPhase2ResumeProvenance(**values)
