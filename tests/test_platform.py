"""Tests for platform abstraction layer — platform detection, packages, services."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPlatformDetection(unittest.TestCase):
    """Test local platform detection."""

    def test_detect_returns_platform(self):
        from freq.core.platform import Platform
        Platform.clear_cache()
        plat = Platform.detect()
        self.assertIsNotNone(plat)
        self.assertTrue(len(plat.os_id) > 0)

    def test_detect_os_id(self):
        from freq.core.platform import Platform
        plat = Platform.detect()
        # We're running on Debian/Nexus
        self.assertIn(plat.os_id, [
            "debian", "ubuntu", "rocky", "arch", "alpine", "fedora",
            "centos", "rhel", "almalinux", "opensuse-tumbleweed",
            "opensuse-leap", "manjaro", "linux",
        ])

    def test_detect_family(self):
        from freq.core.platform import Platform
        plat = Platform.detect()
        self.assertIn(plat.os_family, [
            "debian", "rhel", "arch", "alpine", "suse", "gentoo",
            "void", "freebsd", "nix", "slackware", "linux",
        ])

    def test_detect_python_version(self):
        from freq.core.platform import Platform
        plat = Platform.detect()
        self.assertEqual(plat.python_version[0], sys.version_info[0])
        self.assertEqual(plat.python_version[1], sys.version_info[1])

    def test_detect_init_system(self):
        from freq.core.platform import Platform
        plat = Platform.detect()
        self.assertIn(plat.init_system, [
            "systemd", "openrc", "runit", "sysvinit", "rc.d", "unknown",
        ])

    def test_detect_pkg_manager(self):
        from freq.core.platform import Platform
        plat = Platform.detect()
        self.assertIn(plat.pkg_manager, [
            "apt", "dnf", "yum", "pacman", "zypper", "apk",
            "xbps", "pkg", "emerge", "unknown",
        ])

    def test_detect_arch(self):
        from freq.core.platform import Platform
        plat = Platform.detect()
        self.assertTrue(len(plat.arch) > 0)

    def test_detect_is_cached(self):
        from freq.core.platform import Platform
        Platform.clear_cache()
        plat1 = Platform.detect()
        plat2 = Platform.detect()
        self.assertIs(plat1, plat2)

    def test_frozen_dataclass(self):
        from freq.core.platform import Platform
        plat = Platform.detect()
        with self.assertRaises(AttributeError):
            plat.os_id = "hacked"

    def test_family_map_covers_major_distros(self):
        from freq.core.platform import _FAMILY_MAP
        # Verify all major distros are in the family map
        for distro in ["debian", "ubuntu", "rocky", "fedora", "arch",
                       "alpine", "manjaro", "gentoo", "void"]:
            self.assertIn(distro, _FAMILY_MAP, f"{distro} missing from family map")


class TestRemotePlatform(unittest.TestCase):
    """Test remote platform parsing (without SSH)."""

    def test_parse_debian_output(self):
        from freq.core.remote_platform import RemotePlatform
        output = (
            'ID=debian\nVERSION_ID="13"\nPRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n'
            "ID_LIKE=debian\n"
            "---FREQ_SEP---\n"
            "INIT=systemd\n"
            "PKG=apt\n"
            "HAS_BASH=1\n"
            "HAS_DOCKER=1\n"
            "x86_64\n"
        )
        rp = RemotePlatform._parse("test-host", output)
        self.assertIsNotNone(rp)
        self.assertEqual(rp.os_id, "debian")
        self.assertEqual(rp.os_version, "13")
        self.assertEqual(rp.os_family, "debian")
        self.assertEqual(rp.init_system, "systemd")
        self.assertEqual(rp.pkg_manager, "apt")
        self.assertEqual(rp.arch, "x86_64")
        self.assertTrue(rp.has_bash)
        self.assertTrue(rp.has_docker)

    def test_parse_rocky_output(self):
        from freq.core.remote_platform import RemotePlatform
        output = (
            'ID="rocky"\nVERSION_ID="9.3"\nPRETTY_NAME="Rocky Linux 9.3"\n'
            'ID_LIKE="rhel centos fedora"\n'
            "---FREQ_SEP---\n"
            "INIT=systemd\n"
            "PKG=dnf\n"
            "PKG=yum\n"
            "HAS_BASH=1\n"
            "HAS_DOCKER=0\n"
            "x86_64\n"
        )
        rp = RemotePlatform._parse("rocky-host", output)
        self.assertIsNotNone(rp)
        self.assertEqual(rp.os_id, "rocky")
        self.assertEqual(rp.os_family, "rhel")
        self.assertEqual(rp.pkg_manager, "dnf")  # first match wins

    def test_parse_alpine_output(self):
        from freq.core.remote_platform import RemotePlatform
        output = (
            'ID=alpine\nVERSION_ID=3.20\nPRETTY_NAME="Alpine Linux v3.20"\n'
            "---FREQ_SEP---\n"
            "INIT=openrc\n"
            "PKG=apk\n"
            "HAS_BASH=0\n"
            "HAS_DOCKER=1\n"
            "aarch64\n"
        )
        rp = RemotePlatform._parse("alpine-host", output)
        self.assertIsNotNone(rp)
        self.assertEqual(rp.os_id, "alpine")
        self.assertEqual(rp.os_family, "alpine")
        self.assertEqual(rp.init_system, "openrc")
        self.assertEqual(rp.pkg_manager, "apk")
        self.assertFalse(rp.has_bash)
        self.assertEqual(rp.arch, "aarch64")

    def test_parse_bad_output(self):
        from freq.core.remote_platform import RemotePlatform
        rp = RemotePlatform._parse("bad", "garbage data no separator")
        self.assertIsNone(rp)


class TestPackages(unittest.TestCase):
    """Test package manager abstraction."""

    def test_install_cmd_apt(self):
        from freq.core.packages import install_cmd
        cmd = install_cmd("lldpd", "apt")
        self.assertEqual(cmd, "apt install -y lldpd")

    def test_install_cmd_dnf(self):
        from freq.core.packages import install_cmd
        cmd = install_cmd("lldpd", "dnf")
        self.assertEqual(cmd, "dnf install -y lldpd")

    def test_install_cmd_pacman(self):
        from freq.core.packages import install_cmd
        cmd = install_cmd("lldpd", "pacman")
        self.assertEqual(cmd, "pacman -S --noconfirm lldpd")

    def test_install_cmd_apk(self):
        from freq.core.packages import install_cmd
        cmd = install_cmd("lldpd", "apk")
        self.assertEqual(cmd, "apk add lldpd")

    def test_query_installed_apt(self):
        from freq.core.packages import query_installed_cmd
        cmd = query_installed_cmd("openssh-server", "apt")
        self.assertIn("dpkg", cmd)

    def test_query_installed_dnf(self):
        from freq.core.packages import query_installed_cmd
        cmd = query_installed_cmd("openssh-server", "dnf")
        self.assertIn("rpm", cmd)

    def test_reboot_required_apt(self):
        from freq.core.packages import reboot_required_cmd
        cmd = reboot_required_cmd("apt")
        self.assertIn("reboot-required", cmd)

    def test_reboot_required_dnf(self):
        from freq.core.packages import reboot_required_cmd
        cmd = reboot_required_cmd("dnf")
        self.assertIn("needs-restarting", cmd)

    def test_install_hint_debian(self):
        from freq.core.packages import install_hint
        hint = install_hint("sshpass", os_family="debian")
        self.assertEqual(hint, "apt install sshpass")

    def test_install_hint_rhel(self):
        from freq.core.packages import install_hint
        hint = install_hint("sshpass", os_family="rhel")
        self.assertEqual(hint, "dnf install sshpass")

    def test_install_hint_alpine(self):
        from freq.core.packages import install_hint
        hint = install_hint("sshpass", os_family="alpine")
        self.assertEqual(hint, "apk add sshpass")

    def test_resolve_pkg_name_auditd(self):
        from freq.core.packages import resolve_pkg_name
        self.assertEqual(resolve_pkg_name("auditd", "apt"), "auditd")
        self.assertEqual(resolve_pkg_name("auditd", "dnf"), "audit")
        self.assertEqual(resolve_pkg_name("auditd", "pacman"), "audit")

    def test_resolve_unknown_pkg(self):
        from freq.core.packages import resolve_pkg_name
        self.assertEqual(resolve_pkg_name("foo-bar", "apt"), "foo-bar")

    def test_unknown_pkg_manager(self):
        from freq.core.packages import install_cmd
        cmd = install_cmd("foo", "nonexistent")
        self.assertIn("Unknown", cmd)

    def test_all_managers_have_install(self):
        from freq.core.packages import install_cmd
        for mgr in ["apt", "dnf", "yum", "pacman", "zypper", "apk", "xbps", "pkg", "emerge"]:
            cmd = install_cmd("testpkg", mgr)
            self.assertNotIn("Unknown", cmd, f"{mgr} missing install command")


class TestServices(unittest.TestCase):
    """Test service manager abstraction."""

    def test_systemd_start(self):
        from freq.core.services import service_cmd
        cmd = service_cmd("start", "sshd", "systemd")
        self.assertEqual(cmd, "systemctl start sshd")

    def test_openrc_restart(self):
        from freq.core.services import service_cmd
        cmd = service_cmd("restart", "sshd", "openrc")
        self.assertEqual(cmd, "rc-service sshd restart")

    def test_runit_stop(self):
        from freq.core.services import service_cmd
        cmd = service_cmd("stop", "nginx", "runit")
        self.assertEqual(cmd, "sv stop nginx")

    def test_freebsd_status(self):
        from freq.core.services import service_cmd
        cmd = service_cmd("status", "sshd", "rc.d")
        self.assertEqual(cmd, "service sshd status")

    def test_enable_systemd(self):
        from freq.core.services import service_enable_cmd
        cmd = service_enable_cmd("nginx", "systemd")
        self.assertEqual(cmd, "systemctl enable nginx")

    def test_enable_openrc(self):
        from freq.core.services import service_enable_cmd
        cmd = service_enable_cmd("nginx", "openrc")
        self.assertIn("rc-update add", cmd)

    def test_disable_systemd(self):
        from freq.core.services import service_enable_cmd
        cmd = service_enable_cmd("nginx", "systemd", enable=False)
        self.assertEqual(cmd, "systemctl disable nginx")

    def test_is_active_systemd(self):
        from freq.core.services import is_active_cmd
        cmd = is_active_cmd("nginx", "systemd")
        self.assertIn("is-active", cmd)

    def test_logs_systemd(self):
        from freq.core.services import service_logs_cmd
        cmd = service_logs_cmd("nginx", "systemd", lines=100)
        self.assertIn("journalctl", cmd)
        self.assertIn("100", cmd)

    def test_logs_openrc(self):
        from freq.core.services import service_logs_cmd
        cmd = service_logs_cmd("nginx", "openrc", lines=50)
        self.assertIn("tail", cmd)
        self.assertIn("50", cmd)

    def test_sshd_name_resolution_debian(self):
        """On Debian-family systemd, sshd should resolve to 'ssh'."""
        from freq.core.services import _resolve_service_name
        name = _resolve_service_name("sshd", "systemd", os_family="debian")
        self.assertEqual(name, "ssh")

    def test_sshd_name_resolution_rhel(self):
        """On RHEL-family systemd, sshd stays 'sshd'."""
        from freq.core.services import _resolve_service_name
        name = _resolve_service_name("sshd", "systemd", os_family="rhel")
        self.assertEqual(name, "sshd")

    def test_cron_name_resolution_rhel(self):
        """On RHEL-family systemd, cron should resolve to 'crond'."""
        from freq.core.services import _resolve_service_name
        name = _resolve_service_name("cron", "systemd", os_family="rhel")
        self.assertEqual(name, "crond")

    def test_list_services_systemd(self):
        from freq.core.services import list_services_cmd
        cmd = list_services_cmd("systemd")
        self.assertIn("systemctl", cmd)

    def test_all_init_systems_have_service_cmd(self):
        from freq.core.services import service_cmd
        for init in ["systemd", "openrc", "runit", "sysvinit", "rc.d"]:
            cmd = service_cmd("status", "test", init)
            self.assertNotIn("Unknown", cmd, f"{init} missing service command")


if __name__ == "__main__":
    unittest.main()
