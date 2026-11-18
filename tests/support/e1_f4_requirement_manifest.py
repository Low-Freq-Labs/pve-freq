#!/usr/bin/env python3
"""Machine-readable composed E1 F4 requirement-to-owner enumeration."""

from __future__ import annotations

import argparse
from pathlib import Path

R1 = "combined R1 0613918f"
R2 = "combined R2 be21c3b9"
C3 = "consumer R3 a0241050"
G4 = "guidance amendment 8a811f69"
E5 = "layer-aware envelope amendment ef12b73c"
L6 = "recovery lifecycle acceptance R2 5aaebb13"

# One composed public-contract source for runtime, OpenAPI, and consumer owners.
# Tests derive their expected sets from these cited rows; they do not restate
# subsets based on the predecessor product behavior.
CREATE_ADMIN_FAILURE_CONTRACT = (
    {
        "scenario": "unsupported_media",
        "status": "400",
        "code": "unsupported_media_type",
        "retryable": False,
        "field": None,
        "runtime": True,
        "authority": f"{R1} §2 lines 55-66 + inherited setup_error default-false contract",
    },
    {
        "scenario": "https",
        "status": "403",
        "code": "https_required",
        "retryable": False,
        "field": None,
        "runtime": True,
        "authority": f"{R1} §1 HTTPS remains mandatory + inherited setup_error contract",
    },
    {
        "scenario": "missing",
        "status": "400",
        "code": "claim_secret_required",
        "retryable": False,
        "field": "claim_secret",
        "runtime": True,
        "authority": f"{R1} §5 lines 240-246",
    },
    {
        "scenario": "wrong",
        "status": "403",
        "code": "claim_secret_invalid",
        "retryable": True,
        "field": "claim_secret",
        "runtime": True,
        "authority": f"{R1} §5 lines 240-246",
    },
    {
        "scenario": "setup_closed",
        "status": "403",
        "code": "setup_closed",
        "retryable": False,
        "field": None,
        "runtime": True,
        "authority": f"{R1} §5 lines 240-251 + {R2} Cross-half 2 + inherited setup_error default-false contract",
    },
    {
        "scenario": "consumed",
        "status": "409",
        "code": "claim_consumed",
        "retryable": False,
        "field": None,
        "runtime": True,
        "authority": f"{R1} §5 lines 240-251 + {R2} Cross-half 2 + inherited setup_error default-false contract",
    },
    {
        "scenario": "operator_exists",
        "status": "409",
        "code": "operator_exists",
        "retryable": False,
        "field": None,
        "runtime": True,
        "authority": f"{R1} §5 lines 240-251 + {R2} Cross-half 2 + inherited setup_error default-false contract",
    },
    {
        "scenario": "setup_busy",
        "status": "409",
        "code": "setup_busy",
        "retryable": True,
        "field": None,
        "runtime": True,
        "authority": f"{R1} §5 nonblocking setup lock + inherited setup_busy projection",
    },
    {
        "scenario": "rate",
        "status": "429",
        "code": "claim_rate_limited",
        "retryable": True,
        "field": None,
        "runtime": True,
        "authority": f"{R1} §4 + §5 lines 240-251",
    },
    {
        "scenario": "unavailable",
        "status": "503",
        "code": "claim_state_unavailable",
        "retryable": True,
        "field": None,
        "runtime": True,
        "authority": f"{R1} §3.2 + §5 lines 240-251",
    },
)

SETUP_ERROR_HELPER_OUTER_PROPERTY_CONTRACT = (
    {"property": "ok", "authority": "inherited setup_error contract freq/api/helpers.py:47-64"},
    {"property": "schema", "authority": "inherited setup_error contract freq/api/helpers.py:47-64"},
    {"property": "error", "authority": "inherited setup_error contract freq/api/helpers.py:47-64"},
)
SETUP_ERROR_HELPER_OUTER_PROPERTIES = frozenset(
    item["property"] for item in SETUP_ERROR_HELPER_OUTER_PROPERTY_CONTRACT
)
PUBLIC_ERROR_OUTER_PROPERTY_CONTRACT = SETUP_ERROR_HELPER_OUTER_PROPERTY_CONTRACT + (
    {
        "property": "request_id",
        "authority": f"{E5} exact serialized public wire + shipped response adapters",
    },
)
PUBLIC_ERROR_OUTER_PROPERTIES = frozenset(item["property"] for item in PUBLIC_ERROR_OUTER_PROPERTY_CONTRACT)
ERROR_ENVELOPE_PROPERTY_CONTRACT = (
    {"property": "code", "authority": f"inherited setup_error contract + {R1} §2 and §5 projections"},
    {"property": "message", "authority": f"inherited setup_error contract + {R1} §5-6 actionable projections"},
    {"property": "retryable", "authority": f"inherited setup_error contract + {R1} §4-6 retry truth"},
)
ERROR_ENVELOPE_BASE_PROPERTIES = frozenset(item["property"] for item in ERROR_ENVELOPE_PROPERTY_CONTRACT)
CONSUMER_INTERNAL_EXCLUSION_CONTRACT = (
    {"fragment": "/opt/", "authority": f"{R1} §3.2 + {R2} Condition 3 remote guidance"},
    {"fragment": "digest", "authority": f"{R1} §3.1 + §5 no digest projection"},
    {"fragment": "claim_state", "authority": f"{R1} §3.2 + §5 no internal state projection"},
    {"fragment": "first-admin-claim.json", "authority": f"{R1} §3.2 internal path boundary"},
    {"fragment": "pending_delivery", "authority": f"{R1} §3.2 + §5 internal state boundary"},
)
CONSUMER_INTERNAL_FRAGMENTS = tuple(item["fragment"] for item in CONSUMER_INTERNAL_EXCLUSION_CONTRACT)
CONSUMER_FORBIDDEN_SHAPE_CONTRACT = (
    {
        "name": "absolute-posix-path",
        "pattern": r"(?<![A-Za-z0-9])/(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+",
        "witness": "/home/finn-ops/state/evidence",
        "authority": f"{C3} Setup-page lines 140-143 + Published contract lines 235-237",
    },
    {
        "name": "absolute-windows-path",
        "pattern": r"\b[A-Za-z]:\\(?:[^\\\s]+\\)+[^\\\s]+",
        "witness": r"C:\internal\claim-state.json",
        "authority": f"{C3} Setup-page lines 140-143 + Published contract lines 235-237",
    },
    {
        "name": "home-relative-path",
        "pattern": r"(?:^|\s)~/(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+",
        "witness": "~/state/evidence",
        "authority": f"{C3} Setup-page lines 140-143 + Published contract lines 235-237",
    },
    {
        "name": "finding-identifier",
        "pattern": r"\b(?:finding\s*(?:number\s*)?[#:]?\s*\d+|F\d+(?:[-_.]\d+)?)\b",
        "witness": "F4 finding 12",
        "authority": f"{C3} Setup-page lines 140-143 + Published contract lines 235-237",
    },
    {
        "name": "internal-symbol-shape",
        "pattern": r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b",
        "witness": "internal_state_name",
        "authority": f"{G4} message and focus safety owners",
    },
    {
        "name": "claim-identifier-label",
        "pattern": r"\bclaim[\s_-]*id\b",
        "witness": "claim ID abc123",
        "authority": f"{G4} message and focus safety owners",
    },
    {
        "name": "relative-posix-path-like",
        "pattern": r"(?<![A-Za-z0-9./-])(?:\.{1,2}/)?(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+",
        "witness": "data/setup/private-state.json",
        "authority": f"{G4} complete message boundary; Clancy R8 block finding 4",
    },
    {
        "name": "canonical-c-finding-identifier",
        "pattern": r"\bC\d{2,}(?:[-_.]\d+)*\b",
        "witness": "C03-12",
        "authority": f"{G4} complete finding-identifier boundary; Clancy R8 block finding 4",
    },
)
CONSUMER_BENIGN_MESSAGE_CONTROLS = (
    "Use the newest first-boot claim from the current service.",
    "Follow the local reset procedure, then retry.",
    "Sign in through the dashboard and resume setup.",
    "The service is temporarily unavailable.",
    "Wait for the current rate window.",
    "Open sign in",
)
CLAIM_GUIDANCE_CONTRACT = (
    {
        "code": "claim_secret_required",
        "action": "provide_claim",
        "focus": "operator-claim",
        "retryable": False,
        "terminal": False,
        "message_tokens": ("first-boot claim", "required"),
        "authority": f"{G4} exhaustive table: claim_secret_required",
    },
    {
        "code": "claim_secret_invalid",
        "action": "replace_claim",
        "focus": "operator-claim",
        "retryable": True,
        "terminal": False,
        "message_tokens": ("newest", "first-admin claim reset", "zero-state runbook"),
        "authority": f"{G4} exhaustive table: claim_secret_invalid",
    },
    {
        "code": "claim_state_unavailable",
        "action": "retry",
        "focus": "create-operator",
        "retryable": True,
        "terminal": False,
        "message_tokens": ("temporarily unavailable", "retry"),
        "authority": f"{G4} exhaustive table: claim_state_unavailable",
    },
    {
        "code": "claim_rate_limited",
        "action": "retry",
        "focus": "create-operator",
        "retryable": True,
        "terminal": False,
        "message_tokens": ("wait", "retry"),
        "authority": f"{G4} exhaustive table: claim_rate_limited",
    },
    {
        "code": "claim_consumed",
        "action": "local_reset",
        "focus": None,
        "retryable": False,
        "terminal": True,
        "message_tokens": ("first-admin claim reset", "zero-state runbook"),
        "authority": f"{G4} exhaustive table + consumed focus amendment 6a1c52e2",
    },
    {
        "code": "setup_closed",
        "action": "sign_in",
        "focus": "resume-sign-in",
        "retryable": False,
        "terminal": True,
        "message_tokens": ("complete", "sign in", "resume"),
        "authority": f"{G4} exhaustive table: setup_closed",
    },
)

OPERATOR_EXISTS_GUIDANCE_CONTRACT = {
    "code": "operator_exists",
    "action": "sign_in",
    "focus": "resume-sign-in",
    "retryable": False,
    "terminal": True,
    "message_tokens": ("sign in",),
    "authority": f"{G4} separate operator-exists disposition",
}


def row(requirement: str, authority: str, owner: str, reason: str = "") -> dict[str, str]:
    return {"requirement": requirement, "authority": authority, "owner": owner, "reason": reason}


REQUIREMENTS = (
    row(
        "authority.composed-numbered-supersessions",
        f"{R1} §9 + {R2} Gate + consumed focus 6a1c52e2 + {G4}",
        "test_f4_design_authority_is_composed_and_numbered",
    ),
    row(
        "scope.f12-remains-separate-and-absent",
        f"{R1} §6 + §9 + {R2} Gate",
        "test_f4_source_scope_keeps_f12_separate",
    ),
    row(
        "media.reject-before-body-read",
        f"{R1} §2 + {C3} Shared parser",
        "test_shared_json_parser_rejects_wrong_media_before_reading_body",
    ),
    row(
        "media.case-parameters-exact-matrix",
        f"{R1} §2 + {C3} Shared parser",
        "test_shared_json_parser_enforces_exact_media_matrix",
    ),
    row(
        "media.exact-twelve-route-inventory",
        f"{R1} §2 + {C3} Product ruling",
        "test_json_parser_route_set_equals_exact_twelve_callers",
    ),
    row(
        "media.all-twelve-dispatch-projection",
        f"{R1} §2 + {C3} Product ruling",
        "test_all_twelve_dispatch_routes_project_wrong_media_before_body_or_handler",
    ),
    row(
        "media.shipped-callers-send-json-direct-clients-only-unshipped",
        f"{R1} §2 + {C3} Shared parser",
        "test_every_shipped_parser_caller_sends_json_and_direct_only_routes_have_no_caller",
    ),
    row(
        "media.correct-claim-text-plain-rejected",
        f"{R1} §2 + {C3} Trust ordering",
        "test_correct_claim_with_text_plain_is_rejected_before_comparison",
    ),
    row(
        "origin.create-admin-not-authentication",
        f"{R1} §2 + {C3} Product ruling",
        "test_correct_claim_succeeds_for_absent_and_hostile_origin",
    ),
    row(
        "origin.wrong-claim-shape-invariant",
        f"{R1} §2 + {C3} Trust ordering",
        "test_wrong_claim_has_same_result_for_every_origin_shape",
    ),
    row(
        "origin.login-required-matching",
        f"{R1} §2 + {C3} Published contract",
        "test_login_route_requires_matching_origin_before_auth_mutation",
    ),
    row(
        "origin.logout-required-matching",
        f"{R1} §2 + {C3} Published contract",
        "test_logout_route_requires_matching_origin_before_session_mutation",
    ),
    row(
        "origin.shared-helper-exact-scheme-authority",
        f"{R1} §2",
        "test_login_logout_origin_helper_requires_present_exact_scheme_and_authority",
    ),
    row(
        "transport.create-admin-https",
        f"{R1} §2 + {C3} Published contract",
        "test_correct_claim_cannot_authorize_cleartext_transport",
    ),
    row("claim.generation-256-bit", f"{R1} §3.1", "test_claim_generation_delivers_256_bits_and_persists_digest_only"),
    row(
        "claim.exact-string-bounds-no-coercion",
        f"{R1} §3.1",
        "test_invalid_request_shapes_do_not_compare_or_consume_claim",
    ),
    row("claim.domain-separated-sha256", f"{R1} §3.1", "test_persisted_digest_is_exactly_domain_separated_sha256"),
    row(
        "claim.digest-only-no-raw-persistence",
        f"{R1} §3.1",
        "test_claim_generation_delivers_256_bits_and_persists_digest_only",
    ),
    row("claim.constant-time-digest-compare", f"{R1} §3.1", "test_exact_candidate_bytes_use_constant_time_comparison"),
    row("claim.unicode-not-normalized", f"{R1} §3.1", "test_unicode_normalization_forms_remain_distinct_candidates"),
    row(
        "claim.bearer-not-mixed-with-origin-host-cookie-ip",
        f"{R1} §3.1",
        "test_same_exact_claim_is_independent_of_host_cookie_client_ip_and_username",
    ),
    row(
        "claim.available-restart-no-redisplay",
        f"{R1} §3.3",
        "test_available_restart_reuses_state_without_redisplaying_secret",
    ),
    row(
        "claim.pending-restart-replacement",
        f"{R1} §3.3 + {R2} Cross-half 1",
        "test_pending_delivery_restart_replaces_old_secret_and_only_newest_matches",
    ),
    row(
        "claim.old-generation-fails-new-commits",
        f"{R2} Cross-half 1",
        "test_pending_generation_old_token_fails_and_new_token_commits",
    ),
    row("claim.consumption-erases-digest-terminal", f"{R1} §3.2", "test_consumption_erases_digest_and_is_terminal"),
    row(
        "claim.local-lost-token-reset",
        f"{R2} Condition 3",
        "test_local_lost_token_reset_replaces_only_zero_state_claim",
    ),
    row(
        "claim.consumed-zero-state-local-reset-core-mechanism",
        f"{R2} Condition 3 + Cross-half 2 + consumed focus amendment 6a1c52e2",
        "test_consumed_zero_state_local_reset_regenerates_once_and_configured_state_stays_closed",
        "narrow helper-level proof only; it does not satisfy the governed service lifecycle",
    ),
    row(
        "claim.consumed-stop-delete-restart-full-lifecycle",
        f"{L6} accepted by Clancy and Jarvis",
        "test_consumed_recovery_uses_production_start_stop_delete_restart_lifecycle",
    ),
    row(
        "claim.configured-user-and-marker-independent-restart-negatives",
        f"{L6} accepted by Clancy and Jarvis",
        "test_configured_recovery_cases_each_run_independent_full_lifecycle",
    ),
    row(
        "claim.consumed-lifecycle-each-wrong-path-independently-red",
        f"{L6} differential witnesses",
        "test_each_consumed_recovery_lifecycle_wrong_path_is_independently_red",
    ),
    row(
        "claim.configured-lifecycle-each-wrong-path-independently-red",
        f"{L6} differential witnesses",
        "test_each_configured_recovery_wrong_path_is_independently_red",
    ),
    row(
        "claim.lifecycle-create-admin-production-route-entry-and-mutations",
        f"{L6} create-admin routing may-not-replace boundary; Clancy R9 block",
        "test_lifecycle_create_admin_route_removal_and_retarget_are_independently_red",
    ),
    row(
        "claim.all-product-channels-secret-free",
        f"{R1} §3.1 + §7",
        "test_raw_claim_is_excluded_from_every_observable_product_channel",
    ),
    row(
        "state.path-never-remotely-published",
        f"{R1} §3.2",
        "test_openapi_and_human_contract_publish_claim_json_and_local_recovery_truth",
    ),
    row(
        "state.allowlisted-schema-types-transitions",
        f"{R1} §3.2",
        "test_claim_state_rejects_unknown_types_and_impossible_transitions",
    ),
    row("state.symlink-rejected", f"{R1} §3.2", "test_claim_state_rejects_unsafe_file_shapes_and_repairs_private_mode"),
    row(
        "state.non-regular-rejected",
        f"{R1} §3.2",
        "test_claim_state_rejects_unsafe_file_shapes_and_repairs_private_mode",
    ),
    row(
        "state.multi-link-rejected",
        f"{R1} §3.2",
        "test_claim_state_rejects_unsafe_file_shapes_and_repairs_private_mode",
    ),
    row(
        "state.repairable-mode-repaired",
        f"{R1} §3.2",
        "test_claim_state_rejects_unsafe_file_shapes_and_repairs_private_mode",
    ),
    row(
        "state.unrepairable-mode-fails",
        f"{R1} §3.2",
        "test_claim_state_rejects_unsafe_file_shapes_and_repairs_private_mode",
    ),
    row("state.read-error-fails", f"{R1} §3.2", "test_zero_state_unreadable_claim_aborts_cmd_serve_before_listener"),
    row(
        "state.directory-mode-0700",
        f"{R1} §3.2",
        "test_claim_state_write_is_nofollow_same_directory_atomic_and_durable",
    ),
    row(
        "state.state-lock-temp-mode-0600",
        f"{R1} §3.2",
        "test_claim_state_write_is_nofollow_same_directory_atomic_and_durable",
    ),
    row(
        "state.nofollow-regular-link-verification",
        f"{R1} §3.2",
        "test_claim_state_write_is_nofollow_same_directory_atomic_and_durable",
    ),
    row(
        "state.stable-private-flock",
        f"{R1} §3.2",
        "test_claim_uses_stable_private_flock_for_full_transaction_lifetime",
        "R5 acquisition/fd-open body passed reviewer reading but did not prove lifetime; R6 requires a blocked contender and post-exit acquisition",
    ),
    row(
        "state.same-directory-temp-replace",
        f"{R1} §3.2",
        "test_claim_state_write_is_nofollow_same_directory_atomic_and_durable",
    ),
    row(
        "state.file-fsync-replace-directory-fsync",
        f"{R1} §3.2",
        "test_claim_state_write_is_nofollow_same_directory_atomic_and_durable",
    ),
    row("state.existing-ownership-preserved", f"{R1} §3.2", "test_claim_state_preserves_existing_ownership"),
    row(
        "state.write-delivery-failures-surface",
        f"{R1} §3.2",
        "test_claim_state_write_and_delivery_failures_surface_without_available_state",
    ),
    row(
        "startup.route-construction-before-preparation",
        f"{R1} §3.3",
        "test_startup_orders_observation_delivery_workers_listener_and_readiness",
    ),
    row(
        "startup.user-observation-failure-closed",
        f"{R1} §3.3",
        "test_startup_observation_failure_aborts_before_listener_construction",
    ),
    row(
        "startup.marker-observation-failure-closed",
        f"{R1} §3.3",
        "test_marker_observation_failure_aborts_before_listener",
    ),
    row(
        "startup.zero-state-corrupt-fails-before-listener",
        f"{R1} §3.3 + {R2} Condition 2",
        "test_zero_state_corrupt_claim_aborts_cmd_serve_before_listener",
    ),
    row(
        "startup.configured-corrupt-warns-ready",
        f"{R2} Condition 2",
        "test_configured_corrupt_claim_reaches_cmd_serve_readiness_secret_free",
    ),
    row(
        "startup.configured-symlink-unreadable-warns-ready",
        f"{R2} Condition 2",
        "test_configured_unsafe_state_and_cleanup_failure_reach_readiness",
    ),
    row(
        "startup.configured-reconciliation-write-failure-warns-ready",
        f"{R2} Condition 2",
        "test_configured_unsafe_state_and_cleanup_failure_reach_readiness",
    ),
    row(
        "startup.delivery-before-workers-listener-readiness",
        f"{R1} §3.3",
        "test_startup_orders_observation_delivery_workers_listener_and_readiness",
    ),
    row(
        "startup.delivery-line-timestamp-id-token",
        f"{R2} Cross-half 1",
        "test_startup_orders_observation_delivery_workers_listener_and_readiness",
    ),
    row(
        "startup.delivery-sink-flushed-before-available-listener",
        f"{R1} §3.3",
        "test_startup_orders_observation_delivery_workers_listener_and_readiness",
    ),
    row(
        "startup.readiness-matching-id-no-token",
        f"{R2} Cross-half 1",
        "test_startup_orders_observation_delivery_workers_listener_and_readiness",
    ),
    row("rate.per-client-five-full-300-second-window", f"{R1} §4", "test_rate_limiter_exact_edges_and_full_window"),
    row(
        "rate.global-fifty-full-300-second-window",
        f"{R1} §4 + {R2} Condition 1",
        "test_rate_limiter_exact_edges_and_full_window",
    ),
    row(
        "rate.correct-claim-global-bypass",
        f"{R2} Condition 1",
        "test_global_saturation_through_handler_allows_fresh_correct_claim",
    ),
    row(
        "rate.fresh-wrong-global-rejected",
        f"{R2} Condition 1",
        "test_global_saturation_through_handler_rejects_fresh_wrong_claim_without_mutation",
    ),
    row(
        "rate.per-client-before-compare",
        f"{R1} §4",
        "test_per_client_saturation_through_handler_rejects_correct_claim_before_compare",
    ),
    row(
        "rate.trusted-proxy-aware-resolved-client",
        f"{R1} §4",
        "test_claim_rate_bucket_uses_resolved_client_ip",
    ),
    row(
        "rate.media-missing-not-counted",
        f"{R1} §4",
        "test_media_and_missing_claim_failures_do_not_consume_claim_attempts",
    ),
    row("rate.failed-commit-does-not-clear", f"{R1} §4", "test_failed_registry_commit_does_not_clear_client_failures"),
    row(
        "rate.success-clears-calling-client-only", f"{R1} §4", "test_successful_commit_clears_the_calling_client_bucket"
    ),
    row(
        "rate.429-stable-neutral-retryable-secret-free",
        f"{R1} §6",
        "test_claim_failures_publish_exact_stable_envelopes_without_reflection",
    ),
    row(
        "request.json-object-only", f"{C3} Trust ordering", "test_non_object_and_wrong_field_types_fail_before_compare"
    ),
    row(
        "request.exact-five-keys",
        f"{R1} §5 + {C3} Setup-page",
        "test_invalid_request_shapes_do_not_compare_or_consume_claim",
    ),
    row("request.all-required-field-types", f"{R1} §5", "test_non_object_and_wrong_field_types_fail_before_compare"),
    row(
        "request.no-server-path-or-extra-keys",
        f"{R1} §5",
        "test_invalid_request_shapes_do_not_compare_or_consume_claim",
    ),
    row(
        "transaction.setup-lock-then-claim-lock",
        f"{R1} §5 + {R2} Cross-half 2",
        "test_create_admin_acquires_setup_then_claim_lock_in_order",
    ),
    row(
        "transaction.setup-lock-nonblocking-busy-no-claim-or-mutation",
        f"{R1} §5",
        "test_create_admin_setup_lock_busy_is_nonblocking_and_never_enters_claim_or_mutation",
    ),
    row(
        "transaction.reobserve-marker-users-under-lock-before-claim-truth",
        f"{R2} Cross-half 2",
        "test_create_admin_reobserves_marker_and_users_inside_both_locks_before_claim_state",
    ),
    row(
        "transaction.wrong-claim-zero-credential-user-setup-session-state-mutation",
        f"{R1} §5",
        "test_wrong_claim_has_same_result_for_every_origin_shape",
    ),
    row(
        "transaction.consume-immediately-after-registry-before-session",
        f"{R1} §5",
        "test_session_projection_failure_after_commit_does_not_reopen_claim",
    ),
    row(
        "transaction.invalid-operator-fields-claim-reusable",
        f"{R1} §5",
        "test_invalid_operator_fields_leave_claim_reusable",
    ),
    row(
        "transaction.password-store-failure-claim-reusable",
        f"{R1} §5",
        "test_failed_admin_persistence_leaves_exact_claim_reusable",
    ),
    row("transaction.registry-failure-claim-reusable", f"{R1} §5", "test_user_registry_failure_leaves_claim_reusable"),
    row(
        "transaction.concurrent-correct-exactly-one",
        f"{R1} §5",
        "test_two_concurrent_correct_claims_commit_exactly_one_admin",
    ),
    row(
        "transaction.commit-survives-consume-write-failure",
        f"{R1} §5",
        "test_user_commit_remains_success_when_claim_terminalization_fails_and_replay_closes",
    ),
    row(
        "transaction.consume-failure-critical-warning-secret-free",
        f"{R1} §5",
        "test_user_commit_remains_success_when_claim_terminalization_fails_and_replay_closes",
    ),
    row(
        "transaction.session-projection-failure-does-not-reopen",
        f"{R1} §5",
        "test_session_projection_failure_after_commit_does_not_reopen_claim",
    ),
    row(
        "transaction.stronger-setup-user-truth-before-consumed",
        f"{R2} Cross-half 2",
        "test_consumed_replay_projects_stronger_product_truth_first",
    ),
    row(
        "projection.required-invalid-unavailable-rate-consumed",
        f"{R1} §5",
        "test_claim_failures_publish_exact_stable_envelopes_without_reflection",
    ),
    row(
        "projection.no-candidate-digest-path-reflection",
        f"{R1} §5",
        "test_claim_failures_publish_exact_stable_envelopes_without_reflection",
    ),
    row(
        "projection.schema-rejection-no-live-claim-reflection",
        f"{R1} §5 + Clancy 2026-08-13 consumer block",
        "test_create_admin_schema_rejection_never_reflects_live_claim",
    ),
    row(
        "projection.unknown-key-rejection-no-live-claim-reflection",
        f"{R1} §5 + Clancy 2026-08-13 consumer block",
        "test_create_admin_unknown_key_rejection_never_reflects_live_claim",
    ),
    row(
        "projection.create-admin-secret-excluded-by-construction",
        f"{R1} §5 + Jarvis/Clancy additive correction gate",
        "test_create_admin_shipped_boundary_blocks_future_reflective_validator",
    ),
    row(
        "projection.closed-template-api-no-arbitrary-data",
        f"{R1} §5 + Clancy 2026-08-13 template correction gate",
        "test_create_admin_template_api_accepts_no_arbitrary_projection_data",
    ),
    row(
        "projection.short-candidates-stable-403-no-critical",
        f"{R1} §5 + Clancy/Jarvis false-positive block",
        "test_short_collision_candidates_share_exact_403_without_critical_or_reflection",
    ),
    row(
        "projection.short-candidates-saturated-429-no-critical",
        f"{R1} §4/§5 + Clancy/Jarvis false-positive block",
        "test_short_collision_candidates_preserve_exact_saturated_429_without_critical",
    ),
    row(
        "projection.unapproved-template-fails-closed",
        f"{R1} §5 + Clancy 2026-08-13 template correction gate",
        "test_unapproved_create_admin_template_fails_closed_without_projection",
    ),
    row(
        "projection.malformed-shape-full-surface-no-submitted-claim",
        f"{R1} §5 + Jarvis/Clancy additive correction gate",
        "test_create_admin_malformed_shape_matrix_never_projects_submitted_claim",
    ),
    row(
        "consumer.form-post-no-action",
        f"{C3} Setup-page",
        "test_operator_claim_field_and_submission_contract_are_explicit_and_secret_safe",
    ),
    row(
        "consumer.nameless-password-field-exact-attributes",
        f"{C3} Setup-page",
        "test_operator_claim_field_and_submission_contract_are_explicit_and_secret_safe",
    ),
    row("consumer.native-formdata-exclusion", f"{C3} Governed proof", "tests/e2e/e1-f4-first-admin-claim.spec.js"),
    row("consumer.local-nonempty-no-request", f"{C3} Setup-page", "tests/e2e/e1-f4-first-admin-claim.spec.js"),
    row("consumer.exact-unmodified-five-key-json", f"{C3} Setup-page", "tests/e2e/e1-f4-first-admin-claim.spec.js"),
    row("consumer.no-url-query-fragment-header", f"{C3} Governed proof", "tests/e2e/e1-f4-first-admin-claim.spec.js"),
    row(
        "consumer.no-cookie-storage-history-location-ever",
        f"{C3} Governed proof",
        "tests/e2e/e1-f4-first-admin-claim.spec.js",
    ),
    row(
        "consumer.failure-alert-focus-stay-exact-message",
        f"{C3} Governed proof",
        "tests/e2e/e1-f4-first-admin-claim.spec.js",
    ),
    row(
        "consumer.failure-no-later-setup-mutation", f"{C3} Governed proof", "tests/e2e/e1-f4-first-admin-claim.spec.js"
    ),
    row(
        "consumer.success-clears-three-before-advance", f"{C3} Setup-page", "tests/e2e/e1-f4-first-admin-claim.spec.js"
    ),
    row(
        "consumer.browser-programmatic-copy-and-c03",
        f"{C3} Setup-page",
        "test_browser_and_programmatic_copy_and_c03_are_explicit",
    ),
    row(
        "consumer.operator-exists-signin-resume",
        f"{G4} separate operator-exists disposition",
        "tests/e2e/e1-f4-first-admin-claim.spec.js",
        "executed helper-call spy proves operator_exists bypasses claimFailureGuidance",
    ),
    row(
        "consumer.each-claim-failure-code-maps-to-its-action",
        f"{C3} Setup-page + {R1} §5-6",
        "test_setup_consumer_executes_code_specific_claim_guidance",
        f"exact exhaustive action/focus/retry/terminal/message truth derives from {G4}",
    ),
    row(
        "consumer.guidance-focus-timing-null-and-unknown-no-fallback",
        f"{G4} focus vocabulary + message/focus owners",
        "tests/e2e/e1-f4-first-admin-claim.spec.js",
    ),
    row(
        "consumer.resume-sign-in-stable-id-reveal-before-focus",
        f"{G4} literal focus vocabulary + separate operator-exists disposition",
        "tests/e2e/e1-f4-first-admin-claim.spec.js",
    ),
    row(
        "consumer.resume-sign-in-exact-visible-copy",
        f"{G4} shipped resume-sign-in delta",
        "test_setup_consumer_operator_exists_preserves_resume_handoff",
    ),
    row(
        "consumer.guidance-relative-path-non-f-finding-exclusions-with-benign-controls",
        f"{G4} complete message boundary + Clancy R8 block finding 4",
        "test_setup_consumer_executes_code_specific_claim_guidance",
    ),
    row(
        "public.create-admin-browser-programmatic-https-post-json",
        f"{C3} Published contract",
        "test_openapi_and_human_contract_publish_claim_json_and_local_recovery_truth",
    ),
    row(
        "public.create-admin-five-fields-write-only",
        f"{C3} Published contract",
        "test_openapi_create_admin_publishes_write_only_secrets_and_stable_failures",
    ),
    row(
        "public.create-admin-no-origin-operation-contract",
        f"{C3} Published contract",
        "test_openapi_and_human_contract_publish_claim_json_and_local_recovery_truth",
    ),
    row(
        "public.login-logout-origin-per-operation",
        f"{C3} Published contract",
        "test_openapi_and_human_contract_publish_claim_json_and_local_recovery_truth",
    ),
    row(
        "public.twelve-operation-json-media-sections",
        f"{R1} §2 + {C3} Published contract",
        "test_openapi_and_human_contract_publish_claim_json_and_local_recovery_truth",
    ),
    row(
        "public.stable-failure-responses",
        f"{C3} Published contract + {E5}",
        "test_openapi_create_admin_publishes_write_only_secrets_and_stable_failures",
        "exact per-status branches and closed envelopes derive from CREATE_ADMIN_FAILURE_CONTRACT",
    ),
    row(
        "public.setup-error-helper-exact-three-key-payload",
        f"{E5} exact helper payload",
        "test_setup_error_helper_and_real_serializer_have_distinct_complete_layers",
    ),
    row(
        "public.create-admin-real-serialized-wire-exact-four-key-envelope",
        f"{E5} exact serialized public wire",
        "test_setup_error_helper_and_real_serializer_have_distinct_complete_layers",
        "wire owner invokes the shipped serializer; its pre-serialization capture proves only the separate helper contract",
    ),
    row(
        "public.create-admin-server-request-id-body-header-correlation",
        f"{E5} exact serialized public wire",
        "test_setup_error_helper_and_real_serializer_have_distinct_complete_layers",
    ),
    row(
        "public.create-admin-openapi-exact-four-key-envelope",
        f"{E5} OpenAPI contract",
        "test_openapi_create_admin_publishes_write_only_secrets_and_stable_failures",
    ),
    row(
        "public.human-contract-exact-four-key-error-envelope",
        f"{E5} human contract",
        "test_human_contract_publishes_exact_serialized_error_envelope",
    ),
    row(
        "public.local-recovery-newest-generation",
        f"{R2} Condition 3 + Cross-half 1",
        "test_runbook_publishes_exact_local_reset_commands_without_remote_path_disclosure",
    ),
    row(
        "public.lt-save-config-exact-consumer-name",
        f"{C3} Shared parser",
        "test_openapi_and_human_contract_publish_claim_json_and_local_recovery_truth",
    ),
    row(
        "public.no-remote-claim-recovery-reveal-regeneration-bypass-or-test-default",
        f"{R1} §3.3 + §7 + {R2} Condition 3",
        "test_shipped_product_has_no_remote_claim_recovery_or_test_bypass_surface",
    ),
    row("fixture.private-0600-delivery-immediate-unlink", f"{R1} §7", "tests/support/hermetic_dashboard.py"),
    row(
        "fixture.direct-helper-actual-no-origin-request",
        f"{C3} Governed proof",
        "test_direct_resume_helper_stays_origin_free_and_uses_injected_claim",
    ),
    row(
        "fixture.real-browser-and-direct-success",
        f"{R1} §7 + {C3} Governed proof",
        "tests/e2e/e1-f4-first-admin-claim.spec.js",
    ),
    row("fixture.capture-modes-disabled", f"{R1} §7", "test_f4_playwright_policy_detects_and_cleans_planted_secret"),
    row(
        "fixture.raw-and-zip-entry-artifact-scan",
        f"{R1} §7",
        "test_f4_playwright_policy_detects_and_cleans_planted_secret",
    ),
    row(
        "fixture.genuine-deflate-planted-positive-control",
        f"{R1} §7",
        "test_f4_playwright_policy_detects_and_cleans_planted_secret",
    ),
    row(
        "fixture.cleanup-pass-fail-and-leak-evidence-removal",
        f"{R1} §7",
        "test_f4_playwright_policy_detects_and_cleans_planted_secret",
    ),
    row(
        "fixture.default-config-cannot-collect-claim-spec",
        f"{R1} §7",
        "test_default_playwright_config_cannot_collect_claim_owner",
    ),
    row(
        "fixture.evidence-destination-bounded-regular-file-nondestructive",
        f"{R1} §7",
        "test_browser_runner_refuses_unsafe_evidence_destinations_without_mutation",
    ),
)


def render_requirement_table(metadata: dict[str, str] | None = None) -> str:
    lines = []
    if metadata:
        lines.extend(
            [
                "# E1 F4 mechanically generated requirement-owner map",
                "",
                f"- exact commit: `{metadata['commit']}`",
                f"- exact tree: `{metadata['tree']}`",
                f"- sole parent: `{metadata['parent']}`",
                f"- Python evidence: {metadata['python_evidence']}",
                f"- browser evidence: {metadata['browser_evidence']}",
                "- generator: `tests/support/e1_f4_requirement_manifest.py`",
                "",
            ]
        )
    lines.extend(
        [
            "## Mechanically enumerated composed requirements",
            "",
            "| Requirement | Authority | Owner | Status | Reason |",
            "|---|---|---|---|---|",
        ]
    )
    unowned = []
    for item in REQUIREMENTS:
        owner = item["owner"]
        status = "UNOWNED" if owner == "UNOWNED" else "owned"
        if status == "UNOWNED":
            unowned.append(item)
        values = [item["requirement"], item["authority"], owner, status, item["reason"]]
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
    lines.extend(["", "## Explicit unowned rows (computed)", ""])
    if unowned:
        for item in unowned:
            lines.append(f"- `{item['requirement']}`: {item['reason']}")
    else:
        lines.append(f"None — computed from {len(REQUIREMENTS)} enumerated rows with zero `UNOWNED` owners.")
    lines.extend(
        [
            "",
            "## Derived create-admin public failure contract",
            "",
            "Scoped governed F4 subset: exact equality applies to each listed code's status and wrapper, not to the complete inherited create-admin failure inventory. Truthful additional documented branches remain allowed.",
            "",
            "| Status | Code | Retryable | Field | Runtime owner | Authority |",
            "|---|---|---|---|---|---|",
        ]
    )
    for item in CREATE_ADMIN_FAILURE_CONTRACT:
        values = [
            item["status"],
            item["code"],
            str(item["retryable"]).lower(),
            item["field"] or "—",
            str(item["runtime"]).lower(),
            item["authority"],
        ]
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
    lines.extend(
        [
            "",
            "## Derived setup consumer guidance contract",
            "",
            "| Code | Action | Focus | Retryable | Terminal | Message tokens | Authority |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for item in CLAIM_GUIDANCE_CONTRACT:
        values = [
            item["code"],
            item["action"],
            item["focus"] or "null",
            str(item["retryable"]).lower(),
            str(item["terminal"]).lower(),
            ", ".join(item["message_tokens"]),
            item["authority"],
        ]
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
    lines.extend(
        [
            "",
            "## Derived exact-envelope and consumer-guidance exclusions",
            "",
            "| Kind | Value | Authority |",
            "|---|---|---|",
        ]
    )
    for item in ERROR_ENVELOPE_PROPERTY_CONTRACT:
        lines.append(f"| exact base error property | `{item['property']}` | {item['authority']} |")
    for item in CONSUMER_INTERNAL_EXCLUSION_CONTRACT:
        lines.append(f"| banned consumer-guidance fragment | `{item['fragment']}` | {item['authority']} |")
    for item in CONSUMER_FORBIDDEN_SHAPE_CONTRACT:
        lines.append(f"| forbidden guidance shape | `{item['name']}` | {item['authority']} |")
    lines.extend(
        [
            "",
            "## Exact setup-error helper payload",
            "",
            "| Property | Authority |",
            "|---|---|",
        ]
    )
    for item in SETUP_ERROR_HELPER_OUTER_PROPERTY_CONTRACT:
        lines.append(f"| `{item['property']}` | {item['authority']} |")
    lines.extend(
        [
            "",
            "## Exact serialized public error envelope",
            "",
            "The wire owner exercises the real serializer. A mock at the boundary under assertion makes adapter augmentation invisible and cannot prove shipped bytes.",
            "",
            "| Property | Authority |",
            "|---|---|",
        ]
    )
    for item in PUBLIC_ERROR_OUTER_PROPERTY_CONTRACT:
        lines.append(f"| `{item['property']}` | {item['authority']} |")
    lines.extend(
        [
            "",
            "## Separate operator-exists consumer disposition",
            "",
            f"- code: `{OPERATOR_EXISTS_GUIDANCE_CONTRACT['code']}`",
            f"- action: `{OPERATOR_EXISTS_GUIDANCE_CONTRACT['action']}`",
            f"- focus: `{OPERATOR_EXISTS_GUIDANCE_CONTRACT['focus']}`",
            f"- retryable: `{str(OPERATOR_EXISTS_GUIDANCE_CONTRACT['retryable']).lower()}`",
            f"- terminal: `{str(OPERATOR_EXISTS_GUIDANCE_CONTRACT['terminal']).lower()}`",
            f"- authority: {OPERATOR_EXISTS_GUIDANCE_CONTRACT['authority']}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--commit")
    parser.add_argument("--tree")
    parser.add_argument("--parent")
    parser.add_argument("--python-evidence")
    parser.add_argument("--browser-evidence")
    args = parser.parse_args()
    metadata = None
    if args.output:
        required = {
            "commit": args.commit,
            "tree": args.tree,
            "parent": args.parent,
            "python_evidence": args.python_evidence,
            "browser_evidence": args.browser_evidence,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            parser.error("generated output requires " + ", ".join(missing))
        metadata = required
    rendered = render_requirement_table(metadata)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
