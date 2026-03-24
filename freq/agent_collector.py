#!/usr/bin/env python3
"""FREQ Metrics Collector — lightweight agent for fleet monitoring.

Deploy to any Linux host. Collects system metrics and serves JSON on port 9990.
Zero dependencies — pure Python stdlib. Reads /proc and /sys directly.

Deploy:  freq deploy-agent <host>
Query:   curl http://<host>:9990/metrics
Service: systemctl status freq-agent

Metrics collected:
  - CPU: per-core usage, load average
  - Memory: total, used, available, cached, buffers
  - Disk: usage per mount, I/O stats
  - Network: bytes in/out per interface
  - System: uptime, hostname, kernel, temps, process count
  - Docker: container count (if available)
  - Optional: fan speeds (lm-sensors), SMART (smartmontools)
"""
import json
import os
import socket
import subprocess
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("FREQ_AGENT_PORT", 9990))
HOSTNAME = socket.gethostname()


def collect_cpu():
    """CPU usage from /proc/stat."""
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            load_1, load_5, load_15 = parts[0], parts[1], parts[2]

        cores = os.cpu_count() or 1

        # Per-CPU usage from /proc/stat
        with open("/proc/stat") as f:
            lines = f.readlines()

        cpu_line = lines[0].split()
        user, nice, system, idle = int(cpu_line[1]), int(cpu_line[2]), int(cpu_line[3]), int(cpu_line[4])
        total = user + nice + system + idle
        usage = round((1 - idle / total) * 100, 1) if total > 0 else 0

        return {
            "cores": cores,
            "usage_pct": usage,
            "load_1m": float(load_1),
            "load_5m": float(load_5),
            "load_15m": float(load_15),
        }
    except Exception:
        return {"cores": 0, "usage_pct": 0, "load_1m": 0, "load_5m": 0, "load_15m": 0}


def collect_memory():
    """Memory from /proc/meminfo."""
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = int(parts[1].strip().split()[0])  # Value in kB
                    info[key] = val

        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", info.get("MemFree", 0))
        cached = info.get("Cached", 0)
        buffers = info.get("Buffers", 0)
        used = total - available
        swap_total = info.get("SwapTotal", 0)
        swap_free = info.get("SwapFree", 0)

        return {
            "total_mb": total // 1024,
            "used_mb": used // 1024,
            "available_mb": available // 1024,
            "cached_mb": cached // 1024,
            "buffers_mb": buffers // 1024,
            "usage_pct": round(used / total * 100, 1) if total > 0 else 0,
            "swap_total_mb": swap_total // 1024,
            "swap_used_mb": (swap_total - swap_free) // 1024,
        }
    except Exception:
        return {"total_mb": 0, "used_mb": 0, "available_mb": 0, "usage_pct": 0}


def collect_disk():
    """Disk usage and I/O stats."""
    mounts = []
    try:
        r = subprocess.run(["df", "-h", "--output=source,size,used,avail,pcent,target"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 6 and parts[0].startswith("/"):
                    mounts.append({
                        "device": parts[0],
                        "size": parts[1],
                        "used": parts[2],
                        "avail": parts[3],
                        "usage_pct": parts[4],
                        "mount": parts[5],
                    })
    except Exception:
        pass

    # I/O stats from /proc/diskstats
    io = {}
    try:
        with open("/proc/diskstats") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14:
                    name = parts[2]
                    if name.startswith("sd") or name.startswith("nvme") or name.startswith("vd"):
                        if not any(c.isdigit() for c in name[-1:]) or name.startswith("nvme"):
                            io[name] = {
                                "reads": int(parts[3]),
                                "writes": int(parts[7]),
                                "read_sectors": int(parts[5]),
                                "write_sectors": int(parts[9]),
                            }
    except Exception:
        pass

    return {"mounts": mounts, "io": io}


def collect_network():
    """Network I/O from /proc/net/dev."""
    interfaces = {}
    try:
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                parts = line.split()
                if len(parts) >= 10:
                    name = parts[0].rstrip(":")
                    if name != "lo":
                        interfaces[name] = {
                            "rx_bytes": int(parts[1]),
                            "rx_packets": int(parts[2]),
                            "tx_bytes": int(parts[9]),
                            "tx_packets": int(parts[10]),
                        }
    except Exception:
        pass
    return interfaces


def collect_temps():
    """Temperature from /sys/class/thermal/."""
    temps = []
    try:
        thermal_dir = "/sys/class/thermal"
        if os.path.isdir(thermal_dir):
            for zone in sorted(os.listdir(thermal_dir)):
                if zone.startswith("thermal_zone"):
                    temp_file = os.path.join(thermal_dir, zone, "temp")
                    type_file = os.path.join(thermal_dir, zone, "type")
                    try:
                        with open(temp_file) as f:
                            temp_mc = int(f.read().strip())
                        with open(type_file) as f:
                            sensor_type = f.read().strip()
                        temps.append({
                            "zone": zone,
                            "type": sensor_type,
                            "temp_c": round(temp_mc / 1000, 1),
                        })
                    except (OSError, ValueError):
                        pass
    except Exception:
        pass

    # Also try lm-sensors if available
    try:
        r = subprocess.run(["sensors", "-j"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            sensors_data = json.loads(r.stdout)
            for chip, data in sensors_data.items():
                if isinstance(data, dict):
                    for key, val in data.items():
                        if isinstance(val, dict):
                            for metric, reading in val.items():
                                if "input" in metric and isinstance(reading, (int, float)):
                                    temps.append({
                                        "zone": chip,
                                        "type": key,
                                        "temp_c": round(reading, 1),
                                    })
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        pass

    return temps


def collect_system():
    """System info."""
    try:
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])

        kernel = ""
        try:
            with open("/proc/version") as f:
                kernel = f.read().split()[2]
        except Exception:
            pass

        os_name = ""
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        os_name = line.split("=", 1)[1].strip().strip('"')
                        break
        except Exception:
            pass

        # Process count
        proc_count = 0
        try:
            proc_count = len([d for d in os.listdir("/proc") if d.isdigit()])
        except Exception:
            pass

        # Docker container count
        docker_count = 0
        try:
            r = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                docker_count = len(r.stdout.strip().split("\n")) if r.stdout.strip() else 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return {
            "hostname": HOSTNAME,
            "os": os_name,
            "kernel": kernel,
            "uptime_seconds": int(uptime_seconds),
            "uptime_human": _format_uptime(uptime_seconds),
            "processes": proc_count,
            "docker_containers": docker_count,
        }
    except Exception:
        return {"hostname": HOSTNAME}


def _format_uptime(seconds):
    """Format uptime in human-readable form."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def collect_all():
    """Collect all metrics."""
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hostname": HOSTNAME,
        "cpu": collect_cpu(),
        "memory": collect_memory(),
        "disk": collect_disk(),
        "network": collect_network(),
        "temperatures": collect_temps(),
        "system": collect_system(),
    }


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler for metrics endpoint."""

    def log_message(self, format, *args):
        pass  # Suppress logging

    def do_GET(self):
        if self.path == "/metrics" or self.path == "/":
            data = collect_all()
            body = json.dumps(data, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_error(404)


def main():
    """Start the metrics server."""
    print(f"FREQ Agent Collector starting on port {PORT}...")
    print(f"Hostname: {HOSTNAME}")
    print(f"Metrics: http://0.0.0.0:{PORT}/metrics")
    server = HTTPServer(("0.0.0.0", PORT), MetricsHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
        server.server_close()


if __name__ == "__main__":
    main()
