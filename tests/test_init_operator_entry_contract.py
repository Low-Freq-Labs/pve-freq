"""Operator-facing contracts at the public ``freq init`` entry boundary."""

import types
import unittest
from unittest import mock


class TestInitOperatorEntryContract(unittest.TestCase):
    def test_nonroot_init_dispatch_does_not_initialize_writable_runtime_state(self):
        from freq import cli

        cfg = types.SimpleNamespace(
            conf_dir="/opt/pve-freq/config",
            log_file="/opt/pve-freq/data/freq.log",
            ascii_mode=True,
            build="test",
            debug=False,
        )
        handler = mock.Mock(return_value=1)
        args = types.SimpleNamespace(
            domain="init",
            subcmd="",
            dry_run=False,
            reset=True,
            debug=False,
            yes=True,
            func=handler,
        )
        parser = mock.Mock()
        parser.parse_args.return_value = args

        with mock.patch.object(cli, "load_config", return_value=cfg), mock.patch.object(
            cli, "_build_parser", return_value=parser
        ), mock.patch("freq.core.plugins.discover_plugins", return_value=[]), mock.patch.object(
            cli.os, "geteuid", return_value=1000
        ), mock.patch.object(cli.logger, "init") as init_log, mock.patch.object(
            cli.logger, "init_perf"
        ) as init_perf, mock.patch("freq.core.audit.init") as init_audit, mock.patch.object(
            cli, "load_pack", return_value=None
        ):
            self.assertEqual(cli.main(["init", "--reset", "--yes"]), 1)

        init_log.assert_not_called()
        init_perf.assert_not_called()
        init_audit.assert_not_called()
        handler.assert_called_once_with(cfg, None, args)

    def test_nonroot_reset_reports_privilege_requirement_without_mutating(self):
        from freq.modules import init_cmd

        cfg = types.SimpleNamespace(conf_dir="/opt/pve-freq/config")
        args = types.SimpleNamespace(
            check=False,
            reset=True,
            dry_run=False,
            uninstall=False,
            fix=False,
            headless=False,
            yes=True,
        )
        lines = []
        colors = types.SimpleNamespace(RED="", RESET="", DIM="")
        with mock.patch.object(init_cmd.os, "geteuid", return_value=1000), mock.patch.object(
            init_cmd, "_init_reset", side_effect=AssertionError("reset mutated as non-root")
        ), mock.patch.object(init_cmd, "fmt") as output:
            output.C = colors
            output.line.side_effect = lines.append
            self.assertEqual(init_cmd.cmd_init(cfg, None, args), 1)

        rendered = "\n".join(lines)
        self.assertIn("freq init --reset must be run as root", rendered)
        self.assertIn("sudo freq init --reset", rendered)


if __name__ == "__main__":
    unittest.main()
