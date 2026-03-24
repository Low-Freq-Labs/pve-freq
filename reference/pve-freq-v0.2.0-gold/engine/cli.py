"""Engine CLI — the interface between bash and Python.

Entry point: `python3 -m engine <command> [policy] [options]`

Commands:
  check <policy>    — Discover drift (dry run, no changes)
  fix <policy>      — Discover + fix + verify (applies changes)
  diff <policy>     — Show git-style colored diffs
  policies          — List available policies
  status            — Show last run from history

Options:
  --freq-dir        — FREQ install directory (default: /opt/pve-freq)
  --hosts-file      — Path to hosts.conf
  --hosts           — Comma-separated host labels to target
  --dry-run         — Check only, no changes (implicit for check/diff)
  --json            — JSON output mode
  --max-parallel    — Max concurrent SSH connections (default: 5)
  --stdin           — Read options from stdin JSON
  --password        — SSH password (or read from env FREQ_SSH_PASSWORD)
  --verbose         — Show engine debug log
"""
import argparse
import asyncio
import os
import sys
import json


def main() -> int:
    """Main entry point for the engine CLI."""
    parser = argparse.ArgumentParser(
        prog="freq-engine",
        description="PVE FREQ Remediation Engine v2.0.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 -m engine check ssh-hardening\n"
            "  python3 -m engine fix ssh-hardening --hosts vm101,vm102\n"
            "  python3 -m engine diff ssh-hardening\n"
            "  python3 -m engine policies --json\n"
        ),
    )
    parser.add_argument(
        "command",
        choices=["check", "fix", "diff", "policies", "status"],
        help="Engine command",
    )
    parser.add_argument(
        "policy", nargs="?", default="",
        help="Policy name (required for check/fix/diff)",
    )
    parser.add_argument(
        "--freq-dir", default="/opt/pve-freq",
        help="FREQ install directory",
    )
    parser.add_argument(
        "--hosts-file", default="",
        help="Path to hosts.conf",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Check only, no changes",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON output mode",
    )
    parser.add_argument(
        "--hosts", default="",
        help="Comma-separated host labels to target",
    )
    parser.add_argument(
        "--max-parallel", type=int, default=5,
        help="Max concurrent SSH connections",
    )
    parser.add_argument(
        "--stdin", action="store_true",
        help="Read options from stdin JSON",
    )
    parser.add_argument(
        "--password", default="",
        help="SSH password (or set FREQ_SSH_PASSWORD env var)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show engine debug log after run",
    )
    parser.add_argument(
        "--connect-timeout", type=int, default=10,
        help="SSH connect timeout in seconds",
    )
    parser.add_argument(
        "--command-timeout", type=int, default=30,
        help="SSH command timeout in seconds",
    )

    args = parser.parse_args()

    # Handle stdin override
    if args.stdin:
        try:
            stdin_data = json.loads(sys.stdin.read())
            if "hosts" in stdin_data:
                args.hosts = ",".join(stdin_data["hosts"]) if isinstance(stdin_data["hosts"], list) else stdin_data["hosts"]
            if "dry_run" in stdin_data:
                args.dry_run = stdin_data["dry_run"]
            if "max_parallel" in stdin_data:
                args.max_parallel = stdin_data["max_parallel"]
            if "password" in stdin_data:
                args.password = stdin_data["password"]
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  Error reading stdin JSON: {e}", file=sys.stderr)
            return 1

    # Resolve password
    password = args.password or os.environ.get("FREQ_SSH_PASSWORD", "")
    if not password:
        # Try to read from FREQ vault password file
        vault_pass = os.path.join(args.freq_dir, "data", "vault", "ssh-password")
        if os.path.exists(vault_pass):
            try:
                with open(vault_pass) as f:
                    password = f.read().strip()
            except PermissionError:
                pass

    if not password and args.command in ("check", "fix", "diff"):
        print("  Warning: No SSH password configured.", file=sys.stderr)
        print("  Set FREQ_SSH_PASSWORD env var, use --password, or configure vault.",
              file=sys.stderr)

    # Import engine modules (deferred to avoid import errors at parse time)
    from engine.core.resolver import load_fleet, filter_by_scope, filter_by_labels
    from engine.core.policy import PolicyStore, PolicyExecutor
    from engine.core.runner import PipelineRunner
    from engine.core.display import show_results, show_diff, show_policies
    from engine.core.store import ResultStore

    # Load policies
    policies_dir = os.path.join(args.freq_dir, "engine", "policies")
    store = PolicyStore(policies_dir)

    # ── Command: policies ──
    if args.command == "policies":
        if args.json_output:
            policies_data = [
                {
                    "name": p.name,
                    "description": p.description,
                    "scope": p.scope,
                    "resources": len(p.resources),
                }
                for p in store.list_all()
            ]
            print(json.dumps(policies_data, indent=2))
        else:
            show_policies(store.list_all())
        return 0

    # ── Command: status ──
    if args.command == "status":
        db_path = os.path.join(args.freq_dir, "data", "engine", "results.db")
        if os.path.exists(db_path):
            rs = ResultStore(db_path)
            last = rs.last_run(args.policy)
            if last:
                if args.json_output:
                    print(json.dumps(last, indent=2))
                else:
                    print(f"  Last run: {last['timestamp']} — "
                          f"{last['policy']} ({last['mode']}) "
                          f"in {last['duration']:.1f}s")
                    print(f"  Results: {last['compliant']} compliant, "
                          f"{last['drift']} drift, "
                          f"{last['fixed']} fixed, "
                          f"{last['failed']} failed")
            else:
                print("  No previous runs.")
            rs.close()
        else:
            print("  No engine history. Run 'freq check <policy>' first.")
        return 0

    # ── Commands: check, fix, diff — all need a policy ──
    if not args.policy:
        print("  Usage: freq check <policy>")
        print("  Run 'freq policies' to see available policies.")
        return 1

    policy = store.get(args.policy)
    if not policy:
        print(f"  Unknown policy: {args.policy}")
        available = ", ".join(p.name for p in store.list_all())
        if available:
            print(f"  Available: {available}")
        else:
            print(f"  No policies found in {policies_dir}")
        return 1

    # Load fleet
    hosts_file = args.hosts_file or os.path.join(args.freq_dir, "conf", "hosts.conf")
    fleet = load_fleet(hosts_file)
    fleet = filter_by_scope(fleet, policy.scope)

    if args.hosts:
        fleet = filter_by_labels(fleet, args.hosts.split(","))

    if not fleet:
        print("  No hosts match this policy's scope.")
        if args.hosts:
            print(f"  Targeted: {args.hosts}")
        print(f"  Policy scope: {', '.join(policy.scope)}")
        return 1

    # Execute
    executor = PolicyExecutor(policy)
    dry_run = args.dry_run or args.command in ("check", "diff")
    runner = PipelineRunner(
        max_parallel=args.max_parallel,
        dry_run=dry_run,
        password=password,
        connect_timeout=args.connect_timeout,
        command_timeout=args.command_timeout,
    )

    result = asyncio.run(runner.run(fleet, executor))

    # Display
    if args.command == "diff":
        for host in result.hosts:
            if host.findings:
                show_diff(host)
        if not any(h.findings for h in result.hosts):
            print("  All hosts compliant — no diffs to show.")
    elif args.json_output:
        output = {
            "policy": result.policy,
            "mode": result.mode,
            "duration": round(result.duration, 2),
            "summary": {
                "total": result.total,
                "compliant": result.compliant,
                "drift": result.drift,
                "fixed": result.fixed,
                "failed": result.failed,
            },
            "hosts": [
                {
                    "label": h.label,
                    "ip": h.ip,
                    "type": h.htype,
                    "phase": h.phase.name,
                    "error": h.error,
                    "findings": [
                        {
                            "key": f.key,
                            "current": str(f.current),
                            "desired": str(f.desired),
                            "severity": f.severity.value,
                        }
                        for f in h.findings
                    ],
                    "changes": h.changes,
                    "duration": round(h.duration, 2),
                }
                for h in result.hosts
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        show_results(result)

    # Show debug log if verbose
    if args.verbose and runner.log:
        print(f"\n  {'─'*40}")
        print(f"  Engine Debug Log:")
        for entry in runner.log:
            print(f"    {entry}")
        print()

    # Store results
    db_path = os.path.join(args.freq_dir, "data", "engine", "results.db")
    try:
        rs = ResultStore(db_path)
        rs.save(result)
        rs.close()
    except Exception as e:
        if args.verbose:
            print(f"  Warning: Could not save results to DB: {e}",
                  file=sys.stderr)

    return 0 if result.failed == 0 else 1
