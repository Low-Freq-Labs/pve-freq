"""Automated sweep — audit → check → diff → fix → verify pipeline.

Chains existing FREQ commands into a single automated flow.
The "I want everything checked and fixed" command.

Usage:
  freq sweep              # dry-run: audit + check all policies
  freq sweep --fix        # apply: audit + fix all policies + verify
"""
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.engine.policies import ALL_POLICIES
from freq.engine.runner import run_sync
from freq.core.types import Phase


def cmd_sweep(cfg: FreqConfig, pack, args) -> int:
    """Run a full security and compliance sweep across the fleet."""
    fix_mode = getattr(args, "fix", False)
    mode = "fix" if fix_mode else "check"

    fmt.header("Sweep" + (" — APPLY MODE" if fix_mode else " — DRY RUN"))
    fmt.blank()

    if not cfg.hosts:
        fmt.error("No hosts registered.")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.line(f"{fmt.C.BOLD}Fleet:{fmt.C.RESET} {len(cfg.hosts)} hosts")
    fmt.line(f"{fmt.C.BOLD}Policies:{fmt.C.RESET} {len(ALL_POLICIES)}")
    fmt.line(f"{fmt.C.BOLD}Mode:{fmt.C.RESET} {'APPLY (will make changes)' if fix_mode else 'CHECK (dry run, no changes)'}")
    fmt.blank()

    if fix_mode and not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Run sweep in fix mode? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Step 1: Run audit
    fmt.divider("Step 1: Security Audit")
    fmt.blank()
    from freq.modules.audit import cmd_audit
    import argparse
    audit_args = argparse.Namespace(fix=False)
    cmd_audit(cfg, pack, audit_args)

    # Step 2: Run each policy
    total_start = time.monotonic()
    total_compliant = 0
    total_drift = 0
    total_fixed = 0
    total_failed = 0

    for policy in ALL_POLICIES:
        fmt.blank()
        fmt.divider(f"Step 2: Policy — {policy['name']}")
        fmt.blank()

        result = run_sync(
            cfg.hosts, policy, cfg.ssh_key_path,
            mode=mode, max_parallel=cfg.ssh_max_parallel,
        )

        # Summary per policy
        for h in result.hosts:
            if h.phase == Phase.COMPLIANT:
                total_compliant += 1
                print(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {h.label}: compliant")
            elif h.phase == Phase.DONE:
                total_fixed += 1
                print(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {h.label}: {len(h.changes)} fixed")
            elif h.phase in (Phase.DRIFT, Phase.PLANNED):
                total_drift += 1
                print(f"  {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET}  {h.label}: {len(h.findings)} drift items")
                for f in h.findings:
                    print(f"    {fmt.C.DIM}{f.key}: {f.current} → {f.desired}{fmt.C.RESET}")
            elif h.phase == Phase.FAILED:
                total_failed += 1
                print(f"  {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {h.label}: {h.error}")

    total_duration = time.monotonic() - total_start

    # Final summary
    fmt.blank()
    fmt.divider("Sweep Complete")
    fmt.blank()
    fmt.line(
        f"  {fmt.C.GREEN}{total_compliant}{fmt.C.RESET} compliant  "
        f"{fmt.C.YELLOW}{total_drift}{fmt.C.RESET} drift  "
        f"{fmt.C.GREEN}{total_fixed}{fmt.C.RESET} fixed  "
        f"{fmt.C.RED}{total_failed}{fmt.C.RESET} failed  "
        f"({total_duration:.1f}s)"
    )

    if total_drift > 0 and not fix_mode:
        fmt.blank()
        fmt.line(f"  {fmt.C.GRAY}Run with --fix to apply remediation.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()

    logger.info("sweep complete", mode=mode, compliant=total_compliant,
                drift=total_drift, fixed=total_fixed, failed=total_failed)
    return 0 if total_failed == 0 else 1
