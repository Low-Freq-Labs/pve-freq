"""Collected CLI behavior owners retained from the original Phase-9 proof."""

from __future__ import annotations

import importlib
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace


class TestCLIBehaviorTable(unittest.TestCase):
    """Exercise CLI help, dispatch, convergence, and operator help as tables."""

    DOMAINS = (
        "vm",
        "fleet",
        "host",
        "docker",
        "secure",
        "observe",
        "state",
        "auto",
        "ops",
        "hw",
        "store",
        "dr",
        "net",
        "fw",
        "cert",
        "dns",
        "proxy",
        "media",
        "user",
        "event",
        "vpn",
        "plugin",
    )
    DISPATCH_CASES = (
        "vm list",
        "vm create --name test --image debian --node pve01",
        "vm power start 100",
        "fleet status",
        "fleet exec all hostname",
        "fleet health",
        "host list",
        "host add",
        "docker list",
        "secure audit",
        "secure vault list",
        "observe alert list",
        "observe logs tail freq-test",
        "state baseline capture freq-test",
        "state plan",
        "auto rules list",
        "auto schedule list",
        "ops oncall whoami",
        "hw cost",
        "store nas status",
        "dr backup list",
        "net switch facts switch",
        "net switch interfaces switch",
        "fw rules list",
        "cert scan",
        "dns scan",
        "proxy status",
        "user list",
        "event create test-event",
        "event list",
        "vpn wg status",
        "plugin list",
        "plugin create --name test",
        "plugin types",
    )
    PHASE_DISPATCH_DEFAULTS = (
        "observe alert",
        "vm rollback 100",
        "fleet inventory",
        "fleet compare a b",
        "state baseline",
        "fleet report",
        "observe trend",
        "observe sla",
        "cert",
        "dns",
        "auto schedule",
        "dr policy",
        "auto webhook",
        "dr migrate-plan",
        "dr migrate-vmware",
        "secure patch",
        "docker stack",
        "docs",
        "observe db",
        "proxy",
        "secure secrets",
        "observe logs",
        "ops oncall",
        "secure comply",
        "net map",
        "net netmon",
        "hw cost-analysis",
    )
    LEGACY_PHASE1_ARGUMENT_CASES = (
        (
            "observe alert create test-rule --condition cpu_above --threshold 2.0 --alert-severity critical",
            (
                ("action", "create"),
                ("name", "test-rule"),
                ("condition", "cpu_above"),
                ("threshold", 2.0),
                ("alert_severity", "critical"),
            ),
        ),
        (
            "observe alert delete my-rule",
            (("action", "delete"), ("name", "my-rule")),
        ),
        (
            "observe alert silence host-* --duration 120",
            (("action", "silence"), ("name", "host-*"), ("duration", 120)),
        ),
        ("observe alert test", (("action", "test"),)),
        (
            "observe alert history --lines 50",
            (("action", "history"), ("lines", 50)),
        ),
        ("vm rollback 5005", (("target", "5005"),)),
        (
            "vm rollback 100 --name pre-upgrade",
            (("target", "100"), ("name", "pre-upgrade")),
        ),
        ("vm rollback 100 --no-start", (("no_start", True),)),
        ("fleet inventory hosts", (("section", "hosts"),)),
        ("fleet inventory vms", (("section", "vms"),)),
        ("fleet inventory --csv", (("csv", True),)),
        (
            "fleet compare pve01 pve02",
            (("target_a", "pve01"), ("target_b", "pve02")),
        ),
        (
            "state baseline capture my-baseline",
            (("action", "capture"), ("name", "my-baseline")),
        ),
        (
            "state baseline compare my-baseline",
            (("action", "compare"), ("name", "my-baseline")),
        ),
        (
            "state baseline delete old-baseline",
            (("action", "delete"), ("name", "old-baseline")),
        ),
    )
    LEGACY_PHASE1_OVERLAP_ARGUMENT_CASES = (
        ("observe alert", (("action", "list"),)),
        ("fleet inventory", (("section", "all"),)),
        ("state baseline", (("action", "list"),)),
    )
    LEGACY_PHASE2_ARGUMENT_CASES = (
        ("fleet report --markdown", (("markdown", True),)),
        ("observe trend snapshot", (("action", "snapshot"),)),
        (
            "observe trend history --lines 50",
            (("action", "history"), ("lines", 50)),
        ),
        ("observe sla check", (("action", "check"),)),
        ("observe sla show --days 90", (("days", 90),)),
        ("observe sla reset", (("action", "reset"),)),
        (
            "cert check pve01:8006",
            (("subcmd", "check"), ("target", "pve01:8006")),
        ),
        ("cert list", (("subcmd", "list"),)),
        (
            "dns check 10.25.255.50",
            (("subcmd", "check"), ("target", "10.25.255.50")),
        ),
        ("dns list", (("subcmd", "list"),)),
    )
    LEGACY_PHASE2_OVERLAP_ARGUMENT_CASES = (
        ("fleet report", (("action", "generate"),)),
        ("observe trend", (("action", "show"),)),
        ("observe sla", (("action", "show"),)),
        ("cert", (("subcmd", None),)),
        ("dns", (("subcmd", None),)),
    )
    LEGACY_PHASE3_ARGUMENT_CASES = (
        ("auto schedule templates", (("action", "templates"),)),
        (
            "dr policy create prod-daily --target prod --retention 14",
            (
                ("action", "create"),
                ("name", "prod-daily"),
                ("target", "prod"),
                ("retention", 14),
            ),
        ),
        ("dr policy apply", (("action", "apply"),)),
        (
            "auto webhook test my-hook",
            (("action", "test"), ("name", "my-hook")),
        ),
        (
            "dr migrate-vmware import /tmp/vm.ova --vmid 200 --node pve01",
            (
                ("action", "import"),
                ("target", "/tmp/vm.ova"),
                ("vmid", 200),
                ("node", "pve01"),
            ),
        ),
        ("dr migrate-vmware status", (("action", "status"),)),
    )
    LEGACY_PHASE3_ARGV_ARGUMENT_CASES = (
        (
            (
                "auto",
                "schedule",
                "create",
                "my-job",
                "--command",
                "freq trend snapshot",
                "--interval",
                "2h",
            ),
            (
                ("action", "create"),
                ("name", "my-job"),
                ("command", "freq trend snapshot"),
                ("interval", "2h"),
            ),
        ),
        (
            (
                "auto",
                "webhook",
                "create",
                "deploy-hook",
                "--command",
                "freq doctor",
            ),
            (
                ("action", "create"),
                ("name", "deploy-hook"),
                ("command", "freq doctor"),
            ),
        ),
    )
    LEGACY_PHASE3_OVERLAP_ARGUMENT_CASES = (
        ("auto schedule", (("action", "list"),)),
        ("dr policy", (("action", "list"),)),
        ("auto webhook", (("action", "list"),)),
        ("dr migrate-plan", (("action", "show"),)),
        ("dr migrate-vmware", (("action", "scan"),)),
    )
    LEGACY_PHASE4_ARGUMENT_CASES = (
        ("secure patch check", (("action", "check"),)),
        (
            "secure patch apply --target-host web-01",
            (("action", "apply"), ("target_host", "web-01")),
        ),
        (
            "secure patch hold nginx",
            (("action", "hold"), ("name", "nginx")),
        ),
        ("secure patch compliance", (("action", "compliance"),)),
        (
            "docker stack update media",
            (("action", "update"), ("name", "media")),
        ),
        ("docker stack health", (("action", "health"),)),
        (
            "docker stack logs media --lines 50",
            (("action", "logs"), ("name", "media"), ("lines", 50)),
        ),
        ("docker stack template", (("action", "template"),)),
        ("docs verify", (("action", "verify"),)),
        (
            "docs export --format html",
            (("action", "export"), ("format", "html")),
        ),
        (
            "docs runbook disk-cleanup",
            (("action", "runbook"), ("name", "disk-cleanup")),
        ),
    )
    LEGACY_PHASE4_OVERLAP_ARGUMENT_CASES = (
        ("secure patch", (("action", "status"),)),
        ("docker stack", (("action", "status"),)),
        ("docs", (("action", "generate"),)),
    )
    LEGACY_PHASE5_ARGUMENT_CASES = (
        ("observe db size", (("action", "size"),)),
        (
            "proxy add --upstream 10.0.0.5:8080",
            (("subcmd", "add"), ("upstream", "10.0.0.5:8080")),
        ),
        ("proxy list", (("subcmd", "list"),)),
        ("secure secrets scan", (("action", "scan"),)),
        (
            "secure secrets generate --secret-type token --length 48",
            (
                ("action", "generate"),
                ("secret_type", "token"),
                ("length", 48),
            ),
        ),
        (
            "secure secrets lease my-key --expires 90d",
            (("action", "lease"), ("name", "my-key"), ("expires", "90d")),
        ),
    )
    LEGACY_PHASE5_OVERLAP_ARGUMENT_CASES = (
        ("observe db", (("action", "status"),)),
        ("proxy", (("subcmd", None),)),
        ("secure secrets", (("action", "list"),)),
    )
    LEGACY_PHASE6_ARGUMENT_CASES = (
        (
            "observe logs search OOM --since 2h",
            (("action", "search"), ("pattern", "OOM"), ("since", "2h")),
        ),
        ("observe logs stats", (("action", "stats"),)),
        (
            "ops oncall schedule --users alice,bob",
            (("action", "schedule"), ("users", "alice,bob")),
        ),
        (
            "ops oncall ack INC-001",
            (("action", "ack"), ("name", "INC-001")),
        ),
        ("secure comply report", (("action", "report"),)),
        ("secure comply exceptions", (("action", "exceptions"),)),
    )
    LEGACY_PHASE6_ARGV_ARGUMENT_CASES = (
        (
            (
                "ops",
                "oncall",
                "alert",
                "--message",
                "Disk full",
                "--alert-severity",
                "critical",
            ),
            (
                ("action", "alert"),
                ("message", "Disk full"),
                ("alert_severity", "critical"),
            ),
        ),
        (
            (
                "ops",
                "oncall",
                "resolve",
                "INC-001",
                "--note",
                "Fixed it",
            ),
            (("action", "resolve"), ("note", "Fixed it")),
        ),
    )
    LEGACY_PHASE6_OVERLAP_ARGUMENT_CASES = (
        ("observe logs", (("action", "tail"),)),
        ("ops oncall", (("action", "whoami"),)),
        ("secure comply", (("action", "scan"),)),
    )
    LEGACY_PHASE7_ARGUMENT_CASES = (
        (
            "net map impact db-01",
            (("action", "impact"), ("target", "db-01")),
        ),
        (
            "net map export --format dot",
            (("action", "export"), ("format", "dot")),
        ),
        ("net netmon poll", (("action", "poll"),)),
        ("net netmon bandwidth", (("action", "bandwidth"),)),
        (
            "hw cost-analysis compare --rate 0.15",
            (("action", "compare"), ("rate", 0.15)),
        ),
        ("hw cost-analysis density", (("action", "density"),)),
    )
    LEGACY_PHASE7_OVERLAP_ARGUMENT_CASES = (
        ("net map", (("action", "discover"),)),
        ("net netmon", (("action", "interfaces"),)),
        ("hw cost-analysis", (("action", "waste"),)),
    )
    PHASE2_ARGUMENT_CASES = (
        ("fw status", ()),
        ("fw rules", ()),
        ("fw rules audit", (("action", "audit"),)),
        ("fw nat", ()),
        ("fw states", ()),
        ("fw dhcp", ()),
        ("fw interfaces", ()),
        ("fw gateways", ()),
        ("dns internal list", ()),
        ("dns internal add test.local 10.0.0.1", (("hostname", "test.local"), ("ip", "10.0.0.1"))),
        ("dns internal sync", ()),
        ("vpn wg peers", ()),
        ("vpn wg audit", ()),
        ("vpn ovpn status", ()),
        ("cert inspect google.com:443", (("target", "google.com:443"),)),
        ("cert fleet-check", ()),
        ("cert acme", ()),
        ("cert issued", ()),
        ("cert plan --json", (("json", True),)),
        (
            "cert bootstrap --base-domain dc01.lowfreqlabs.com --cloudflare-token-file /tmp/cf --dry-run",
            (
                ("base_domain", "dc01.lowfreqlabs.com"),
                ("cloudflare_token_file", "/tmp/cf"),
                ("dry_run", True),
            ),
        ),
        ("cert issue --dry-run", (("dry_run", True),)),
        ("cert renew --deploy --dry-run", (("deploy", True), ("dry_run", True))),
        (
            "cert deploy pve01 --dry-run --json",
            (("target", "pve01"), ("dry_run", True), ("json", True)),
        ),
        ("cert dns-sync --dry-run --json", (("dry_run", True), ("json", True))),
        ("cert verify pfsense --json", (("target", "pfsense"), ("json", True))),
        ("proxy hosts", ()),
        ("proxy health", ()),
    )
    WS2_ARGUMENT_CASES = (
        ("net snmp poll switch", ()),
        ("net snmp poll --all", (("all", True),)),
        ("net snmp poll switch --community private", (("community", "private"),)),
        ("net snmp interfaces switch", ()),
        ("net snmp errors switch", ()),
        ("net snmp cpu switch", ()),
        ("net snmp identity switch", ()),
        ("net snmp setup-plan", ()),
        ("net topology discover", ()),
        ("net topology show", ()),
        ("net topology export --format dot", (("format", "dot"),)),
        ("net topology export --format json", (("format", "json"),)),
        ("net topology diff", ()),
        ("net find-mac aabb.ccdd.eeff", (("mac", "aabb.ccdd.eeff"),)),
        ("net find-ip 10.25.255.5", (("ip", "10.25.255.5"),)),
        ("net troubleshoot 10.25.255.5", (("target", "10.25.255.5"),)),
        ("net ip-util", ()),
        ("net ip-conflict", ()),
    )
    PHASE3_ARGUMENT_CASES = (
        ("store status", ()),
        ("store pools", ()),
        ("store pools pve01", (("target", "pve01"),)),
        ("store datasets", ()),
        ("store snapshots", ()),
        ("store smart", ()),
        ("store shares", ()),
        ("store alerts", ()),
        ("dr status", ()),
        ("dr verify", ()),
        ("dr sla list", ()),
        (
            "dr sla set 100 --rpo 12 --rto 2",
            (("vmid", "100"), ("rpo", 12), ("rto", 2)),
        ),
        ("dr runbook list", ()),
        ("dr runbook create full-recovery", (("name", "full-recovery"),)),
        ("dr runbook show full-recovery", (("name", "full-recovery"),)),
    )
    PHASE4_ARGUMENT_CASES = (
        ("observe metrics collect", ()),
        ("observe metrics show", ()),
        ("observe metrics top", ()),
        ("observe monitor list", ()),
        ("observe monitor run", ()),
        ("secure vuln scan", ()),
        ("secure vuln results", ()),
        ("secure fim baseline", ()),
        ("secure fim check", ()),
        ("secure fim status", ()),
    )
    PHASE5_ARGUMENT_CASES = (
        ("ops incident list", ()),
        ("ops incident create test-incident", (("title", "test-incident"),)),
        ("ops change list", ()),
        ("state export", ()),
        ("state drift", ()),
        ("state history", ()),
        ("auto react list", ()),
        ("auto workflow list", ()),
        ("auto job", ()),
    )
    PHASE6_ARGUMENT_CASES = (
        ("docker images", ()),
        ("docker prune", ()),
        ("docker update-check", ()),
        ("hw smart", ()),
        ("hw ups", ()),
        ("hw power", ()),
        ("hw inventory", ()),
    )
    PHASE7_ARGUMENT_CASES = (
        ("plugin info test-name", (("name", "test-name"),)),
        ("plugin install https://example.com/p.py", (("source", "https://example.com/p.py"),)),
        ("plugin remove test-plugin", (("name", "test-plugin"),)),
        (
            "plugin create --name my-plugin --type deployer",
            (("name", "my-plugin"), ("type", "deployer")),
        ),
        ("plugin search firewall", (("query", "firewall"),)),
        ("plugin update", ()),
        ("plugin update my-plugin", (("name", "my-plugin"),)),
    )
    CONFIG_ARGUMENT_CASES = (
        ("net config backup", ()),
        ("net config backup --all", (("all", True),)),
        ("net config backup switch", (("target", "switch"),)),
        ("net config history", ()),
        ("net config history switch", (("target", "switch"),)),
        ("net config diff switch", (("target", "switch"),)),
        ("net config diff switch --version 2", (("version", 2),)),
        ("net config search vlan", (("pattern", "vlan"),)),
        ("net config restore switch", ()),
        ("net config restore switch --version 3", (("version", 3),)),
    )
    EVENT_ARGUMENT_CASES = (
        ("event create superbowl", (("name", "superbowl"),)),
        ("event show superbowl", (("name", "superbowl"),)),
        ("event plan superbowl", (("name", "superbowl"),)),
        ("event deploy superbowl", ()),
        ("event verify superbowl", ()),
        ("event wipe superbowl --confirm", (("confirm", True),)),
        ("event wipe superbowl", (("confirm", False),)),
        ("event archive superbowl", ()),
        ("event delete superbowl --yes", (("yes", True),)),
    )
    SWITCH_ARGUMENT_CASES = (
        ("net switch show", ()),
        ("net switch facts", ()),
        ("net switch interfaces", ()),
        ("net switch vlans", ()),
        ("net switch mac", ()),
        ("net switch arp", ()),
        ("net switch neighbors", ()),
        ("net switch config", ()),
        ("net switch environment", ()),
        ("net switch exec", ()),
        ("net switch show 10.25.255.5", (("target", "10.25.255.5"),)),
        ("net switch mac --vlan 50", (("vlan", "50"),)),
        ("net switch config --backup", (("backup", True),)),
        ("net switch exec --all", (("all", True),)),
    )
    PORT_ARGUMENT_CASES = (
        ("net port status", ()),
        (
            "net port configure switch Gi1/0/5 --vlan 50",
            (("port", "Gi1/0/5"), ("vlan", "50")),
        ),
        (
            "net port desc switch Gi1/0/5 --description Camera",
            (("description", "Camera"),),
        ),
        ("net port poe", ()),
        ("net port poe switch --port Gi1/0/1 --on", (("on", True),)),
        ("net port find --mac aabb.ccdd.eeff", (("mac", "aabb.ccdd.eeff"),)),
        ("net port flap --port Gi1/0/5", (("port", "Gi1/0/5"),)),
    )
    PROFILE_ARGUMENT_CASES = (
        ("net switch profile list", ()),
        ("net switch profile show camera", (("name", "camera"),)),
        (
            "net switch profile create test --mode access --vlan 50",
            (("name", "test"), ("mode", "access"), ("vlan", "50")),
        ),
        (
            "net switch profile apply camera switch --ports Gi1/0/1-24",
            (("name", "camera"), ("target", "switch"), ("ports", "Gi1/0/1-24")),
        ),
        ("net switch profile delete test", (("name", "test"),)),
    )
    IPAM_ARGUMENT_CASES = (
        ("net ip next --vlan mgmt", (("action", "next"), ("vlan", "mgmt"))),
        ("net ip list", (("action", "list"),)),
        (
            "net ip check 10.0.0.50",
            (("action", "check"), ("target", "10.0.0.50")),
        ),
        ("net ip next --vlan lan --count 5", (("count", 5),)),
    )
    DOCKER_FLEET_ARGUMENT_CASES = (
        ("docker fleet ps", (("docker_action", "ps"),)),
        ("docker fleet stats", (("docker_action", "stats"),)),
        (
            "docker fleet logs nginx --lines 50",
            (("docker_action", "logs"), ("service", "nginx"), ("lines", 50)),
        ),
    )
    PLAN_ARGUMENT_CASES = (
        ("state plan --file /tmp/my-plan.toml", (("file", "/tmp/my-plan.toml"),)),
        ("state apply --dry-run", (("dry_run", True),)),
        ("state apply --yes", (("yes", True),)),
    )
    VM_PARSER_ARGUMENT_CASES = (
        ("vm power start 5001", (("action", "start"), ("target", "5001"))),
        (
            "vm snapshot list 5001",
            (("snap_action", "list"), ("target", "5001")),
        ),
        (
            "vm snapshot delete 5001 --name snap1",
            (("snap_action", "delete"), ("name", "snap1")),
        ),
        (
            "vm nic add 5001 --ip 192.168.10.50 --vlan 10",
            (
                ("action", "add"),
                ("target", "5001"),
                ("ip", "192.168.10.50"),
                ("vlan", "10"),
            ),
        ),
        ("vm nic clear 5001", (("action", "clear"),)),
        ("vm nic clear 5001 --yes", (("action", "clear"), ("yes", True))),
        (
            "vm nic change-id 5001 --new-id 5002",
            (("action", "change-id"), ("new_id", "5002")),
        ),
        (
            "vm nic check-ip --ip 192.168.10.1",
            (("action", "check-ip"), ("ip", "192.168.10.1")),
        ),
    )
    FLEET_PARSER_ARGUMENT_CASES = (
        ("fleet detail web01", (("target", "web01"),)),
        ("fleet boundaries", (("action", "show"),)),
        (
            "fleet boundaries lookup 5001",
            (("action", "lookup"), ("target", "5001")),
        ),
    )
    TOP_LEVEL_COMMANDS = (
        "version",
        "help",
        "doctor",
        "menu",
        "demo",
        "init",
        "configure",
        "serve",
        "update",
        "docs",
        "distros",
        "notify",
        "lab",
    )
    CORE_ARGUMENT_CASES = (
        (
            "init --headless --service-account dc01-admin",
            (
                ("domain", "init"),
                ("headless", True),
                ("service_account", "dc01-admin"),
            ),
        ),
        (
            "vm create --name test --cores 4 --ram 2048",
            (("name", "test"), ("cores", 4), ("ram", 2048)),
        ),
        ("vm snapshot list 100", (("snap_action", "list"), ("target", "100"))),
        (
            "vm nic add 100 --ip 10.0.0.5/24",
            (("action", "add"), ("target", "100"), ("ip", "10.0.0.5/24")),
        ),
        (
            "fleet log myhost --lines 50 --unit sshd",
            (("target", "myhost"), ("lines", 50), ("unit", "sshd")),
        ),
        (
            "host discover 192.168.1.0/24",
            (("subcmd", "discover"), ("subnet", "192.168.1.0/24")),
        ),
        (
            "docker stack update mystack",
            (
                ("domain", "docker"),
                ("subcmd", "stack"),
                ("action", "update"),
                ("name", "mystack"),
            ),
        ),
        ("secure vault init", (("action", "init"),)),
        ("secure vault set", (("action", "set"),)),
        ("secure vault get", (("action", "get"),)),
        ("secure vault delete", (("action", "delete"),)),
        ("secure audit --fix", (("fix", True),)),
        (
            "observe alert check",
            (("domain", "observe"), ("subcmd", "alert"), ("action", "check")),
        ),
        (
            "state check ssh-hardening --hosts lab-pve1,lab-pve2",
            (("policy", "ssh-hardening"), ("hosts", "lab-pve1,lab-pve2")),
        ),
        ("ops risk pfsense", (("target", "pfsense"),)),
        ("dns check myhost", (("subcmd", "check"), ("target", "myhost"))),
        (
            "user create testuser --role admin",
            (("subcmd", "create"), ("username", "testuser"), ("role", "admin")),
        ),
        ("hw idrac status", (("action", "status"),)),
        ("version", ()),
        ("help", ()),
        ("secure sweep --fix", (("fix", True),)),
        ("auto patrol --interval 60", (("interval", 60),)),
        ("--debug --yes version", (("debug", True), ("yes", True))),
        ("notify test message", (("message", ["test", "message"]),)),
        (
            "vm import --image debian-13 --name myvm",
            (("image", "debian-13"), ("name", "myvm")),
        ),
        ("media status", (("action", "status"),)),
    )
    CORE_OVERLAP_ARGUMENT_CASES = (
        ("vm list", (("domain", "vm"), ("subcmd", "list"))),
        (
            "vm power start 100",
            (("subcmd", "power"), ("action", "start"), ("target", "100")),
        ),
        ("fleet status", (("domain", "fleet"), ("subcmd", "status"))),
        ("host list", (("domain", "host"), ("subcmd", "list"))),
        ("fw status", (("domain", "fw"), ("subcmd", "status"))),
        ("cert scan", (("subcmd", "scan"),)),
        ("dr backup list", (("action", "list"),)),
        ("store nas status", (("action", "status"),)),
        ("secure vault list", (("action", "list"),)),
    )
    CORE_ARGV_ARGUMENT_CASES = (
        (
            ("auto", "schedule", "create", "myjob", "--command", "freq fleet status"),
            (("action", "create"), ("name", "myjob")),
        ),
    )
    CLI_OUTPUT_CASES = (
        (("version",), ("F R E Q",), ()),
        (("help",), ("freq vm", "freq fleet", "freq secure", "freq doctor"), ()),
        (("state", "policies"), ("ssh-hardening",), ()),
        (("ops", "risk", "all"), (), ("risk",)),
        (("distros",), ("cloud images",), ()),
        (("user", "roles"), ("viewer", "admin"), ()),
        (("configure",), ("Version",), ()),
        (("notify",), ("not configured",), ()),
        (("vm", "provision"), ("debian-13",), ()),
    )
    CLI_STATUS_CASES = (
        (("doctor",), (0, 1)),
    )
    RETIRED_FLAT_COMMANDS = (
        ("create", "--name", "test"),
        ("destroy", "100"),
        ("audit",),
    )
    HELP_TERMS = ("vm", "fleet", "plugin", "net", "secure", "observe", "auto", "dr")

    def setUp(self):
        from freq.cli import _build_parser

        self.parser = _build_parser()

    def test_all_domain_help_paths_exit_cleanly(self):
        import argparse

        self.assertEqual(len(self.DOMAINS), 22)
        self.assertEqual(len(set(self.DOMAINS)), 22)
        self.assertEqual(len(self.TOP_LEVEL_COMMANDS), 13)
        self.assertEqual(len(set(self.TOP_LEVEL_COMMANDS)), 13)
        registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices)
        for command in self.TOP_LEVEL_COMMANDS:
            with self.subTest(top_level=command):
                self.assertIn(command, registered)
        for domain in self.DOMAINS:
            with self.subTest(domain=domain), redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    self.parser.parse_args([domain, "--help"])
                self.assertEqual(raised.exception.code, 0)

    def test_representative_commands_dispatch_to_callable_handlers(self):
        combined = self.DISPATCH_CASES + self.PHASE_DISPATCH_DEFAULTS
        legacy_phase1_commands = tuple(
            command for command, _ in self.LEGACY_PHASE1_ARGUMENT_CASES
        )
        legacy_phase1_overlap_commands = tuple(
            command for command, _ in self.LEGACY_PHASE1_OVERLAP_ARGUMENT_CASES
        )
        legacy_phase2_commands = tuple(
            command for command, _ in self.LEGACY_PHASE2_ARGUMENT_CASES
        )
        legacy_phase2_overlap_commands = tuple(
            command for command, _ in self.LEGACY_PHASE2_OVERLAP_ARGUMENT_CASES
        )
        legacy_phase3_commands = tuple(
            command for command, _ in self.LEGACY_PHASE3_ARGUMENT_CASES
        )
        legacy_phase3_argv = tuple(
            argv for argv, _ in self.LEGACY_PHASE3_ARGV_ARGUMENT_CASES
        )
        legacy_phase3_overlap_commands = tuple(
            command for command, _ in self.LEGACY_PHASE3_OVERLAP_ARGUMENT_CASES
        )
        legacy_phase4_commands = tuple(
            command for command, _ in self.LEGACY_PHASE4_ARGUMENT_CASES
        )
        legacy_phase4_overlap_commands = tuple(
            command for command, _ in self.LEGACY_PHASE4_OVERLAP_ARGUMENT_CASES
        )
        legacy_phase5_commands = tuple(
            command for command, _ in self.LEGACY_PHASE5_ARGUMENT_CASES
        )
        legacy_phase5_overlap_commands = tuple(
            command for command, _ in self.LEGACY_PHASE5_OVERLAP_ARGUMENT_CASES
        )
        legacy_phase6_commands = tuple(
            command for command, _ in self.LEGACY_PHASE6_ARGUMENT_CASES
        )
        legacy_phase6_argv = tuple(
            argv for argv, _ in self.LEGACY_PHASE6_ARGV_ARGUMENT_CASES
        )
        legacy_phase6_overlap_commands = tuple(
            command for command, _ in self.LEGACY_PHASE6_OVERLAP_ARGUMENT_CASES
        )
        legacy_phase7_commands = tuple(
            command for command, _ in self.LEGACY_PHASE7_ARGUMENT_CASES
        )
        legacy_phase7_overlap_commands = tuple(
            command for command, _ in self.LEGACY_PHASE7_OVERLAP_ARGUMENT_CASES
        )
        phase2_commands = tuple(command for command, _ in self.PHASE2_ARGUMENT_CASES)
        ws2_commands = tuple(command for command, _ in self.WS2_ARGUMENT_CASES)
        phase3_commands = tuple(command for command, _ in self.PHASE3_ARGUMENT_CASES)
        phase4_commands = tuple(command for command, _ in self.PHASE4_ARGUMENT_CASES)
        phase5_commands = tuple(command for command, _ in self.PHASE5_ARGUMENT_CASES)
        phase6_commands = tuple(command for command, _ in self.PHASE6_ARGUMENT_CASES)
        phase7_commands = tuple(command for command, _ in self.PHASE7_ARGUMENT_CASES)
        config_commands = tuple(command for command, _ in self.CONFIG_ARGUMENT_CASES)
        event_commands = tuple(command for command, _ in self.EVENT_ARGUMENT_CASES)
        switch_commands = tuple(command for command, _ in self.SWITCH_ARGUMENT_CASES)
        port_commands = tuple(command for command, _ in self.PORT_ARGUMENT_CASES)
        profile_commands = tuple(command for command, _ in self.PROFILE_ARGUMENT_CASES)
        ipam_commands = tuple(command for command, _ in self.IPAM_ARGUMENT_CASES)
        docker_fleet_commands = tuple(
            command for command, _ in self.DOCKER_FLEET_ARGUMENT_CASES
        )
        plan_commands = tuple(command for command, _ in self.PLAN_ARGUMENT_CASES)
        vm_parser_commands = tuple(
            command for command, _ in self.VM_PARSER_ARGUMENT_CASES
        )
        fleet_parser_commands = tuple(
            command for command, _ in self.FLEET_PARSER_ARGUMENT_CASES
        )
        core_commands = tuple(command for command, _ in self.CORE_ARGUMENT_CASES)
        overlap_commands = tuple(
            command for command, _ in self.CORE_OVERLAP_ARGUMENT_CASES
        )
        core_argv = tuple(argv for argv, _ in self.CORE_ARGV_ARGUMENT_CASES)
        all_argument_cases = (
            self.LEGACY_PHASE1_ARGUMENT_CASES
            + self.LEGACY_PHASE2_ARGUMENT_CASES
            + self.LEGACY_PHASE3_ARGUMENT_CASES
            + self.LEGACY_PHASE4_ARGUMENT_CASES
            + self.LEGACY_PHASE5_ARGUMENT_CASES
            + self.LEGACY_PHASE6_ARGUMENT_CASES
            + self.LEGACY_PHASE7_ARGUMENT_CASES
            + self.PHASE2_ARGUMENT_CASES
            + self.WS2_ARGUMENT_CASES
            + self.PHASE3_ARGUMENT_CASES
            + self.PHASE4_ARGUMENT_CASES
            + self.PHASE5_ARGUMENT_CASES
            + self.PHASE6_ARGUMENT_CASES
            + self.PHASE7_ARGUMENT_CASES
            + self.CONFIG_ARGUMENT_CASES
            + self.EVENT_ARGUMENT_CASES
            + self.SWITCH_ARGUMENT_CASES
            + self.PORT_ARGUMENT_CASES
            + self.PROFILE_ARGUMENT_CASES
            + self.IPAM_ARGUMENT_CASES
            + self.DOCKER_FLEET_ARGUMENT_CASES
            + self.PLAN_ARGUMENT_CASES
            + self.VM_PARSER_ARGUMENT_CASES
            + self.FLEET_PARSER_ARGUMENT_CASES
            + self.CORE_ARGUMENT_CASES
        )
        all_commands = (
            combined
            + legacy_phase1_commands
            + legacy_phase2_commands
            + legacy_phase3_commands
            + legacy_phase4_commands
            + legacy_phase5_commands
            + legacy_phase6_commands
            + legacy_phase7_commands
            + phase2_commands
            + ws2_commands
            + phase3_commands
            + phase4_commands
            + phase5_commands
            + phase6_commands
            + phase7_commands
            + config_commands
            + event_commands
            + switch_commands
            + port_commands
            + profile_commands
            + ipam_commands
            + docker_fleet_commands
            + plan_commands
            + vm_parser_commands
            + fleet_parser_commands
            + core_commands
        )
        self.assertEqual(len(self.DISPATCH_CASES), 34)
        self.assertEqual(len(self.PHASE_DISPATCH_DEFAULTS), 27)
        self.assertEqual(len(combined), 61)
        self.assertEqual(len(set(combined)), 61)
        self.assertEqual(len(legacy_phase1_commands), 15)
        self.assertEqual(len(set(legacy_phase1_commands)), 15)
        self.assertEqual(
            sum(len(expected) for _, expected in self.LEGACY_PHASE1_ARGUMENT_CASES),
            28,
        )
        self.assertEqual(len(legacy_phase1_overlap_commands), 3)
        self.assertEqual(len(set(legacy_phase1_overlap_commands)), 3)
        self.assertEqual(
            sum(
                len(expected)
                for _, expected in self.LEGACY_PHASE1_OVERLAP_ARGUMENT_CASES
            ),
            3,
        )
        self.assertTrue(
            set(legacy_phase1_overlap_commands).issubset(set(combined))
        )
        self.assertEqual(len(legacy_phase2_commands), 10)
        self.assertEqual(len(set(legacy_phase2_commands)), 10)
        self.assertEqual(
            sum(len(expected) for _, expected in self.LEGACY_PHASE2_ARGUMENT_CASES),
            13,
        )
        self.assertEqual(len(legacy_phase2_overlap_commands), 5)
        self.assertEqual(len(set(legacy_phase2_overlap_commands)), 5)
        self.assertEqual(
            sum(
                len(expected)
                for _, expected in self.LEGACY_PHASE2_OVERLAP_ARGUMENT_CASES
            ),
            5,
        )
        self.assertTrue(
            set(legacy_phase2_overlap_commands).issubset(set(combined))
        )
        self.assertEqual(len(legacy_phase3_commands), 6)
        self.assertEqual(len(set(legacy_phase3_commands)), 6)
        self.assertEqual(
            sum(len(expected) for _, expected in self.LEGACY_PHASE3_ARGUMENT_CASES),
            13,
        )
        self.assertEqual(len(legacy_phase3_argv), 2)
        self.assertEqual(len(set(legacy_phase3_argv)), 2)
        self.assertEqual(
            sum(
                len(expected)
                for _, expected in self.LEGACY_PHASE3_ARGV_ARGUMENT_CASES
            ),
            7,
        )
        self.assertEqual(len(legacy_phase3_overlap_commands), 5)
        self.assertEqual(len(set(legacy_phase3_overlap_commands)), 5)
        self.assertEqual(
            sum(
                len(expected)
                for _, expected in self.LEGACY_PHASE3_OVERLAP_ARGUMENT_CASES
            ),
            5,
        )
        self.assertTrue(
            set(legacy_phase3_overlap_commands).issubset(set(combined))
        )
        self.assertEqual(len(legacy_phase4_commands), 11)
        self.assertEqual(len(set(legacy_phase4_commands)), 11)
        self.assertEqual(
            sum(len(expected) for _, expected in self.LEGACY_PHASE4_ARGUMENT_CASES),
            18,
        )
        self.assertEqual(len(legacy_phase4_overlap_commands), 3)
        self.assertEqual(len(set(legacy_phase4_overlap_commands)), 3)
        self.assertEqual(
            sum(
                len(expected)
                for _, expected in self.LEGACY_PHASE4_OVERLAP_ARGUMENT_CASES
            ),
            3,
        )
        self.assertTrue(
            set(legacy_phase4_overlap_commands).issubset(set(combined))
        )
        self.assertEqual(len(legacy_phase5_commands), 6)
        self.assertEqual(len(set(legacy_phase5_commands)), 6)
        self.assertEqual(
            sum(len(expected) for _, expected in self.LEGACY_PHASE5_ARGUMENT_CASES),
            11,
        )
        self.assertEqual(len(legacy_phase5_overlap_commands), 3)
        self.assertEqual(len(set(legacy_phase5_overlap_commands)), 3)
        self.assertEqual(
            sum(
                len(expected)
                for _, expected in self.LEGACY_PHASE5_OVERLAP_ARGUMENT_CASES
            ),
            3,
        )
        self.assertTrue(
            set(legacy_phase5_overlap_commands).issubset(set(combined))
        )
        self.assertEqual(len(legacy_phase6_commands), 6)
        self.assertEqual(len(set(legacy_phase6_commands)), 6)
        self.assertEqual(
            sum(len(expected) for _, expected in self.LEGACY_PHASE6_ARGUMENT_CASES),
            10,
        )
        self.assertEqual(len(legacy_phase6_argv), 2)
        self.assertEqual(len(set(legacy_phase6_argv)), 2)
        self.assertEqual(
            sum(
                len(expected)
                for _, expected in self.LEGACY_PHASE6_ARGV_ARGUMENT_CASES
            ),
            5,
        )
        self.assertEqual(len(legacy_phase6_overlap_commands), 3)
        self.assertEqual(len(set(legacy_phase6_overlap_commands)), 3)
        self.assertEqual(
            sum(
                len(expected)
                for _, expected in self.LEGACY_PHASE6_OVERLAP_ARGUMENT_CASES
            ),
            3,
        )
        self.assertTrue(
            set(legacy_phase6_overlap_commands).issubset(set(combined))
        )
        self.assertEqual(len(legacy_phase7_commands), 6)
        self.assertEqual(len(set(legacy_phase7_commands)), 6)
        self.assertEqual(
            sum(len(expected) for _, expected in self.LEGACY_PHASE7_ARGUMENT_CASES),
            9,
        )
        self.assertEqual(len(legacy_phase7_overlap_commands), 3)
        self.assertEqual(len(set(legacy_phase7_overlap_commands)), 3)
        self.assertEqual(
            sum(
                len(expected)
                for _, expected in self.LEGACY_PHASE7_OVERLAP_ARGUMENT_CASES
            ),
            3,
        )
        self.assertTrue(
            set(legacy_phase7_overlap_commands).issubset(set(combined))
        )
        alert_check_case = (
            "observe alert check",
            (("domain", "observe"), ("subcmd", "alert"), ("action", "check")),
        )
        self.assertIn(alert_check_case, self.CORE_ARGUMENT_CASES)
        self.assertEqual(len(phase2_commands), 27)
        self.assertEqual(len(set(phase2_commands)), 27)
        self.assertEqual(sum(len(expected) for _, expected in self.PHASE2_ARGUMENT_CASES), 18)
        self.assertEqual(len(ws2_commands), 18)
        self.assertEqual(len(set(ws2_commands)), 18)
        self.assertEqual(sum(len(expected) for _, expected in self.WS2_ARGUMENT_CASES), 7)
        self.assertEqual(len(phase3_commands), 15)
        self.assertEqual(len(set(phase3_commands)), 15)
        self.assertEqual(sum(len(expected) for _, expected in self.PHASE3_ARGUMENT_CASES), 6)
        self.assertEqual(len(phase4_commands), 10)
        self.assertEqual(len(set(phase4_commands)), 10)
        self.assertEqual(sum(len(expected) for _, expected in self.PHASE4_ARGUMENT_CASES), 0)
        self.assertEqual(len(phase5_commands), 9)
        self.assertEqual(len(set(phase5_commands)), 9)
        self.assertEqual(sum(len(expected) for _, expected in self.PHASE5_ARGUMENT_CASES), 1)
        self.assertIn("docker list", self.DISPATCH_CASES)
        self.assertEqual(len(phase6_commands), 7)
        self.assertEqual(len(set(phase6_commands)), 7)
        self.assertEqual(sum(len(expected) for _, expected in self.PHASE6_ARGUMENT_CASES), 0)
        self.assertIn("plugin list", self.DISPATCH_CASES)
        self.assertIn("plugin types", self.DISPATCH_CASES)
        self.assertEqual(len(phase7_commands), 7)
        self.assertEqual(len(set(phase7_commands)), 7)
        self.assertEqual(sum(len(expected) for _, expected in self.PHASE7_ARGUMENT_CASES), 7)
        self.assertEqual(len(config_commands), 10)
        self.assertEqual(len(set(config_commands)), 10)
        self.assertEqual(sum(len(expected) for _, expected in self.CONFIG_ARGUMENT_CASES), 7)
        self.assertIn("event", self.DOMAINS)
        self.assertIn("event list", self.DISPATCH_CASES)
        self.assertEqual(len(event_commands), 9)
        self.assertEqual(len(set(event_commands)), 9)
        self.assertEqual(sum(len(expected) for _, expected in self.EVENT_ARGUMENT_CASES), 6)
        self.assertEqual((len(switch_commands), len(port_commands), len(profile_commands)), (14, 7, 5))
        self.assertEqual((len(set(switch_commands)), len(set(port_commands)), len(set(profile_commands))), (14, 7, 5))
        self.assertEqual(
            tuple(sum(len(expected) for _, expected in cases) for cases in (
                self.SWITCH_ARGUMENT_CASES,
                self.PORT_ARGUMENT_CASES,
                self.PROFILE_ARGUMENT_CASES,
            )),
            (4, 6, 8),
        )
        self.assertIn("net", self.DOMAINS)
        self.assertEqual(len(ipam_commands), 4)
        self.assertEqual(len(set(ipam_commands)), 4)
        self.assertEqual(sum(len(expected) for _, expected in self.IPAM_ARGUMENT_CASES), 6)
        self.assertIn("docker", self.DOMAINS)
        self.assertIn("observe", self.DOMAINS)
        self.assertIn("observe monitor list", phase4_commands)
        self.assertIn("observe monitor run", phase4_commands)
        self.assertEqual(len(docker_fleet_commands), 3)
        self.assertEqual(len(set(docker_fleet_commands)), 3)
        self.assertEqual(
            sum(len(expected) for _, expected in self.DOCKER_FLEET_ARGUMENT_CASES),
            5,
        )
        self.assertIn("state", self.DOMAINS)
        self.assertIn("state plan", self.DISPATCH_CASES)
        self.assertEqual(len(plan_commands), 3)
        self.assertEqual(len(set(plan_commands)), 3)
        self.assertEqual(sum(len(expected) for _, expected in self.PLAN_ARGUMENT_CASES), 3)
        self.assertIn("vm", self.DOMAINS)
        self.assertIn("fleet", self.DOMAINS)
        self.assertIn("vm power start 100", self.DISPATCH_CASES)
        self.assertEqual(len(vm_parser_commands), 8)
        self.assertEqual(len(set(vm_parser_commands)), 8)
        self.assertEqual(
            sum(len(expected) for _, expected in self.VM_PARSER_ARGUMENT_CASES),
            17,
        )
        self.assertEqual(len(fleet_parser_commands), 3)
        self.assertEqual(len(set(fleet_parser_commands)), 3)
        self.assertEqual(
            sum(len(expected) for _, expected in self.FLEET_PARSER_ARGUMENT_CASES),
            4,
        )
        self.assertEqual(len(core_commands), 26)
        self.assertEqual(len(set(core_commands)), 26)
        self.assertEqual(
            sum(len(expected) for _, expected in self.CORE_ARGUMENT_CASES),
            45,
        )
        self.assertEqual(len(overlap_commands), 9)
        self.assertEqual(len(set(overlap_commands)), 9)
        self.assertEqual(
            sum(len(expected) for _, expected in self.CORE_OVERLAP_ARGUMENT_CASES),
            15,
        )
        self.assertEqual(len(all_commands), 306)
        self.assertEqual(len(set(all_commands)), 306)
        self.assertTrue(set(overlap_commands).issubset(set(all_commands)))
        ipam_mgmt_case = (
            "net ip next --vlan mgmt",
            (("action", "next"), ("vlan", "mgmt")),
        )
        self.assertIn(ipam_mgmt_case, self.IPAM_ARGUMENT_CASES)
        self.assertEqual(len(core_argv), 1)
        self.assertEqual(len(set(core_argv)), 1)
        self.assertEqual(core_argv[0][-1], "freq fleet status")
        self.assertEqual(
            sum(len(expected) for _, expected in self.CORE_ARGV_ARGUMENT_CASES),
            2,
        )
        string_argv = {tuple(command.split()) for command in all_commands}
        self.assertEqual(len(string_argv), 306)
        exact_argv = core_argv + legacy_phase3_argv + legacy_phase6_argv
        self.assertEqual(len(exact_argv), 5)
        self.assertEqual(len(set(exact_argv)), 5)
        self.assertTrue(set(exact_argv).isdisjoint(string_argv))
        self.assertEqual(len(string_argv) + len(set(exact_argv)), 311)
        inherited_value_count = (
            sum(len(expected) for _, expected in self.CORE_ARGUMENT_CASES)
            + sum(len(expected) for _, expected in self.CORE_OVERLAP_ARGUMENT_CASES)
            + len(ipam_mgmt_case[1])
            + sum(len(expected) for _, expected in self.CORE_ARGV_ARGUMENT_CASES)
        )
        self.assertEqual(inherited_value_count, 64)
        for command in combined:
            with self.subTest(command=command):
                args = self.parser.parse_args(command.split())
                self.assertTrue(callable(getattr(args, "func", None)), command)
        for command, expected in all_argument_cases:
            with self.subTest(command=command):
                names = tuple(name for name, _ in expected)
                self.assertEqual(len(names), len(set(names)), f"duplicate argument oracle: {command}")
                args = self.parser.parse_args(command.split())
                self.assertTrue(callable(getattr(args, "func", None)), command)
                for name, value in expected:
                    self.assertEqual(getattr(args, name), value, f"{command}: {name}")
        for command, expected in self.CORE_OVERLAP_ARGUMENT_CASES:
            with self.subTest(overlap=command):
                names = tuple(name for name, _ in expected)
                self.assertEqual(len(names), len(set(names)))
                args = self.parser.parse_args(command.split())
                self.assertTrue(callable(getattr(args, "func", None)), command)
                for name, value in expected:
                    self.assertEqual(getattr(args, name), value, f"{command}: {name}")
        for command, expected in self.LEGACY_PHASE1_OVERLAP_ARGUMENT_CASES:
            with self.subTest(legacy_phase1_overlap=command):
                names = tuple(name for name, _ in expected)
                self.assertEqual(len(names), len(set(names)))
                args = self.parser.parse_args(command.split())
                self.assertTrue(callable(getattr(args, "func", None)), command)
                for name, value in expected:
                    self.assertEqual(getattr(args, name), value, f"{command}: {name}")
        for command, expected in self.LEGACY_PHASE2_OVERLAP_ARGUMENT_CASES:
            with self.subTest(legacy_phase2_overlap=command):
                names = tuple(name for name, _ in expected)
                self.assertEqual(len(names), len(set(names)))
                args = self.parser.parse_args(command.split())
                self.assertTrue(callable(getattr(args, "func", None)), command)
                for name, value in expected:
                    self.assertEqual(getattr(args, name), value, f"{command}: {name}")
        for command, expected in self.LEGACY_PHASE3_OVERLAP_ARGUMENT_CASES:
            with self.subTest(legacy_phase3_overlap=command):
                names = tuple(name for name, _ in expected)
                self.assertEqual(len(names), len(set(names)))
                args = self.parser.parse_args(command.split())
                self.assertTrue(callable(getattr(args, "func", None)), command)
                for name, value in expected:
                    self.assertEqual(getattr(args, name), value, f"{command}: {name}")
        for command, expected in self.LEGACY_PHASE4_OVERLAP_ARGUMENT_CASES:
            with self.subTest(legacy_phase4_overlap=command):
                names = tuple(name for name, _ in expected)
                self.assertEqual(len(names), len(set(names)))
                args = self.parser.parse_args(command.split())
                self.assertTrue(callable(getattr(args, "func", None)), command)
                for name, value in expected:
                    self.assertEqual(getattr(args, name), value, f"{command}: {name}")
        for command, expected in self.LEGACY_PHASE5_OVERLAP_ARGUMENT_CASES:
            with self.subTest(legacy_phase5_overlap=command):
                names = tuple(name for name, _ in expected)
                self.assertEqual(len(names), len(set(names)))
                args = self.parser.parse_args(command.split())
                self.assertTrue(callable(getattr(args, "func", None)), command)
                for name, value in expected:
                    self.assertEqual(getattr(args, name), value, f"{command}: {name}")
        for command, expected in self.LEGACY_PHASE6_OVERLAP_ARGUMENT_CASES:
            with self.subTest(legacy_phase6_overlap=command):
                names = tuple(name for name, _ in expected)
                self.assertEqual(len(names), len(set(names)))
                args = self.parser.parse_args(command.split())
                self.assertTrue(callable(getattr(args, "func", None)), command)
                for name, value in expected:
                    self.assertEqual(getattr(args, name), value, f"{command}: {name}")
        for command, expected in self.LEGACY_PHASE7_OVERLAP_ARGUMENT_CASES:
            with self.subTest(legacy_phase7_overlap=command):
                names = tuple(name for name, _ in expected)
                self.assertEqual(len(names), len(set(names)))
                args = self.parser.parse_args(command.split())
                self.assertTrue(callable(getattr(args, "func", None)), command)
                for name, value in expected:
                    self.assertEqual(getattr(args, name), value, f"{command}: {name}")
        for argv, expected in self.LEGACY_PHASE6_ARGV_ARGUMENT_CASES:
            with self.subTest(legacy_phase6_argv=argv):
                names = tuple(name for name, _ in expected)
                self.assertEqual(len(names), len(set(names)))
                args = self.parser.parse_args(list(argv))
                self.assertTrue(callable(getattr(args, "func", None)), argv)
                for name, value in expected:
                    self.assertEqual(getattr(args, name), value, f"{argv}: {name}")
        for argv, expected in self.LEGACY_PHASE3_ARGV_ARGUMENT_CASES:
            with self.subTest(legacy_phase3_argv=argv):
                names = tuple(name for name, _ in expected)
                self.assertEqual(len(names), len(set(names)))
                args = self.parser.parse_args(list(argv))
                self.assertTrue(callable(getattr(args, "func", None)), argv)
                for name, value in expected:
                    self.assertEqual(getattr(args, name), value, f"{argv}: {name}")
        for argv, expected in self.CORE_ARGV_ARGUMENT_CASES:
            with self.subTest(argv=argv):
                names = tuple(name for name, _ in expected)
                self.assertEqual(len(names), len(set(names)))
                args = self.parser.parse_args(list(argv))
                self.assertTrue(callable(getattr(args, "func", None)), argv)
                for name, value in expected:
                    self.assertEqual(getattr(args, name), value, f"{argv}: {name}")

    def test_retired_flat_commands_are_rejected(self):
        for argv in self.RETIRED_FLAT_COMMANDS:
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    self.parser.parse_args(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_operator_help_lists_every_retained_domain_family(self):
        from freq.cli import cmd_help

        output = io.StringIO()
        with redirect_stdout(output):
            cmd_help(SimpleNamespace(version="3.0.0"), SimpleNamespace(), SimpleNamespace())
        text = output.getvalue().lower()
        for term in self.HELP_TERMS:
            with self.subTest(term=term):
                self.assertIn(term, text)

        from freq.cli import main

        argv_cases = tuple(argv for argv, _, _ in self.CLI_OUTPUT_CASES)
        self.assertEqual(len(argv_cases), 9)
        self.assertEqual(len(set(argv_cases)), 9)
        self.assertEqual(sum(len(exact) for _, exact, _ in self.CLI_OUTPUT_CASES), 12)
        self.assertEqual(sum(len(lower) for _, _, lower in self.CLI_OUTPUT_CASES), 1)
        for argv, exact, lower in self.CLI_OUTPUT_CASES:
            with self.subTest(output=argv):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    try:
                        result = main(list(argv))
                    except SystemExit as exc:
                        result = exc.code or 0
                self.assertEqual(result, 0)
                output = stdout.getvalue()
                for token in exact:
                    self.assertIn(token, output)
                folded = output.lower()
                for token in lower:
                    self.assertIn(token, folded)

        self.assertEqual(self.CLI_STATUS_CASES, ((("doctor",), (0, 1)),))
        status_argv = tuple(argv for argv, _ in self.CLI_STATUS_CASES)
        self.assertEqual(len(status_argv), 1)
        self.assertEqual(len(set(status_argv)), 1)
        for argv, allowed_statuses in self.CLI_STATUS_CASES:
            with self.subTest(status=argv), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                try:
                    result = main(list(argv))
                except SystemExit as exc:
                    result = exc.code or 0
                self.assertIn(result, allowed_statuses)


class TestModuleImportTable(unittest.TestCase):
    """Import every module retained by the Phase-9 local proof."""

    COMMAND_EXPORTS = (
        ("alert", "cmd_alert"),
        ("backup_policy", "cmd_backup_policy"),
        ("baseline", "cmd_baseline"),
        ("cert", "cmd_cert"),
        ("cert_management", "cmd_cert_acme_status"),
        ("cert_management", "cmd_cert_bootstrap"),
        ("cert_management", "cmd_cert_deploy"),
        ("cert_management", "cmd_cert_dns_sync"),
        ("cert_management", "cmd_cert_fleet_check"),
        ("cert_management", "cmd_cert_inspect"),
        ("cert_management", "cmd_cert_issue"),
        ("cert_management", "cmd_cert_issued_list"),
        ("cert_management", "cmd_cert_plan"),
        ("cert_management", "cmd_cert_renew"),
        ("cert_management", "cmd_cert_verify"),
        ("compare", "cmd_compare"),
        ("comply", "cmd_comply"),
        ("cost_analysis", "cmd_cost_analysis"),
        ("db", "cmd_db"),
        ("depmap", "cmd_map"),
        ("dns", "cmd_dns"),
        ("dns_management", "cmd_dns_internal_add"),
        ("dns_management", "cmd_dns_internal_audit"),
        ("dns_management", "cmd_dns_internal_list"),
        ("dns_management", "cmd_dns_internal_remove"),
        ("dns_management", "cmd_dns_internal_sync"),
        ("docs", "cmd_docs"),
        ("firewall", "cmd_fw_dhcp"),
        ("firewall", "cmd_fw_gateways"),
        ("firewall", "cmd_fw_interfaces"),
        ("firewall", "cmd_fw_nat"),
        ("firewall", "cmd_fw_rules"),
        ("firewall", "cmd_fw_states"),
        ("firewall", "cmd_fw_status"),
        ("inventory", "cmd_inventory"),
        ("logs", "cmd_logs"),
        ("migrate_plan", "cmd_migrate_plan"),
        ("migrate_vmware", "cmd_migrate_vmware"),
        ("netmon", "cmd_netmon"),
        ("oncall", "cmd_oncall"),
        ("patch", "cmd_patch"),
        ("proxy", "cmd_proxy"),
        ("proxy_management", "cmd_proxy_health"),
        ("proxy_management", "cmd_proxy_hosts"),
        ("proxy_management", "cmd_proxy_status"),
        ("report", "cmd_report"),
        ("rollback", "cmd_rollback"),
        ("schedule", "cmd_schedule"),
        ("secrets", "cmd_secrets"),
        ("sla", "cmd_sla"),
        ("stack", "cmd_stack"),
        ("storage", "cmd_store_alerts"),
        ("storage", "cmd_store_datasets"),
        ("storage", "cmd_store_pools"),
        ("storage", "cmd_store_shares"),
        ("storage", "cmd_store_smart"),
        ("storage", "cmd_store_snapshots"),
        ("storage", "cmd_store_status"),
        ("trend", "cmd_trend"),
        ("vpn", "cmd_vpn_ovpn_status"),
        ("vpn", "cmd_vpn_wg_audit"),
        ("vpn", "cmd_vpn_wg_peers"),
        ("vpn", "cmd_vpn_wg_status"),
        ("webhook", "cmd_webhook"),
    )

    MODULES = (
        "switch_orchestration",
        "config_management",
        "event_network",
        "snmp",
        "topology",
        "net_intelligence",
        "firewall",
        "dns_management",
        "vpn",
        "cert_management",
        "proxy_management",
        "storage",
        "dr",
        "metrics",
        "synthetic_monitors",
        "vuln",
        "fim",
        "incident",
        "iac",
        "automation",
        "docker_mgmt",
        "hardware",
        "plugin_manager",
    )

    def test_all_retained_modules_import(self):
        for module in self.MODULES:
            with self.subTest(module=module):
                __import__(f"freq.modules.{module}")

    def test_retained_command_exports_are_callable(self):
        self.assertEqual(len(self.COMMAND_EXPORTS), 64)
        self.assertEqual(len(set(self.COMMAND_EXPORTS)), 64)
        self.assertEqual(len({module for module, _ in self.COMMAND_EXPORTS}), 33)
        for module, symbol in self.COMMAND_EXPORTS:
            with self.subTest(module=module, symbol=symbol):
                imported = importlib.import_module(f"freq.modules.{module}")
                export = getattr(imported, symbol)
                self.assertTrue(callable(export))
