"""Tests for event network lifecycle — template CRUD, plan, CLI registration.

Covers: Template creation/loading/listing, TOML serialization,
        CLI subcommand registration, module imports.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Mock Config
# ---------------------------------------------------------------------------

@dataclass
class MockHost:
    ip: str
    label: str
    htype: str
    groups: str = ""


class MockConfig:
    def __init__(self, tmpdir):
        self.conf_dir = tmpdir
        self.hosts = [
            MockHost("10.25.255.5", "switch", "switch"),
            MockHost("10.25.255.26", "pve01", "pve"),
        ]
        self.switch_ip = "10.25.255.5"
        self.ssh_key_path = "/tmp/test_key"
        self.ssh_rsa_key_path = "/tmp/test_rsa"
        self.ssh_connect_timeout = 5


# ---------------------------------------------------------------------------
# Template Storage Tests
# ---------------------------------------------------------------------------

class TestTemplateStorage(unittest.TestCase):
    """Test event template CRUD operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = MockConfig(self.tmpdir)
        from freq.modules.event_network import (
            _save_template, _load_template, _list_templates, _templates_dir,
        )
        self.save = _save_template
        self.load = _load_template
        self.list = _list_templates
        self.tdir = _templates_dir

    def test_templates_dir_created(self):
        path = self.tdir(self.cfg)
        self.assertTrue(os.path.isdir(path))

    def test_save_and_load(self):
        data = {
            "event": {"name": "superbowl", "status": "draft", "created": "2026-04-01"},
            "switches": [{"label": "switch", "ip": "10.25.255.5", "role": "access"}],
            "vlans": [{"name": "cameras", "id": 50, "subnet": "10.25.50.0/24"}],
        }
        self.save(self.cfg, "superbowl", data)
        loaded = self.load(self.cfg, "superbowl")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["event"]["name"], "superbowl")

    def test_load_nonexistent(self):
        result = self.load(self.cfg, "doesnt-exist")
        self.assertIsNone(result)

    def test_list_templates(self):
        self.save(self.cfg, "event-a", {"event": {"name": "a"}})
        self.save(self.cfg, "event-b", {"event": {"name": "b"}})
        templates = self.list(self.cfg)
        self.assertEqual(len(templates), 2)
        self.assertIn("event-a", templates)
        self.assertIn("event-b", templates)

    def test_list_empty(self):
        templates = self.list(self.cfg)
        self.assertEqual(templates, [])

    def test_template_file_is_toml(self):
        self.save(self.cfg, "test", {"event": {"name": "test"}})
        filepath = os.path.join(self.tdir(self.cfg), "test.toml")
        self.assertTrue(os.path.exists(filepath))
        with open(filepath) as f:
            content = f.read()
        self.assertIn("[event]", content)
        self.assertIn('name = "test"', content)


class TestTomlSerialization(unittest.TestCase):
    """Test _toml_val serializer."""

    def setUp(self):
        from freq.modules.event_network import _toml_val
        self.val = _toml_val

    def test_string(self):
        self.assertEqual(self.val("hello"), '"hello"')

    def test_bool_true(self):
        self.assertEqual(self.val(True), "true")

    def test_bool_false(self):
        self.assertEqual(self.val(False), "false")

    def test_int(self):
        self.assertEqual(self.val(42), "42")

    def test_list(self):
        self.assertEqual(self.val([1, 2, 3]), "[1, 2, 3]")

    def test_list_of_strings(self):
        result = self.val(["a", "b"])
        self.assertIn('"a"', result)
        self.assertIn('"b"', result)


# ---------------------------------------------------------------------------
# Archive Tests
# ---------------------------------------------------------------------------

class TestArchiveDir(unittest.TestCase):
    """Test archive directory creation."""

    def test_archives_dir_created(self):
        tmpdir = tempfile.mkdtemp()
        cfg = MockConfig(tmpdir)
        from freq.modules.event_network import _archives_dir
        path = _archives_dir(cfg)
        self.assertTrue(os.path.isdir(path))


# ---------------------------------------------------------------------------
# CLI Registration Tests
# ---------------------------------------------------------------------------

class TestCLIEventRegistration(unittest.TestCase):
    """Test that event subcommands are registered."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _parse(self, args_str):
        return self.parser.parse_args(args_str.split())

    def test_event_domain_registered(self):
        """Event domain exists in parser."""
        import argparse
        registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertIn("event", registered)

    def test_event_create(self):
        args = self._parse("event create superbowl")
        self.assertTrue(hasattr(args, "func"))
        self.assertEqual(args.name, "superbowl")

    def test_event_list(self):
        args = self._parse("event list")
        self.assertTrue(hasattr(args, "func"))

    def test_event_show(self):
        args = self._parse("event show superbowl")
        self.assertEqual(args.name, "superbowl")

    def test_event_plan(self):
        args = self._parse("event plan superbowl")
        self.assertEqual(args.name, "superbowl")

    def test_event_deploy(self):
        args = self._parse("event deploy superbowl")
        self.assertTrue(hasattr(args, "func"))

    def test_event_verify(self):
        args = self._parse("event verify superbowl")
        self.assertTrue(hasattr(args, "func"))

    def test_event_wipe(self):
        args = self._parse("event wipe superbowl --confirm")
        self.assertTrue(args.confirm)

    def test_event_wipe_no_confirm(self):
        args = self._parse("event wipe superbowl")
        self.assertFalse(args.confirm)

    def test_event_archive(self):
        args = self._parse("event archive superbowl")
        self.assertTrue(hasattr(args, "func"))

    def test_event_delete(self):
        args = self._parse("event delete superbowl --yes")
        self.assertTrue(args.yes)


# ---------------------------------------------------------------------------
# Command Logic Tests (no SSH)
# ---------------------------------------------------------------------------

class TestEventCreateCommand(unittest.TestCase):
    """Test cmd_event_create with mock config."""

    def test_create_event(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import MagicMock

        tmpdir = tempfile.mkdtemp()
        cfg = MockConfig(tmpdir)

        # Create vlans.toml so create can pull VLANs
        vlans_toml = os.path.join(tmpdir, "vlans.toml")
        with open(vlans_toml, "w") as f:
            f.write('[vlan.cameras]\nid = 50\nname = "CAMERAS"\nsubnet = "10.25.50.0/24"\n')

        from freq.modules.event_network import cmd_event_create
        args = MagicMock()
        args.name = "test-event"

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_event_create(cfg, None, args)

        self.assertEqual(rc, 0)
        # Verify template was created
        from freq.modules.event_network import _load_template
        tmpl = _load_template(cfg, "test-event")
        self.assertIsNotNone(tmpl)
        self.assertEqual(tmpl["event"]["name"], "test-event")
        self.assertEqual(tmpl["event"]["status"], "draft")

    def test_create_duplicate_fails(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import MagicMock

        tmpdir = tempfile.mkdtemp()
        cfg = MockConfig(tmpdir)

        from freq.modules.event_network import _save_template, cmd_event_create
        _save_template(cfg, "exists", {"event": {"name": "exists"}})

        args = MagicMock()
        args.name = "exists"

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_event_create(cfg, None, args)

        self.assertEqual(rc, 1)


class TestEventListCommand(unittest.TestCase):
    """Test cmd_event_list."""

    def test_list_empty(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import MagicMock

        tmpdir = tempfile.mkdtemp()
        cfg = MockConfig(tmpdir)

        from freq.modules.event_network import cmd_event_list
        args = MagicMock()

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_event_list(cfg, None, args)

        self.assertEqual(rc, 0)

    def test_list_with_events(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import MagicMock

        tmpdir = tempfile.mkdtemp()
        cfg = MockConfig(tmpdir)

        from freq.modules.event_network import _save_template, cmd_event_list
        _save_template(cfg, "event-a", {
            "event": {"name": "a", "status": "draft", "created": "2026-04-01"},
            "switches": [{"label": "sw1"}],
        })

        args = MagicMock()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_event_list(cfg, None, args)

        self.assertEqual(rc, 0)
        self.assertIn("event-a", buf.getvalue())


class TestEventDeleteCommand(unittest.TestCase):
    """Test cmd_event_delete."""

    def test_delete_requires_confirm(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import MagicMock

        tmpdir = tempfile.mkdtemp()
        cfg = MockConfig(tmpdir)
        from freq.modules.event_network import _save_template, cmd_event_delete
        _save_template(cfg, "test", {"event": {"name": "test"}})

        args = MagicMock()
        args.name = "test"
        args.yes = False

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_event_delete(cfg, None, args)
        self.assertEqual(rc, 1)

    def test_delete_with_confirm(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import MagicMock

        tmpdir = tempfile.mkdtemp()
        cfg = MockConfig(tmpdir)
        from freq.modules.event_network import _save_template, cmd_event_delete, _load_template
        _save_template(cfg, "test", {"event": {"name": "test"}})

        args = MagicMock()
        args.name = "test"
        args.yes = True

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_event_delete(cfg, None, args)
        self.assertEqual(rc, 0)
        self.assertIsNone(_load_template(cfg, "test"))


# ---------------------------------------------------------------------------
# Module Import Tests
# ---------------------------------------------------------------------------

class TestEventModuleImports(unittest.TestCase):
    """Test that event_network module imports cleanly."""

    def test_module_imports(self):
        from freq.modules import event_network
        self.assertIsNotNone(event_network)

    def test_all_commands_import(self):
        from freq.modules.event_network import (
            cmd_event_create, cmd_event_list, cmd_event_show,
            cmd_event_plan, cmd_event_deploy, cmd_event_verify,
            cmd_event_wipe, cmd_event_archive, cmd_event_delete,
        )
        self.assertTrue(callable(cmd_event_create))
        self.assertTrue(callable(cmd_event_list))
        self.assertTrue(callable(cmd_event_show))
        self.assertTrue(callable(cmd_event_plan))
        self.assertTrue(callable(cmd_event_deploy))
        self.assertTrue(callable(cmd_event_verify))
        self.assertTrue(callable(cmd_event_wipe))
        self.assertTrue(callable(cmd_event_archive))
        self.assertTrue(callable(cmd_event_delete))


if __name__ == "__main__":
    unittest.main()
