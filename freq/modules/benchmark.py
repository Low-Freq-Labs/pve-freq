"""System benchmarking — CPU, memory, disk, and network speed tests via SSH.

All benchmarks run on remote hosts via SSH. Tools (sysbench, fio, iperf3)
must be installed on target hosts. Missing tools are reported, not fatal.

Replaces: Manual SSH-and-parse benchmarking scripts, ad-hoc iperf3 sessions

Architecture:
    - Every benchmark runs remotely via freq.core.ssh.run
    - Each bench_* function returns a structured dict with results + metadata
    - check_tools() probes which benchmark tools are available on a host
    - Results include raw output for debugging, parsed values for display
    - Network benchmarks use iperf3 client/server model between two hosts

Design decisions:
    - SSH, not agents. No software to deploy beyond standard benchmark tools.
    - sysbench for CPU/memory (most common, available via apt/yum).
    - fio for disk I/O (industry standard, JSON output for reliable parsing).
    - iperf3 for network (de facto standard, daemon mode for server side).
    - Each function is standalone — call one or all, no ordering dependency.
    - Timeouts are generous (120s) because benchmarks are inherently slow.
"""

import json
import re
import time

from freq.core.ssh import run as ssh_single


# -- Tool availability check -------------------------------------------------


def check_tools(host_ip: str, cfg=None) -> dict:
    """Check which benchmark tools are installed on a remote host.

    Probes for sysbench, fio, and iperf3 via `which`. Returns a dict
    mapping tool names to their install paths (or None if missing).

    Args:
        host_ip: IP address of the target host.
        cfg: FreqConfig (passed to SSH for auth/key resolution).

    Returns:
        Dict like {"sysbench": "/usr/bin/sysbench", "fio": None, "iperf3": "/usr/bin/iperf3"}
    """
    tools = ["sysbench", "fio", "iperf3"]
    result = ssh_single(
        host=host_ip,
        command="which sysbench fio iperf3 2>/dev/null; true",
        command_timeout=10,
        cfg=cfg,
    )

    found = {}
    paths = result.stdout.strip().splitlines() if result.returncode == 0 else []
    for tool in tools:
        match = next((p for p in paths if tool in p), None)
        found[tool] = match

    return found


# -- CPU benchmark -----------------------------------------------------------


def bench_cpu(host_ip: str, cfg=None, threads: int = 0, duration: int = 10) -> dict:
    """Run a CPU benchmark via sysbench on a remote host.

    Uses sysbench cpu test with configurable thread count and duration.
    Parses "events per second" from output as the primary metric.

    Args:
        host_ip: IP address of the target host.
        cfg: FreqConfig (passed to SSH for auth/key resolution).
        threads: Number of threads (0 = auto-detect via nproc).
        duration: Test duration in seconds (default: 10).

    Returns:
        Dict with keys: ok, events_per_second, threads, duration_sec,
        raw_output, error.
    """
    # Use nproc for auto thread count
    thread_arg = f"--threads={threads}" if threads > 0 else "--threads=$(nproc)"
    cmd = f"sysbench cpu {thread_arg} --time={duration} run 2>&1"

    result = ssh_single(
        host=host_ip,
        command=cmd,
        command_timeout=duration + 30,
        cfg=cfg,
    )

    if result.returncode != 0:
        return {
            "ok": False,
            "events_per_second": 0,
            "threads": threads,
            "duration_sec": duration,
            "raw_output": result.stdout,
            "error": result.stderr or f"sysbench exited {result.returncode}",
        }

    # Parse "events per second" from sysbench output
    # Example line: "    events per second:  1234.56"
    eps = 0.0
    eps_match = re.search(r"events per second:\s+([\d.]+)", result.stdout)
    if eps_match:
        eps = float(eps_match.group(1))

    # Parse actual thread count used
    actual_threads = threads
    threads_match = re.search(r"Number of threads:\s+(\d+)", result.stdout)
    if threads_match:
        actual_threads = int(threads_match.group(1))

    return {
        "ok": True,
        "events_per_second": eps,
        "threads": actual_threads,
        "duration_sec": duration,
        "raw_output": result.stdout,
        "error": "",
    }


# -- Memory benchmark --------------------------------------------------------


def bench_memory(host_ip: str, cfg=None, total_size: str = "4G") -> dict:
    """Run a memory bandwidth benchmark via sysbench on a remote host.

    Uses sysbench memory test to measure memory throughput.
    Parses "MiB/sec" transferred from output as the primary metric.

    Args:
        host_ip: IP address of the target host.
        cfg: FreqConfig (passed to SSH for auth/key resolution).
        total_size: Total data to transfer (default: "4G").

    Returns:
        Dict with keys: ok, mib_per_sec, total_size, raw_output, error.
    """
    cmd = f"sysbench memory --memory-total-size={total_size} run 2>&1"

    result = ssh_single(
        host=host_ip,
        command=cmd,
        command_timeout=120,
        cfg=cfg,
    )

    if result.returncode != 0:
        return {
            "ok": False,
            "mib_per_sec": 0,
            "total_size": total_size,
            "raw_output": result.stdout,
            "error": result.stderr or f"sysbench exited {result.returncode}",
        }

    # Parse MiB/sec from sysbench output
    # Example: "4096.00 MiB transferred (12345.67 MiB/sec)"
    mib = 0.0
    mib_match = re.search(r"([\d.]+)\s+MiB/sec", result.stdout)
    if mib_match:
        mib = float(mib_match.group(1))

    return {
        "ok": True,
        "mib_per_sec": mib,
        "total_size": total_size,
        "raw_output": result.stdout,
        "error": "",
    }


# -- Disk I/O benchmark ------------------------------------------------------


def bench_disk(host_ip: str, cfg=None, size: str = "256M", runtime: int = 10) -> dict:
    """Run a random-read disk I/O benchmark via fio on a remote host.

    Uses fio with 4K random reads to measure IOPS. Output is JSON for
    reliable parsing. The test file is created in /tmp and cleaned up.

    Args:
        host_ip: IP address of the target host.
        cfg: FreqConfig (passed to SSH for auth/key resolution).
        size: Test file size (default: "256M").
        runtime: Test duration in seconds (default: 10).

    Returns:
        Dict with keys: ok, iops, bw_kib, latency_avg_us, raw_output, error.
    """
    cmd = (
        f"fio --name=freq_bench --filename=/tmp/freq_bench_test "
        f"--size={size} --rw=randread --bs=4k --direct=1 "
        f"--runtime={runtime} --time_based "
        f"--output-format=json 2>/dev/null; "
        f"rm -f /tmp/freq_bench_test"
    )

    result = ssh_single(
        host=host_ip,
        command=cmd,
        command_timeout=runtime + 60,
        cfg=cfg,
    )

    if result.returncode != 0:
        return {
            "ok": False,
            "iops": 0,
            "bw_kib": 0,
            "latency_avg_us": 0,
            "raw_output": result.stdout[:2000],
            "error": result.stderr or f"fio exited {result.returncode}",
        }

    # Parse JSON output from fio
    iops = 0.0
    bw_kib = 0.0
    lat_avg = 0.0

    try:
        fio_data = json.loads(result.stdout)
        job = fio_data.get("jobs", [{}])[0]
        read_stats = job.get("read", {})
        iops = read_stats.get("iops", 0)
        bw_kib = read_stats.get("bw", 0)  # KiB/s
        lat_ns = read_stats.get("lat_ns", read_stats.get("clat_ns", {}))
        lat_avg = lat_ns.get("mean", 0) / 1000  # ns → us
    except (json.JSONDecodeError, IndexError, KeyError, TypeError):
        # Fall back to regex parsing if JSON fails
        iops_match = re.search(r'"iops"\s*:\s*([\d.]+)', result.stdout)
        if iops_match:
            iops = float(iops_match.group(1))

    return {
        "ok": True,
        "iops": round(iops, 1),
        "bw_kib": round(bw_kib, 1),
        "latency_avg_us": round(lat_avg, 2),
        "raw_output": result.stdout[:2000],
        "error": "",
    }


# -- Network benchmark -------------------------------------------------------


def bench_network(source_ip: str, target_ip: str, cfg=None, duration: int = 10) -> dict:
    """Run a network throughput benchmark between two hosts via iperf3.

    Starts an iperf3 server on the target host (daemon mode, single-run),
    then runs the iperf3 client from the source host. The server exits
    automatically after one test.

    Args:
        source_ip: IP of the client host (sends traffic).
        target_ip: IP of the server host (receives traffic).
        cfg: FreqConfig (passed to SSH for auth/key resolution).
        duration: Test duration in seconds (default: 10).

    Returns:
        Dict with keys: ok, bits_per_second, mbps, duration_sec,
        source, target, raw_output, error.
    """
    # Kill any stale iperf3 server, then start fresh in daemon mode (-D)
    # -1 = one-shot (exits after single client connection)
    server_cmd = "pkill -f 'iperf3 -s' 2>/dev/null; sleep 0.5; iperf3 -s -1 -D"
    server_result = ssh_single(
        host=target_ip,
        command=server_cmd,
        command_timeout=10,
        cfg=cfg,
    )

    if server_result.returncode != 0:
        return {
            "ok": False,
            "bits_per_second": 0,
            "mbps": 0,
            "duration_sec": duration,
            "source": source_ip,
            "target": target_ip,
            "raw_output": "",
            "error": f"Failed to start iperf3 server on {target_ip}: {server_result.stderr}",
        }

    # Brief pause to let server bind
    # (the SSH command already includes sleep 0.5 after pkill)

    # Run client from source host
    client_cmd = f"iperf3 -c {target_ip} -t {duration} --json 2>&1"
    client_result = ssh_single(
        host=source_ip,
        command=client_cmd,
        command_timeout=duration + 30,
        cfg=cfg,
    )

    if client_result.returncode != 0:
        # Clean up: kill server if client failed
        ssh_single(host=target_ip, command="pkill -f 'iperf3 -s' 2>/dev/null", command_timeout=5, cfg=cfg)
        return {
            "ok": False,
            "bits_per_second": 0,
            "mbps": 0,
            "duration_sec": duration,
            "source": source_ip,
            "target": target_ip,
            "raw_output": client_result.stdout[:2000],
            "error": client_result.stderr or f"iperf3 client exited {client_result.returncode}",
        }

    # Parse JSON output from iperf3 client
    bps = 0.0
    try:
        iperf_data = json.loads(client_result.stdout)
        end = iperf_data.get("end", {})
        # Sum of all streams
        sum_sent = end.get("sum_sent", {})
        sum_received = end.get("sum_received", {})
        # Use received throughput (more accurate — what actually arrived)
        bps = sum_received.get("bits_per_second", sum_sent.get("bits_per_second", 0))
    except (json.JSONDecodeError, KeyError, TypeError):
        # Fallback regex
        bps_match = re.search(r'"bits_per_second"\s*:\s*([\d.eE+]+)', client_result.stdout)
        if bps_match:
            bps = float(bps_match.group(1))

    mbps = round(bps / 1_000_000, 2)

    return {
        "ok": True,
        "bits_per_second": bps,
        "mbps": mbps,
        "duration_sec": duration,
        "source": source_ip,
        "target": target_ip,
        "raw_output": client_result.stdout[:2000],
        "error": "",
    }


# -- Full benchmark suite ----------------------------------------------------


def bench_all(host_ip: str, cfg=None) -> dict:
    """Run all local benchmarks (CPU, memory, disk) on a single host.

    Network benchmarks require two hosts and must be called separately
    via bench_network().

    Args:
        host_ip: IP address of the target host.
        cfg: FreqConfig (passed to SSH for auth/key resolution).

    Returns:
        Dict with keys: host, timestamp, tools, cpu, memory, disk.
    """
    tools = check_tools(host_ip, cfg=cfg)
    results = {
        "host": host_ip,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tools": tools,
        "cpu": None,
        "memory": None,
        "disk": None,
    }

    if tools.get("sysbench"):
        results["cpu"] = bench_cpu(host_ip, cfg=cfg)
        results["memory"] = bench_memory(host_ip, cfg=cfg)

    if tools.get("fio"):
        results["disk"] = bench_disk(host_ip, cfg=cfg)

    return results
