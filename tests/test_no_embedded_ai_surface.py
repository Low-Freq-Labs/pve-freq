"""Executable owner for Sonny's embedded-AI removal decision."""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOVED_MODULES = {
    "freq/jarvis/agent.py",
    "freq/jarvis/gitops.py",
    "freq/jarvis/learn.py",
    "freq/modules/specialist.py",
}
REMOVED_ROUTES = {
    "/api/agent/create",
    "/api/agent/destroy",
    "/api/agents",
    "/api/gitops/apply",
    "/api/gitops/diff",
    "/api/gitops/init",
    "/api/gitops/log",
    "/api/gitops/rollback",
    "/api/gitops/status",
    "/api/gitops/sync",
    "/api/learn",
    "/api/specialists",
}
REMOVED_BROWSER_SYMBOLS = {
    "gitopsApply",
    "gitopsDiff",
    "gitopsFetch",
    "gitopsInit",
    "gitopsRollback",
    "loadGitops",
    "searchLearn",
}
REMOVED_BROWSER_MARKUP = {
    'data-view="gitops"',
    'id="gitops-view"',
    'id="learn-q"',
    'id="learn-r"',
}
REMOVED_PUBLIC_COPY = {
    "AI specialist",
    "Agent Platform",
    "Smart Commands",
    "freq agent",
    "freq learn",
    "freq specialist",
    "state gitops",
}
CANONICAL_DOMAINS = {
    "auto",
    "cert",
    "config",
    "dns",
    "docker",
    "dr",
    "event",
    "fleet",
    "fw",
    "host",
    "hw",
    "lab",
    "media",
    "net",
    "notify",
    "observe",
    "ops",
    "plugin",
    "proxy",
    "secure",
    "state",
    "store",
    "user",
    "vm",
    "vpn",
}


class EmbeddedAiRemovalContract(unittest.TestCase):
    def test_ai_modules_are_absent(self):
        self.assertEqual(
            {path for path in REMOVED_MODULES if (ROOT / path).exists()},
            set(),
        )

    def test_python_product_has_no_removed_module_imports(self):
        forbidden = {
            "freq.jarvis.agent",
            "freq.jarvis.gitops",
            "freq.jarvis.learn",
            "freq.modules.specialist",
        }
        findings = []
        for path in sorted((ROOT / "freq").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in forbidden:
                    findings.append((path.relative_to(ROOT).as_posix(), node.lineno, node.module))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in forbidden:
                            findings.append((path.relative_to(ROOT).as_posix(), node.lineno, alias.name))
        self.assertEqual(findings, [])

    def test_cli_does_not_advertise_removed_ai_commands(self):
        from freq.cli import _build_parser

        parser = _build_parser()
        domains = parser._subparsers._group_actions[0].choices
        self.assertTrue({"agent", "learn", "specialist"}.isdisjoint(domains))
        state = domains["state"]
        state_actions = state._subparsers._group_actions[0].choices
        self.assertNotIn("gitops", state_actions)

    def test_canonical_domains_and_metrics_agent_remain(self):
        from freq.api import build_route_registry
        from freq.cli import _build_parser
        from freq.modules.serve import FreqHandler

        parser = _build_parser()
        domains = parser._subparsers._group_actions[0].choices
        self.assertEqual(CANONICAL_DOMAINS - domains.keys(), set())
        fleet = domains["fleet"]
        fleet_actions = fleet._subparsers._group_actions[0].choices
        self.assertIn("deploy-agent", fleet_actions)
        routes = build_route_registry(FreqHandler._ROUTES)
        self.assertIn("/api/deploy-agent", routes)

    def test_browser_has_no_dangling_removed_route_or_action(self):
        browser_paths = (
            ROOT / "freq/data/web/app.html",
            ROOT / "freq/data/web/js/app.js",
        )
        findings = []
        for path in browser_paths:
            source = path.read_text(encoding="utf-8")
            for token in sorted(REMOVED_ROUTES | REMOVED_BROWSER_SYMBOLS | REMOVED_BROWSER_MARKUP):
                if token in source:
                    findings.append((path.relative_to(ROOT).as_posix(), token))
        self.assertEqual(findings, [])

    def test_cli_tui_and_docs_have_no_removed_public_surface(self):
        public_paths = [
            ROOT / "README.md",
            ROOT / "freq/cli.py",
            ROOT / "freq/tui/menu.py",
            *sorted((ROOT / "docs").rglob("*.md")),
            *sorted((ROOT / "docs").rglob("*.txt")),
        ]
        findings = []
        for path in public_paths:
            source = path.read_text(encoding="utf-8", errors="replace")
            for token in sorted(REMOVED_ROUTES | REMOVED_PUBLIC_COPY):
                if token.lower() in source.lower():
                    findings.append((path.relative_to(ROOT).as_posix(), token))
        self.assertEqual(findings, [])

    def test_runtime_route_registry_has_no_removed_ai_routes(self):
        from freq.api import build_route_registry
        from freq.modules.serve import FreqHandler

        routes = build_route_registry(FreqHandler._ROUTES)
        self.assertEqual(sorted(REMOVED_ROUTES & routes.keys()), [])


if __name__ == "__main__":
    unittest.main()
