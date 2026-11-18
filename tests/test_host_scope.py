import unittest
from types import SimpleNamespace


class _Boundaries:
    def categorize(self, vmid):
        if vmid in {400, 802}:
            return "out_of_contract", "probe"
        if vmid >= 9000:
            return "templates", "probe"
        return "production", "operator"


class TestHostScope(unittest.TestCase):
    def test_managed_probe_hosts_excludes_operator_and_pve_guest_rows(self):
        import inspect

        from freq.core import host_scope
        from freq.modules import init_cmd, watchdog

        managed_probe_hosts = host_scope.managed_probe_hosts

        cfg = SimpleNamespace(
            pve_nodes=["10.25.255.26", "10.25.255.27", "10.25.255.28"],
            operator_exclude_labels=[],
            hosts=[
                SimpleNamespace(label="pve01", ip="10.25.255.26", htype="pve", vmid=0, managed=True),
                SimpleNamespace(label="pve-freq", ip="10.25.255.50", htype="linux", vmid=100, managed=True),
                SimpleNamespace(label="nexus", ip="10.25.255.8", htype="linux", vmid=901, managed=True),
                SimpleNamespace(label="lab-pve1", ip="10.25.10.202", htype="pve", vmid=5002, managed=True),
                SimpleNamespace(label="managed-app", ip="10.25.255.44", htype="linux", vmid=44, managed=True),
                SimpleNamespace(label="inventory-only", ip="10.25.255.45", htype="linux", vmid=45, managed=False),
            ],
        )

        labels = [h.label for h in managed_probe_hosts(cfg)]

        self.assertEqual(labels, ["pve01", "pve-freq", "nexus", "managed-app"])
        cfg.operator_exclude_labels = [" NEXUS ", "pve_freq"]
        self.assertEqual(
            [h.label for h in managed_probe_hosts(cfg)],
            ["pve01", "managed-app"],
        )
        self.assertEqual(
            inspect.getsource(host_scope).count("def is_operator_excluded("),
            1,
        )
        for module in (init_cmd, watchdog):
            source = inspect.getsource(module)
            with self.subTest(shared_exclusion_consumer=module.__name__):
                self.assertIn("is_operator_excluded(cfg,", source)
                self.assertNotIn("OPERATOR_AUTO_EXCLUDE_LABELS", source)

    def test_managed_probe_hosts_excludes_boundary_categories_and_inventory_lookup(self):
        from freq.core.host_scope import managed_probe_hosts

        cfg = SimpleNamespace(
            pve_nodes=["10.25.255.26"],
            conf_dir="",
            operator_exclude_labels=[],
            fleet_boundaries=_Boundaries(),
            hosts=[
                SimpleNamespace(label="owned-app", ip="10.25.25.44", htype="linux", vmid=144, managed=True, all_ips=[]),
                SimpleNamespace(label="runescapebotvm", ip="10.25.66.69", htype="linux", vmid=400, managed=True, all_ips=[]),
                SimpleNamespace(label="blue", ip="10.25.255.75", htype="linux", vmid=802, managed=True, all_ips=[]),
                SimpleNamespace(label="tpl-ubuntu-2404", ip="10.25.5.214", htype="linux", vmid=9004, managed=True, all_ips=[]),
                SimpleNamespace(label="operator-disabled", ip="10.25.25.45", htype="linux", vmid=145, managed=False, all_ips=[]),
            ],
        )

        labels = [h.label for h in managed_probe_hosts(cfg)]

        self.assertEqual(labels, ["owned-app"])

    def test_init_consumer_uses_same_configured_exclusion_policy(self):
        """F3-6: init has the same default-empty and configured behavior."""
        import inspect

        from freq.modules.init_cmd import _is_managed_auto_host

        parameters = list(inspect.signature(_is_managed_auto_host).parameters)
        self.assertEqual(parameters[0], "cfg")
        cfg = SimpleNamespace(operator_exclude_labels=[])
        self.assertTrue(_is_managed_auto_host(cfg, "nexus", "docker"))
        self.assertTrue(_is_managed_auto_host(cfg, "control-plane", "docker"))
        cfg.operator_exclude_labels = [" NEXUS ", "control_plane"]
        self.assertFalse(_is_managed_auto_host(cfg, "nexus", "docker"))
        self.assertFalse(_is_managed_auto_host(cfg, "control-plane", "docker"))

    def test_exclusion_source_has_one_owner_and_no_site_label_constants(self):
        """F3-7: source inventory rejects duplicate/local exclusion policy."""
        import ast
        import inspect
        from pathlib import Path

        from freq.core import host_scope
        from freq.modules import init_cmd, watchdog

        modules = (host_scope, init_cmd, watchdog)
        definition_owners = []
        forbidden_name = "OPERATOR" + "_AUTO_EXCLUDE_LABELS"
        site_label = "ne" + "xus"
        for module in modules:
            source = inspect.getsource(module)
            tree = ast.parse(source)
            definition_owners.extend(
                module.__name__
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "is_operator_excluded"
            )
            assigned_names = {
                target.id
                for node in ast.walk(tree)
                if isinstance(node, (ast.Assign, ast.AnnAssign))
                for target in (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if isinstance(target, ast.Name)
            }
            with self.subTest(module=module.__name__):
                self.assertNotIn(forbidden_name, assigned_names)

        self.assertEqual(definition_owners, ["freq.core.host_scope"])
        consumer_sources = {
            "host_scope": inspect.getsource(host_scope.should_probe_managed_host),
            "init_auto": inspect.getsource(init_cmd._is_managed_auto_host),
            "init_existing": inspect.getsource(init_cmd._inventory_only_reason),
            "watchdog": inspect.getsource(watchdog._cache_item_in_watchdog_contract),
        }
        for name, source in consumer_sources.items():
            with self.subTest(exclusion_consumer=name):
                self.assertIn("is_operator_excluded(cfg,", source)
                self.assertNotIn(site_label, source.lower())

        repo = Path(__file__).parents[1]
        for relpath in (
            "freq/core/host_scope.py",
            "freq/modules/init_cmd.py",
            "freq/modules/watchdog.py",
        ):
            with self.subTest(no_duplicated_constant=relpath):
                self.assertNotIn(forbidden_name, (repo / relpath).read_text())


if __name__ == "__main__":
    unittest.main()
