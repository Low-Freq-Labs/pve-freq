"""Regression tests for VM power recovery and health backoff interaction."""

import inspect

from freq.api import vm


def test_vm_power_start_clears_health_backoff():
    src = inspect.getsource(vm.handle_vm_power)
    assert "_clear_health_backoff_for_vmid" in src
    assert '"start"' in src
    assert '"reset"' in src


def test_backoff_clear_removes_circuit_breaker_state():
    src = inspect.getsource(vm._clear_health_backoff_for_vmid)
    assert "_host_backoff_until.pop" in src
    assert "_host_fail_count.pop" in src
    assert "_host_recovering.add" in src
