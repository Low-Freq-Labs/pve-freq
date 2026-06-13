"""BMC resource metrics must not render as fake CPU/RAM/disk data."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text()


def test_background_health_marks_idrac_resource_metrics_unsupported():
    src = _read("freq/modules/serve.py")
    idx = src.find('bmc_metrics = {}')
    assert idx >= 0
    window = src[idx: idx + 2200]
    assert '"resource_metrics_supported": False' in window
    assert '"unsupported_metrics": ["cpu", "ram", "disk", "load"]' in window
    assert '"management_metrics": bmc_metrics' in window
    assert '"cores": None, "ram": None, "disk": None' in window


def test_cold_cache_health_marks_idrac_resource_metrics_unsupported():
    src = _read("freq/api/fleet.py")
    idx = src.find('bmc_metrics = {}')
    assert idx >= 0
    window = src[idx: idx + 1800]
    assert '"resource_metrics_supported": False' in window
    assert '"unsupported_metrics": ["cpu", "ram", "disk", "load"]' in window
    assert '"management_metrics": bmc_metrics' in window
    assert '"cores": None, "ram": None, "disk": None' in window


def test_dashboard_does_not_coerce_unsupported_metrics_to_numeric_values():
    src = _read("freq/data/web/js/app.js")
    assert "function _resourceMetricsSupported(h)" in src
    assert "function _managementMetricRows(h)" in src
    assert "function _loadBmcInventoryStats(label)" in src
    assert "function _bmcInventoryStats(inv,reachable)" in src
    assert "RACADM INVENTORY" not in src

    idx = src.find("function _silentHealthRefresh")
    assert idx >= 0
    window = src[idx: idx + 7000]
    assert "if(!_resourceMetricsSupported(h)){_replaceWithManagementMetrics(card,h);return;}" in window


def test_lab_host_cards_use_management_rows_for_unsupported_devices():
    src = _read("freq/data/web/js/app.js")
    idx = src.find("function _buildLabHostCards")
    assert idx >= 0
    window = src[idx: idx + 3200]
    assert "if(!_resourceMetricsSupported(h))" in window
    assert "c+=_managementMetricRows(h)" in window


def test_bmc_terminal_is_presented_as_service_account_shell():
    app = _read("freq/data/web/js/app.js")
    assert "RACADM INVENTORY" not in app
    assert "if(termIp)readBtns+='<button" in app

    terminal = _read("freq/api/terminal.py")
    assert 'if htype in ("pfsense", "idrac", "switch", "truenas")' in terminal
    assert "Terminal unavailable: BMC/iDRAC controllers have constrained SSH session limits" not in terminal


def test_idrac_actions_are_targeted_and_session_limited():
    hw = _read("freq/api/hw.py")
    assert "IDRAC_SESSION_LOCK" in hw
    assert "IDRAC_SESSION_GAP_SECONDS" in hw
    assert "target required for iDRAC actions" in hw
    assert "one BMC at a time" in hw
    assert '"storage": "racadm raid get status"' in hw
    assert '"firmware": "racadm getversion"' in hw
    assert '"inventory": "racadm hwinventory"' in hw
    assert "IDRAC_INVENTORY_COMMAND_TIMEOUT" in hw
    assert "def _parse_idrac_hwinventory" in hw
    assert "iDRAC SSH session limit reached" in hw

    serve = _read("freq/modules/serve.py")
    assert "def _run_idrac_subprocess" in serve
    assert "Serialize iDRAC SSH reads" in serve
    assert "with IDRAC_SESSION_LOCK" in serve


def test_idrac_hwinventory_parser_extracts_real_hardware_stats():
    from freq.api.hw import _parse_idrac_hwinventory

    out = """
[InstanceID: System.Embedded.1]
PopulatedCPUSockets = 2
MaxCPUSockets = 2
SysMemTotalSize = 90112 MB
PopulatedDIMMSlots = 5
MaxDIMMSlots = 12
PowerState = On
RollupStatus = Error
CPURollupStatus = OK
MemoryRollupStatus = OK
StorageRollupStatus = OK
FanRollupStatus = Error
PSRollupStatus = Error
ServiceTag = ABC123
-------------------------------------------------------------------
[InstanceID: CPU.Socket.1]
Model = Intel(R) Xeon(R) CPU E5-2620 v3 @ 2.40GHz
NumberOfEnabledCores = 6
NumberOfEnabledThreads = 12
PrimaryStatus = OK
-------------------------------------------------------------------
[InstanceID: CPU.Socket.2]
Model = Intel(R) Xeon(R) CPU E5-2620 v3 @ 2.40GHz
NumberOfEnabledCores = 6
NumberOfEnabledThreads = 12
PrimaryStatus = OK
-------------------------------------------------------------------
[InstanceID: Disk.Bay.0]
SizeInBytes = 6000606183424 Bytes
MediaType = HDD
RaidStatus = Non-RAID
PrimaryStatus = OK
PredictiveFailureState = Smart Alert Absent
-------------------------------------------------------------------
[InstanceID: Disk.Bay.1]
SizeInBytes = 6000606183424 Bytes
MediaType = HDD
RaidStatus = Non-RAID
PrimaryStatus = OK
PredictiveFailureState = Smart Alert Absent
-------------------------------------------------------------------
[InstanceID: RAID.Integrated.1-1]
ProductName = PERC H730P Mini
CacheSizeInMB = 2048 MB
"""
    inv = _parse_idrac_hwinventory(out)
    assert inv["cpu_sockets"] == 2
    assert inv["cpu_cores"] == 12
    assert inv["cpu_threads"] == 24
    assert inv["ram_mb"] == 90112
    assert inv["dimm_populated"] == 5
    assert inv["disk_count"] == 2
    assert inv["disk_total_bytes"] == 12001212366848
    assert inv["disk_bad_count"] == 0
    assert inv["raid_controller"] == "PERC H730P Mini"
    assert inv["raid_cache_mb"] == 2048
    assert inv["bad_health"] == ["system_rollup", "fan_status", "psu_status"]
