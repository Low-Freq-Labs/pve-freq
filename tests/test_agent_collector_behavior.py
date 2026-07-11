"""Behavioral safety net for the dependency-free fleet metrics agent."""

import io
from types import SimpleNamespace
from unittest.mock import Mock, patch

from freq import agent_collector as collector


def _files(contents):
    def open_file(path, *args, **kwargs):
        if path not in contents:
            raise FileNotFoundError(path)
        return io.StringIO(contents[path])

    return open_file


def test_collect_cpu_parses_proc_and_fails_closed():
    proc = {
        "/proc/loadavg": "1.25 0.50 0.10 1/100 123\n",
        "/proc/stat": "cpu  100 20 30 50 0 0 0 0\ncpu0 1 2 3 4\n",
    }
    with patch("builtins.open", side_effect=_files(proc)), patch.object(collector.os, "cpu_count", return_value=8):
        data = collector.collect_cpu()

    assert data == {
        "cores": 8,
        "usage_pct": 75.0,
        "load_1m": 1.25,
        "load_5m": 0.5,
        "load_15m": 0.1,
    }
    with patch("builtins.open", side_effect=OSError):
        assert collector.collect_cpu()["cores"] == 0


def test_collect_memory_parses_proc_and_falls_back_to_free():
    meminfo = """MemTotal:       8192 kB
MemFree:        2048 kB
Cached:         1024 kB
Buffers:         512 kB
SwapTotal:      4096 kB
SwapFree:       1024 kB
Ignored line
"""
    with patch("builtins.open", return_value=io.StringIO(meminfo)):
        data = collector.collect_memory()

    assert data["total_mb"] == 8
    assert data["used_mb"] == 6
    assert data["usage_pct"] == 75.0
    assert data["cached_mb"] == 1
    assert data["buffers_mb"] == 0
    assert data["swap_total_mb"] == 4
    assert data["swap_used_mb"] == 3
    with patch("builtins.open", side_effect=ValueError):
        assert collector.collect_memory()["total_mb"] == 0


def test_collect_disk_reports_real_mounts_and_whole_devices_only():
    df = """Filesystem Size Used Avail Use% Mounted on
/dev/sda1 100G 25G 75G 25% /
tmpfs 1G 0 1G 0% /run
"""
    stats = """8 0 sda 10 0 20 0 30 0 40 0 0 0 0
8 1 sda1 1 0 2 0 3 0 4 0 0 0 0
259 0 nvme0n1 50 0 60 0 70 0 80 0 0 0 0
"""
    result = SimpleNamespace(returncode=0, stdout=df)
    with patch.object(collector.subprocess, "run", return_value=result), patch(
        "builtins.open", side_effect=_files({"/proc/diskstats": stats})
    ):
        data = collector.collect_disk()

    assert data["mounts"] == [
        {"device": "/dev/sda1", "size": "100G", "used": "25G", "avail": "75G", "usage_pct": "25%", "mount": "/"}
    ]
    assert set(data["io"]) == {"sda", "nvme0n1"}
    assert data["io"]["sda"]["writes"] == 30

    with patch.object(collector.subprocess, "run", side_effect=OSError), patch("builtins.open", side_effect=OSError):
        assert collector.collect_disk() == {"mounts": [], "io": {}}


def test_collect_network_excludes_loopback_and_parses_counters():
    netdev = """Inter-| Receive | Transmit
 face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed
lo: 1 2 0 0 0 0 0 0 3 4 0 0 0 0 0 0
eth0: 100 5 0 0 0 0 0 0 200 6 0 0 0 0 0 0
"""
    with patch("builtins.open", return_value=io.StringIO(netdev)):
        assert collector.collect_network() == {
            "eth0": {"rx_bytes": 100, "rx_packets": 5, "tx_bytes": 200, "tx_packets": 6}
        }
    with patch("builtins.open", side_effect=OSError):
        assert collector.collect_network() == {}


def test_collect_temps_combines_sysfs_and_lm_sensors():
    files = {
        "/sys/class/thermal/thermal_zone0/temp": "42500\n",
        "/sys/class/thermal/thermal_zone0/type": "x86_pkg_temp\n",
        "/sys/class/thermal/thermal_zone1/temp": "not-a-number\n",
        "/sys/class/thermal/thermal_zone1/type": "broken\n",
    }
    sensors = SimpleNamespace(
        returncode=0,
        stdout='{"coretemp": {"Package": {"temp1_input": 51.25, "label": "CPU"}}}',
    )
    with patch.object(collector.os.path, "isdir", return_value=True), patch.object(
        collector.os, "listdir", return_value=["thermal_zone1", "cooling_device0", "thermal_zone0"]
    ), patch("builtins.open", side_effect=_files(files)), patch.object(
        collector.subprocess, "run", return_value=sensors
    ):
        temps = collector.collect_temps()

    assert temps == [
        {"zone": "thermal_zone0", "type": "x86_pkg_temp", "temp_c": 42.5},
        {"zone": "coretemp", "type": "Package", "temp_c": 51.2},
    ]
    with patch.object(collector.os.path, "isdir", side_effect=OSError), patch.object(
        collector.subprocess, "run", side_effect=FileNotFoundError
    ):
        assert collector.collect_temps() == []


def test_collect_system_and_uptime_formats_are_deterministic():
    files = {
        "/proc/uptime": "90061.5 0.0\n",
        "/proc/version": "Linux version 6.8.12-test build\n",
        "/etc/os-release": 'ID=test\nPRETTY_NAME="Test Linux"\n',
    }
    docker = SimpleNamespace(returncode=0, stdout="one\ntwo\n")
    with patch("builtins.open", side_effect=_files(files)), patch.object(
        collector.os, "listdir", return_value=["1", "20", "net", "self"]
    ), patch.object(collector.subprocess, "run", return_value=docker):
        data = collector.collect_system()

    assert data["os"] == "Test Linux"
    assert data["kernel"] == "6.8.12-test"
    assert data["uptime_seconds"] == 90061
    assert data["uptime_human"] == "1d 1h 1m"
    assert data["processes"] == 2
    assert data["docker_containers"] == 2
    assert collector._format_uptime(3660) == "1h 1m"
    assert collector._format_uptime(120) == "2m"
    with patch("builtins.open", side_effect=OSError):
        assert collector.collect_system() == {"hostname": collector.HOSTNAME}


def test_collect_all_composes_each_collector():
    with patch.object(collector.time, "strftime", return_value="2026-07-11T06:00:00"), patch.multiple(
        collector,
        collect_cpu=Mock(return_value={"cpu": True}),
        collect_memory=Mock(return_value={"memory": True}),
        collect_disk=Mock(return_value={"disk": True}),
        collect_network=Mock(return_value={"network": True}),
        collect_temps=Mock(return_value=[42]),
        collect_system=Mock(return_value={"system": True}),
    ):
        data = collector.collect_all()

    assert data["timestamp"] == "2026-07-11T06:00:00"
    assert data["hostname"] == collector.HOSTNAME
    assert data["temperatures"] == [42]
    assert data["system"] == {"system": True}


def _handler(path):
    handler = collector.MetricsHandler.__new__(collector.MetricsHandler)
    handler.path = path
    handler.wfile = io.BytesIO()
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.send_error = Mock()
    return handler


def test_metrics_handler_serves_metrics_health_and_404():
    metrics = _handler("/metrics")
    with patch.object(collector, "collect_all", return_value={"ok": True}):
        metrics.do_GET()
    metrics.send_response.assert_called_once_with(200)
    assert b'"ok": true' in metrics.wfile.getvalue()
    metrics.send_header.assert_any_call("Access-Control-Allow-Origin", "*")

    health = _handler("/health")
    health.do_GET()
    health.send_response.assert_called_once_with(200)
    assert health.wfile.getvalue() == b'{"status":"ok"}'

    missing = _handler("/missing")
    missing.do_GET()
    missing.send_error.assert_called_once_with(404)
