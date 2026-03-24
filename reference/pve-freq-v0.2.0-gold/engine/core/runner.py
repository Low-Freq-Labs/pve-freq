"""Async pipeline runner — Core 02 architecture.

Runs remediation across the fleet concurrently with bounded parallelism.
Each host goes through: ping -> discover -> compare -> (plan -> fix -> activate -> verify).

This is the winner from the 10-core experiment. 2.7s for 10 hosts.
Semaphore-bounded to prevent SSH flooding.
"""
import asyncio
import time
from engine.core.types import Host, Phase, FleetResult
from engine.core.transport import SSHTransport
from engine.core.policy import PolicyExecutor


class PipelineRunner:
    """Runs a policy across the fleet using async parallelism.

    Features:
    - Semaphore-bounded concurrency (default 5 parallel SSH)
    - Full pipeline per host: ping -> discover -> compare -> fix -> activate -> verify
    - Dry-run mode stops after compare (shows drift, no changes)
    - Each host independently succeeds or fails
    - Aggregate results for fleet-level reporting
    """

    def __init__(self, max_parallel: int = 5, dry_run: bool = False,
                 password: str = "", connect_timeout: int = 10,
                 command_timeout: int = 30):
        self.max_parallel = max_parallel
        self.dry_run = dry_run
        self.ssh = SSHTransport(
            password=password,
            connect_timeout=connect_timeout,
            command_timeout=command_timeout,
        )
        self.log: list[str] = []

    def _log(self, msg: str):
        """Internal log for debugging."""
        self.log.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

    async def _process_host(self, host: Host, executor: PolicyExecutor,
                            sem: asyncio.Semaphore):
        """Full pipeline for one host, semaphore-bounded.

        Each phase transitions the host to the next state.
        Any failure sets FAILED and returns immediately.
        """
        async with sem:
            t0 = time.time()
            self._log(f"{host.label}: starting pipeline")

            # Stage 1: Ping
            if not await self.ssh.ping(host.ip):
                host.phase = Phase.FAILED
                host.error = "unreachable"
                host.duration = time.time() - t0
                self._log(f"{host.label}: FAILED (unreachable)")
                return

            host.phase = Phase.REACHABLE
            self._log(f"{host.label}: reachable")

            # Stage 2: Discover
            try:
                host.current = await executor.discover(host, self.ssh)
                if host.current.get("_skip"):
                    host.phase = Phase.COMPLIANT
                    host.duration = time.time() - t0
                    self._log(f"{host.label}: skipped (no applicable resources)")
                    return
                if host.current.get("_error"):
                    host.phase = Phase.FAILED
                    host.error = host.current["_error"]
                    host.duration = time.time() - t0
                    self._log(f"{host.label}: FAILED ({host.error})")
                    return
                host.phase = Phase.DISCOVERED
                self._log(f"{host.label}: discovered ({len(host.current)} keys)")
            except Exception as e:
                host.phase = Phase.FAILED
                host.error = f"discover: {e}"
                host.duration = time.time() - t0
                self._log(f"{host.label}: FAILED (discover exception: {e})")
                return

            # Stage 3: Compare
            host.desired = executor.desired_state(host)
            host.findings = executor.compare(host)

            if not host.findings:
                host.phase = Phase.COMPLIANT
                host.duration = time.time() - t0
                self._log(f"{host.label}: compliant")
                return

            host.phase = Phase.DRIFT
            self._log(f"{host.label}: drift detected ({len(host.findings)} findings)")

            # Dry run stops here
            if self.dry_run:
                host.phase = Phase.PLANNED
                host.duration = time.time() - t0
                self._log(f"{host.label}: planned (dry run)")
                return

            # Stage 4: Fix
            host.phase = Phase.FIXING
            try:
                for finding in host.findings:
                    ok = await executor.fix(host, finding, self.ssh)
                    if ok:
                        host.changes.append(
                            f"{finding.key}: {finding.current} -> {finding.desired}"
                        )
                        self._log(f"{host.label}: fixed {finding.key}")
                    else:
                        host.phase = Phase.FAILED
                        host.error = f"fix failed: {finding.key}"
                        host.duration = time.time() - t0
                        self._log(f"{host.label}: FAILED (fix: {finding.key})")
                        return
            except Exception as e:
                host.phase = Phase.FAILED
                host.error = f"fix: {e}"
                host.duration = time.time() - t0
                self._log(f"{host.label}: FAILED (fix exception: {e})")
                return

            # Stage 5: Activate
            host.phase = Phase.ACTIVATING
            try:
                if not await executor.activate(host, self.ssh):
                    host.phase = Phase.FAILED
                    host.error = "activation failed"
                    host.duration = time.time() - t0
                    self._log(f"{host.label}: FAILED (activation)")
                    return
                self._log(f"{host.label}: activated")
            except Exception as e:
                host.phase = Phase.FAILED
                host.error = f"activate: {e}"
                host.duration = time.time() - t0
                self._log(f"{host.label}: FAILED (activate exception: {e})")
                return

            # Stage 6: Verify
            host.phase = Phase.VERIFYING
            try:
                if await executor.verify(host, self.ssh):
                    host.phase = Phase.DONE
                    self._log(f"{host.label}: DONE (verified)")
                else:
                    host.phase = Phase.FAILED
                    host.error = "verification failed"
                    self._log(f"{host.label}: FAILED (verification)")
            except Exception as e:
                host.phase = Phase.FAILED
                host.error = f"verify: {e}"
                self._log(f"{host.label}: FAILED (verify exception: {e})")

            host.duration = time.time() - t0

    async def run(self, hosts: list[Host], executor: PolicyExecutor) -> FleetResult:
        """Run policy across all hosts concurrently.

        Creates a semaphore to bound parallelism, then launches all
        hosts simultaneously. Each host independently succeeds or fails.
        Returns aggregate FleetResult.
        """
        sem = asyncio.Semaphore(self.max_parallel)
        t0 = time.time()

        self._log(f"Starting {executor.policy.name} across {len(hosts)} hosts "
                  f"(max_parallel={self.max_parallel}, dry_run={self.dry_run})")

        await asyncio.gather(
            *[self._process_host(h, executor, sem) for h in hosts]
        )

        # Build result
        result = FleetResult(
            policy=executor.policy.name,
            mode="fix" if not self.dry_run else "check",
            duration=time.time() - t0,
            hosts=hosts,
            total=len(hosts),
            compliant=sum(1 for h in hosts if h.phase == Phase.COMPLIANT),
            drift=sum(1 for h in hosts if h.phase in (Phase.DRIFT, Phase.PLANNED)),
            fixed=sum(1 for h in hosts if h.phase == Phase.DONE),
            failed=sum(1 for h in hosts if h.phase == Phase.FAILED),
            skipped=sum(1 for h in hosts if h.phase == Phase.COMPLIANT),
        )

        self._log(f"Complete: {result.compliant} compliant, {result.drift} drift, "
                  f"{result.fixed} fixed, {result.failed} failed in {result.duration:.1f}s")

        return result
