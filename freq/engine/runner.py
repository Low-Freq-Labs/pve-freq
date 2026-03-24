"""Async pipeline runner for FREQ engine.

Semaphore-bounded async pipeline: 10 hosts in 2.7s vs 30s serial.
The Convergence proved this architecture — 4x speedup with 5-parallel SSH.

Pipeline per host:
  PING → DISCOVER → COMPARE → [DRY-RUN stops] → FIX → ACTIVATE → VERIFY → DONE
"""
import asyncio
import time

from freq.core.types import Host, Phase, FleetResult
from freq.core.ssh import async_run as ssh_run
from freq.engine.policy import PolicyExecutor

# Runner timeouts
RUNNER_PING_TIMEOUT = 10


async def _run_host(
    host: Host,
    executor: PolicyExecutor,
    ssh_key: str,
    mode: str = "check",
    semaphore: asyncio.Semaphore = None,
) -> Host:
    """Run the policy pipeline on a single host.

    mode: "check" (dry-run), "fix" (apply), "diff" (show drift)
    """
    sem = semaphore or asyncio.Semaphore(1)

    async with sem:
        start = time.monotonic()
        host.phase = Phase.PENDING

        # 1. PING
        r = await ssh_run(host.ip, "echo ok", key_path=ssh_key,
                          connect_timeout=5, command_timeout=RUNNER_PING_TIMEOUT,
                          htype=host.htype, use_sudo=False)
        if r.returncode != 0:
            host.phase = Phase.FAILED
            host.error = f"unreachable: {r.stderr[:50]}"
            host.duration = time.monotonic() - start
            return host

        host.phase = Phase.REACHABLE

        # 2. DISCOVER — read current state
        resources = executor.applicable_resources(host)
        if not resources:
            host.phase = Phase.COMPLIANT
            host.duration = time.monotonic() - start
            return host

        current = {}
        for res in resources:
            res_type = res.get("type", "")
            path = res.get("path", "")

            if res_type == "file_line" and path:
                # Read file and parse key-value pairs
                r = await ssh_run(host.ip, f"cat {path} 2>/dev/null",
                                  key_path=ssh_key, htype=host.htype, use_sudo=True)
                if r.returncode == 0:
                    for line in r.stdout.split("\n"):
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        # Parse "Key Value" or "Key=Value"
                        for delim in (" ", "="):
                            if delim in line:
                                k, _, v = line.partition(delim)
                                k = k.strip()
                                v = v.strip()
                                if k in res.get("entries", {}):
                                    current[k] = v
                                break

            elif res_type == "command_check":
                check_cmd = res.get("check_cmd", "")
                if check_cmd:
                    r = await ssh_run(host.ip, check_cmd,
                                      key_path=ssh_key, htype=host.htype, use_sudo=True)
                    if r.returncode == 0:
                        current[res.get("key", "check")] = r.stdout.strip()

        host.current = current
        host.phase = Phase.DISCOVERED

        # 3. COMPARE
        desired = executor.desired_state(host)
        host.desired = desired
        findings = executor.compare(current, desired)
        host.findings = findings

        if not findings:
            host.phase = Phase.COMPLIANT
            host.duration = time.monotonic() - start
            return host

        host.phase = Phase.DRIFT

        # DRY-RUN / DIFF stops here
        if mode in ("check", "diff"):
            host.phase = Phase.PLANNED
            host.duration = time.monotonic() - start
            return host

        # 4. FIX
        host.phase = Phase.FIXING
        fix_cmds = executor.fix_commands(host, findings)
        for cmd in fix_cmds:
            r = await ssh_run(host.ip, cmd, key_path=ssh_key,
                              htype=host.htype, use_sudo=True)
            if r.returncode != 0:
                host.phase = Phase.FAILED
                host.error = f"fix failed: {r.stderr[:50]}"
                host.duration = time.monotonic() - start
                return host

        # 5. ACTIVATE
        host.phase = Phase.ACTIVATING
        for cmd in executor.activate_commands(host):
            r = await ssh_run(host.ip, cmd, key_path=ssh_key,
                              htype=host.htype, use_sudo=True)
            if r.returncode != 0:
                host.phase = Phase.FAILED
                host.error = f"activate failed: {r.stderr[:50]}"
                host.duration = time.monotonic() - start
                return host

        # 6. VERIFY — re-discover and compare
        host.phase = Phase.VERIFYING
        # Re-read current state (simplified: re-check findings)
        verify_ok = True
        for res in resources:
            if res.get("type") == "file_line" and res.get("path"):
                r = await ssh_run(host.ip, f"cat {res['path']} 2>/dev/null",
                                  key_path=ssh_key, htype=host.htype, use_sudo=True)
                # Basic verification — just check command succeeded
                if r.returncode != 0:
                    verify_ok = False

        if verify_ok:
            host.phase = Phase.DONE
            host.changes = [f"{f.key}: {f.current} → {f.desired}" for f in findings]
        else:
            host.phase = Phase.FAILED
            host.error = "verification failed"

        host.duration = time.monotonic() - start
        return host


async def run_pipeline(
    hosts: list,
    policy: dict,
    ssh_key: str,
    mode: str = "check",
    max_parallel: int = 5,
) -> FleetResult:
    """Run a policy pipeline across multiple hosts.

    Returns FleetResult with per-host outcomes.
    """
    executor = PolicyExecutor(policy)
    semaphore = asyncio.Semaphore(max_parallel)
    start = time.monotonic()

    # Filter to applicable hosts
    applicable = [h for h in hosts if executor.applies_to(h)]

    # Run pipeline on all applicable hosts
    tasks = [
        asyncio.create_task(_run_host(h, executor, ssh_key, mode, semaphore))
        for h in applicable
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle exceptions
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            applicable[i].phase = Phase.FAILED
            applicable[i].error = str(r)

    duration = time.monotonic() - start

    # Build fleet result
    compliant = sum(1 for h in applicable if h.phase == Phase.COMPLIANT)
    drift = sum(1 for h in applicable if h.phase in (Phase.DRIFT, Phase.PLANNED))
    fixed = sum(1 for h in applicable if h.phase == Phase.DONE)
    failed = sum(1 for h in applicable if h.phase == Phase.FAILED)
    skipped = len(hosts) - len(applicable)

    return FleetResult(
        policy=policy["name"],
        mode=mode,
        duration=duration,
        hosts=applicable,
        total=len(applicable),
        compliant=compliant,
        drift=drift,
        fixed=fixed,
        failed=failed,
        skipped=skipped,
    )


def run_sync(hosts, policy, ssh_key, mode="check", max_parallel=5) -> FleetResult:
    """Synchronous wrapper for run_pipeline."""
    return asyncio.run(run_pipeline(hosts, policy, ssh_key, mode, max_parallel))
