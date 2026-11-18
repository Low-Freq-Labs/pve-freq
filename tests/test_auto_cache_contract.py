"""Automation API cache-directory behavior and startup-order contract."""

import importlib
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.case_matrix import run_case_matrix  # noqa: E402

from freq.api import auto  # noqa: E402
from freq.modules import serve  # noqa: E402


class TestAutomationCacheContract(unittest.TestCase):
    def _cfg(self):
        return SimpleNamespace(
            conf_dir="/srv/freq/conf",
            data_dir="/srv/freq/data",
        )

    def _case_runtime_init_before_route_import_uses_config_cache_dir(self):
        from freq.jarvis import rules

        cfg = self._cfg()
        expected_cache_dir = os.path.join(cfg.data_dir, "cache")
        handler = object()
        history = [{"rule": "cpu-high", "host": "pve1"}]
        original_cache_dir = serve.CACHE_DIR

        try:
            with (
                mock.patch.object(serve, "load_config", return_value=cfg),
                mock.patch("freq.core.config.load_config", return_value=cfg),
            ):
                serve._init_cache_dir()
                importlib.reload(auto)

            with (
                mock.patch.object(auto, "load_config", return_value=cfg),
                mock.patch.object(rules, "load_alert_history", return_value=history) as load_history,
                mock.patch.object(auto, "json_response") as respond,
            ):
                auto.handle_rules_history(handler)

            load_history.assert_called_once_with(expected_cache_dir)
            respond.assert_called_once_with(handler, {"alerts": history, "count": 1})
        finally:
            serve.CACHE_DIR = original_cache_dir
            importlib.reload(auto)

    def _case_rules_use_exact_cache_dir_and_annotate_active_hosts(self):
        from freq.jarvis import rules

        cfg = self._cfg()
        expected_cache_dir = os.path.join(cfg.data_dir, "cache")
        handler = object()
        rule = SimpleNamespace(name="cpu-high")
        state = {
            "cpu-high:pve1": {"active": True},
            "cpu-high:pve2": {"active": True},
            "disk-high:pve3": {"active": True},
        }
        rule_dicts = [{"name": "cpu-high", "enabled": True}]

        with (
            mock.patch.object(auto, "load_config", return_value=cfg),
            mock.patch.object(rules, "load_rules", return_value=[rule]) as load_rules,
            mock.patch.object(rules, "load_rule_state", return_value=state) as load_state,
            mock.patch.object(rules, "rules_to_dicts", return_value=rule_dicts),
            mock.patch.object(auto, "json_response") as respond,
        ):
            auto.handle_rules(handler)

        load_rules.assert_called_once_with(cfg.conf_dir)
        load_state.assert_called_once_with(expected_cache_dir)
        respond.assert_called_once_with(
            handler,
            {
                "rules": [
                    {
                        "name": "cpu-high",
                        "enabled": True,
                        "active_hosts": ["pve1", "pve2"],
                    }
                ],
                "count": 1,
            },
        )


AUTOMATION_CACHE_CASES = (
    "_case_runtime_init_before_route_import_uses_config_cache_dir",
    "_case_rules_use_exact_cache_dir_and_annotate_active_hosts",
)


class TestAutomationCacheMatrix(unittest.TestCase):
    def test_automation_cache_matrix(self):
        run_case_matrix(self, TestAutomationCacheContract, AUTOMATION_CACHE_CASES)


if __name__ == "__main__":
    unittest.main()
