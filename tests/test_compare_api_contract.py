"""Regression tests for dashboard compare API compatibility."""

import inspect

from freq.api import fleet
from freq.modules import compare


def test_compare_accepts_dashboard_parameter_names():
    src = inspect.getsource(fleet.handle_compare)
    assert "host_a" in src
    assert "host_b" in src


def test_compare_ssh_uses_runtime_config_identity():
    src = inspect.getsource(compare._gather_host_info)
    assert "cfg=cfg" in src
