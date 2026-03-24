"""Engine CLI commands for FREQ.

Commands: check, fix, diff, policies
These connect the declarative policy engine to the CLI.
"""
from freq.core import fmt
from freq.core import resolve
from freq.core.config import FreqConfig
from freq.engine.policy import PolicyExecutor, PolicyStore
from freq.engine.runner import run_sync
from freq.engine.policies import ALL_POLICIES
from freq.core.types import Phase


def _build_store() -> PolicyStore:
    """Build the policy store with all built-in policies."""
    store = PolicyStore()
    for p in ALL_POLICIES:
        store.register(p)
    return store


def _resolve_hosts(cfg: FreqConfig, args) -> list:
    """Resolve host targets from args."""
    host_filter = getattr(args, "hosts", None)
    if host_filter:
        return resolve.by_labels(cfg.hosts, host_filter)
    return cfg.hosts


def cmd_policies(cfg: FreqConfig, pack, args) -> int:
    """List all available policies."""
    fmt.header("Policies")
    fmt.blank()

    store = _build_store()
    policies = store.list()

    if not policies:
        fmt.line(f"{fmt.C.YELLOW}No policies registered.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.table_header(
        ("NAME", 20),
        ("SCOPE", 20),
        ("DESCRIPTION", 30),
    )

    for p in policies:
        scope = ", ".join(p.get("scope", []))
        fmt.table_row(
            (f"{fmt.C.CYAN}{p['name']}{fmt.C.RESET}", 20),
            (scope, 20),
            (f"{fmt.C.DIM}{p.get('description', '')[:30]}{fmt.C.RESET}", 30),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.GRAY}{len(policies)} policy(ies) available{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.GRAY}Usage: freq check <policy> [--hosts label1,label2]{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def cmd_check(cfg: FreqConfig, pack, args) -> int:
    """Check policy compliance (dry run)."""
    policy_name = getattr(args, "policy", None)
    if not policy_name:
        fmt.error("Usage: freq check <policy> [--hosts host1,host2]")
        fmt.info("Run 'freq policies' to see available policies.")
        return 1

    store = _build_store()
    policy = store.get(policy_name)
    if not policy:
        fmt.error(f"Policy not found: {policy_name}")
        fmt.info(f"Available: {', '.join(p['name'] for p in store.list())}")
        return 1

    hosts = _resolve_hosts(cfg, args)
    if not hosts:
        fmt.error("No hosts to check.")
        return 1

    fmt.header(f"Check: {policy_name}")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Policy:{fmt.C.RESET} {policy['description']}")
    fmt.line(f"{fmt.C.BOLD}Scope:{fmt.C.RESET}  {', '.join(policy.get('scope', []))}")
    fmt.line(f"{fmt.C.BOLD}Hosts:{fmt.C.RESET}  {len(hosts)}")
    fmt.blank()

    # Run pipeline in check mode
    result = run_sync(hosts, policy, cfg.ssh_key_path, mode="check",
                      max_parallel=cfg.ssh_max_parallel)

    # Display results
    fmt.table_header(
        ("HOST", 16),
        ("STATUS", 12),
        ("FINDINGS", 8),
        ("TIME", 6),
    )

    for h in result.hosts:
        if h.phase == Phase.COMPLIANT:
            status = fmt.badge("compliant")
            finding_count = "0"
        elif h.phase == Phase.PLANNED:
            status = fmt.badge("drift")
            finding_count = str(len(h.findings))
        elif h.phase == Phase.FAILED:
            status = fmt.badge("failed")
            finding_count = h.error[:20]
        else:
            status = fmt.badge(h.phase.name.lower())
            finding_count = str(len(h.findings))

        fmt.table_row(
            (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 16),
            (status, 12),
            (finding_count, 8),
            (f"{h.duration:.1f}s", 6),
        )

        # Show findings detail
        for f in h.findings:
            print(f"    {fmt.C.YELLOW}{f.key}:{fmt.C.RESET} "
                  f"{fmt.C.RED}{f.current}{fmt.C.RESET} → "
                  f"{fmt.C.GREEN}{f.desired}{fmt.C.RESET}")

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(
        f"  {fmt.C.GREEN}{result.compliant}{fmt.C.RESET} compliant  "
        f"{fmt.C.YELLOW}{result.drift}{fmt.C.RESET} drift  "
        f"{fmt.C.RED}{result.failed}{fmt.C.RESET} failed  "
        f"({result.total} hosts, {result.duration:.1f}s)"
    )
    fmt.blank()
    fmt.footer()

    return 0 if result.failed == 0 else 1


def cmd_fix(cfg: FreqConfig, pack, args) -> int:
    """Apply policy remediation."""
    policy_name = getattr(args, "policy", None)
    if not policy_name:
        fmt.error("Usage: freq fix <policy> [--hosts host1,host2]")
        return 1

    store = _build_store()
    policy = store.get(policy_name)
    if not policy:
        fmt.error(f"Policy not found: {policy_name}")
        return 1

    hosts = _resolve_hosts(cfg, args)
    if not hosts:
        fmt.error("No hosts to fix.")
        return 1

    fmt.header(f"Fix: {policy_name}")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Policy:{fmt.C.RESET} {policy['description']}")
    fmt.line(f"{fmt.C.BOLD}Mode:{fmt.C.RESET}   {fmt.C.RED}APPLY (changes will be made){fmt.C.RESET}")
    fmt.blank()

    # Confirm
    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Apply fixes to {len(hosts)} hosts? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Run pipeline in fix mode
    result = run_sync(hosts, policy, cfg.ssh_key_path, mode="fix",
                      max_parallel=cfg.ssh_max_parallel)

    # Display results
    for h in result.hosts:
        if h.phase == Phase.DONE:
            fmt.step_ok(f"{h.label}: {len(h.changes)} fixed ({h.duration:.1f}s)")
            for change in h.changes:
                print(f"    {fmt.C.DIM}{change}{fmt.C.RESET}")
        elif h.phase == Phase.COMPLIANT:
            fmt.step_info(f"{h.label}: already compliant")
        elif h.phase == Phase.FAILED:
            fmt.step_fail(f"{h.label}: {h.error}")
        else:
            fmt.step_warn(f"{h.label}: {h.phase.name}")

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(
        f"  {fmt.C.GREEN}{result.fixed}{fmt.C.RESET} fixed  "
        f"{fmt.C.GREEN}{result.compliant}{fmt.C.RESET} already ok  "
        f"{fmt.C.RED}{result.failed}{fmt.C.RESET} failed  "
        f"({result.total} hosts, {result.duration:.1f}s)"
    )
    fmt.blank()
    fmt.footer()

    return 0 if result.failed == 0 else 1


def cmd_diff(cfg: FreqConfig, pack, args) -> int:
    """Show policy drift as git-style diff."""
    policy_name = getattr(args, "policy", None)
    if not policy_name:
        fmt.error("Usage: freq diff <policy> [--hosts host1,host2]")
        return 1

    store = _build_store()
    policy = store.get(policy_name)
    if not policy:
        fmt.error(f"Policy not found: {policy_name}")
        return 1

    hosts = _resolve_hosts(cfg, args)
    if not hosts:
        fmt.error("No hosts to diff.")
        return 1

    fmt.header(f"Diff: {policy_name}")
    fmt.blank()

    # Run pipeline in check mode
    result = run_sync(hosts, policy, cfg.ssh_key_path, mode="check",
                      max_parallel=cfg.ssh_max_parallel)

    executor = PolicyExecutor(policy)

    has_drift = False
    for h in result.hosts:
        if h.phase == Phase.COMPLIANT:
            continue

        has_drift = True
        print(f"  {fmt.C.BOLD}{h.label}{fmt.C.RESET} ({h.ip})")

        diff_text = executor.diff_text(h.current, h.desired)
        if diff_text:
            for line in diff_text.split("\n"):
                if line.startswith("---") or line.startswith("+++"):
                    print(f"  {fmt.C.BOLD}{line}{fmt.C.RESET}")
                elif line.startswith("-"):
                    print(f"  {fmt.C.RED}{line}{fmt.C.RESET}")
                elif line.startswith("+"):
                    print(f"  {fmt.C.GREEN}{line}{fmt.C.RESET}")
                elif line.startswith("@@"):
                    print(f"  {fmt.C.CYAN}{line}{fmt.C.RESET}")
                else:
                    print(f"  {line}")
        print()

    if not has_drift:
        fmt.line(f"{fmt.C.GREEN}All hosts compliant. No drift detected.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0
