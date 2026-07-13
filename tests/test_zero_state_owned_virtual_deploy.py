"""Owned virtual appliances retain identity through deploy and verification."""

import base64
import json
import re
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from freq.modules import init_cmd


def _host(*, managed=True):
    return types.SimpleNamespace(
        ip="192.168.255.25",
        label="truenas-lab",
        htype="truenas",
        managed=managed,
        vmid=0,
        all_ips=["192.168.255.25", "192.168.25.25", "10.25.10.201"],
    )


def _deploy_cfg(host):
    return types.SimpleNamespace(
        pve_nodes=[],
        pve_node_names=[],
        hosts=[host],
        ssh_service_account="freq-admin",
        ssh_key_path="/tmp/fleet-key",
        _owned_vmids={5001},
    )


def _deploy_ctx():
    return {
        "svc_name": "freq-admin",
        "svc_pass": "SvcPass2026!",
        "pubkey": "ssh-ed25519 AAAA-owned-vm-test freq-admin",
        "key_path": "/tmp/fleet-key",
        "ip_vmid_map": {"10.25.10.201": 5001},
        "vmid_node_map": {5001: "10.25.255.26"},
    }


class TestOwnedVirtualApplianceDeploy(unittest.TestCase):
    @patch("freq.modules.init_cmd._run")
    def test_phase12_qga_diagnosis_names_strictmodes_owner_mismatch(self, run):
        run.return_value = (
            0,
            json.dumps({
                "exitcode": 0,
                "out-data": (
                    "SSH_OWNER 3008 3008 3005 3005 3005 3005 3005 3005\n"
                    "SSH_MODE 755 700 600\n"
                ),
            }),
            "",
        )
        cfg = types.SimpleNamespace(ssh_key_path="/tmp/fleet-key")
        reason = init_cmd._guest_agent_ssh_ownership_diagnosis(
            cfg,
            {"key_path": "/tmp/fleet-key"},
            5001,
            "10.25.255.26",
            "freq-admin",
        )

        self.assertEqual(
            reason,
            "StrictModes ownership/mode mismatch: account=3008:3008, "
            "home=3005:3005/755, .ssh=3005:3005/700, "
            "authorized_keys=3005:3005/600",
        )
        self.assertEqual(init_cmd._skip_reason(f"Permission denied; {reason}"), reason)

    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.fmt")
    def test_guest_agent_rejects_deploy_without_owner_proof(self, _fmt, run):
        run.return_value = (
            0,
            json.dumps({"exitcode": 0, "out-data": "DEPLOY_OK\n"}),
            "",
        )
        cfg = types.SimpleNamespace(ssh_key_path="/tmp/fleet-key")
        ctx = _deploy_ctx()

        self.assertFalse(
            init_cmd._deploy_via_guest_agent(
                cfg,
                ctx,
                5001,
                "10.25.255.26",
                "192.168.255.25",
                "truenas-lab",
                "truenas",
            )
        )

    @patch("freq.modules.init_cmd._run")
    @patch("freq.modules.init_cmd.fmt")
    def test_linux_guest_agent_password_failure_keeps_key_repair_nonfatal(
        self, fmt, run
    ):
        commands = []

        def fake_run(command, timeout=None):
            commands.append(command)
            return (
                0,
                json.dumps({
                    "exitcode": 0,
                    "out-data": (
                        "CHPASSWD_FAIL\nSSH_OWNERSHIP_OK\nDEPLOY_OK\n"
                    ),
                }),
                "",
            )

        run.side_effect = fake_run
        cfg = types.SimpleNamespace(ssh_key_path="/tmp/fleet-key")

        self.assertTrue(
            init_cmd._deploy_via_guest_agent(
                cfg,
                _deploy_ctx(),
                5001,
                "10.25.255.26",
                "192.168.255.25",
                "owned-linux",
                "linux",
            )
        )
        match = re.search(
            r"echo ([A-Za-z0-9+/=]+) \| base64 -d", commands[0][-1]
        )
        self.assertIsNotNone(match)
        script = base64.b64decode(match.group(1)).decode()
        self.assertIn("chpasswd 2>/dev/null || echo CHPASSWD_FAIL", script)
        self.assertIn("SSH_OWNERSHIP_OK", script)
        fmt.step_warn.assert_called_once_with(
            "owned-linux: password update failed; SSH key auth configured"
        )

    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._deploy_via_guest_agent", return_value=True)
    @patch(
        "freq.modules.init_cmd._run",
        return_value=(255, "", "Permission denied (publickey)."),
    )
    @patch("freq.modules.init_cmd.fmt")
    def test_vmidless_primary_ip_miss_uses_all_ips_for_guest_agent(
        self, _fmt, _run, guest_deploy, dispatch
    ):
        host = _host()
        cfg = _deploy_cfg(host)
        ctx = _deploy_ctx()

        init_cmd._headless_fleet_deploy(
            cfg,
            ctx,
            bootstrap_key="/tmp/bootstrap-key",
            bootstrap_user="freq-ops",
        )

        guest_deploy.assert_called_once_with(
            cfg,
            ctx,
            5001,
            "10.25.255.26",
            "192.168.255.25",
            "truenas-lab",
            "truenas",
        )
        dispatch.assert_not_called()
        self.assertEqual(ctx["deployed_ips"], {"192.168.255.25"})
        self.assertEqual(ctx["fleet_deploy_failures"], 0)

    @patch("freq.modules.init_cmd._mark_host_unmanaged")
    @patch("freq.modules.init_cmd._deploy_to_host_dispatch")
    @patch("freq.modules.init_cmd._deploy_via_guest_agent", return_value=False)
    @patch(
        "freq.modules.init_cmd._run",
        return_value=(255, "", "Permission denied (publickey)."),
    )
    @patch("freq.modules.init_cmd.fmt")
    def test_owned_vm_guest_agent_failure_is_not_silently_demoted(
        self, _fmt, _run, _guest_deploy, dispatch, mark_unmanaged
    ):
        host = _host()
        cfg = _deploy_cfg(host)
        ctx = _deploy_ctx()

        init_cmd._headless_fleet_deploy(
            cfg,
            ctx,
            bootstrap_key="/tmp/bootstrap-key",
            bootstrap_user="freq-ops",
        )

        dispatch.assert_not_called()
        mark_unmanaged.assert_not_called()
        self.assertTrue(host.managed)
        self.assertEqual(ctx["fleet_deploy_failures"], 1)
        self.assertEqual(ctx["fleet_deploy_failed_ips"], {"192.168.255.25"})
        self.assertEqual(ctx["fleet_deploy_skips"], 0)

    def test_guest_agent_deploy_establishes_key_phase12_verifies(self):
        """Exercise the VM5001 guest-agent script through Phase-12 SSH truth."""
        host = _host()
        account_ready = False
        guest_script = ""

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conf = root / "conf"
            data = root / "data"
            keys = data / "keys"
            vault = data / "vault"
            log = data / "log"
            for directory in (conf, keys, vault, log):
                directory.mkdir(parents=True, exist_ok=True)
            key_file = keys / "freq_id_ed25519"
            rsa_file = keys / "freq_id_rsa"
            key_file.write_text("private-key")
            rsa_file.write_text("rsa-key")
            (vault / "freq.vault").write_text("vault")
            (conf / "roles.conf").write_text("[roles]\n")
            (conf / "freq.toml").write_text("[infrastructure]\n")
            (conf / "hosts.toml").write_text(
                '[[hosts]]\nip = "192.168.255.25"\nlabel = "truenas-lab"\n'
            )
            (conf / "fleet-boundaries.toml").write_text(
                '[categories.lab]\nvmids = [5001]\n'
            )
            (conf / "pve-inventory.toml").write_text(
                '[[resource]]\nvmid = 5001\nkind = "vm"\n'
                '[summary]\nresource_count = 1\nvm_count = 1\ntemplate_count = 0\n'
            )
            cfg = types.SimpleNamespace(
                pve_nodes=["10.25.255.26"],
                pve_node_names=["pve01"],
                hosts=[host],
                ssh_service_account="freq-admin",
                ssh_key_path=str(key_file),
                _owned_vmids={5001},
                key_dir=str(keys),
                vault_file=str(vault / "freq.vault"),
                conf_dir=str(conf),
                hosts_file=str(conf / "hosts.toml"),
                log_file=str(log / "freq.log"),
                log_dir=str(log),
                data_dir=str(data),
                pve_api_token_id="freq@pve!token",
                pve_api_token_secret="secret",
                vlans=[],
                pfsense_ip="",
                truenas_ip="192.168.255.25",
                switch_ip="",
                version="test",
                agent_port=9990,
            )
            ctx = _deploy_ctx()
            ctx["key_path"] = str(key_file)

            def run_deploy(command, timeout=None):
                nonlocal account_ready, guest_script
                if "qm guest exec 5001" not in command[-1]:
                    return 255, "", "Permission denied (publickey)."
                match = re.search(r"echo ([A-Za-z0-9+/=]+) \| base64 -d", command[-1])
                self.assertIsNotNone(match)
                guest_script = base64.b64decode(match.group(1)).decode()
                account_ready = (
                    ctx["pubkey"] in guest_script
                    and "authorized_keys" in guest_script
                    and "TRUENAS_QGA_KEY_ONLY" in guest_script
                    and "chpasswd" not in guest_script
                    and "/etc/sudoers.d/freq-freq-admin" in guest_script
                    and 'chown freq-admin:$(id -gn freq-admin) "$_h"' in guest_script
                    and "chown -R freq-admin:$(id -gn freq-admin)" in guest_script
                    and "_home_unsafe" in guest_script
                    and "SSH_OWNERSHIP_FAIL" in guest_script
                    and "SSH_OWNERSHIP_OK" in guest_script
                )
                return 0, json.dumps({
                    "exitcode": 0,
                    "out-data": "SSH_OWNERSHIP_OK\nDEPLOY_OK\n",
                }), ""

            with (
                patch("freq.modules.init_cmd._run", side_effect=run_deploy),
                patch("freq.modules.init_cmd._deploy_to_host_dispatch"),
                patch("freq.modules.init_cmd.fmt"),
            ):
                cfg.pve_nodes = []
                init_cmd._headless_fleet_deploy(
                    cfg,
                    ctx,
                    bootstrap_key="",
                    bootstrap_user="freq-ops",
                )
                cfg.pve_nodes = ["10.25.255.26"]

            self.assertTrue(account_ready, guest_script)
            self.assertEqual(ctx["deployed_ips"], {"192.168.255.25"})

            def verify_host(ip, htype, user, key, rsa, cfg=None):
                if ip == host.ip:
                    self.assertTrue(account_ready)
                return True, ""

            def run_verify(command, timeout=None):
                if command[0] == "timedatectl":
                    return 0, "America/Chicago\n", ""
                return 0, "", ""

            marker = root / ".initialized"
            with (
                patch("freq.modules.init_cmd._run", side_effect=run_verify),
                patch("freq.modules.init_cmd._verify_host", side_effect=verify_host) as verify,
                patch("freq.modules.pve._pve_api_call", return_value=({}, True)),
                patch("freq.modules.init_cmd._write_init_status"),
                patch("freq.modules.init_cmd.INIT_MARKER", str(marker)),
                patch("freq.modules.init_cmd.fmt") as verify_fmt,
            ):
                verified = init_cmd._phase_verify(cfg, ctx)

            failures = [str(call.args[0]) for call in verify_fmt.step_fail.call_args_list]
            self.assertTrue(verified, failures)

            self.assertTrue(
                any(call.args[0] == host.ip for call in verify.call_args_list),
                "Phase 12 did not verify the guest-agent-deployed TrueNAS host",
            )
            self.assertTrue(marker.is_file())


if __name__ == "__main__":
    unittest.main()
