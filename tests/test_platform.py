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
            "centos", "rhel", "almalinux", "ol", "amzn",
            "opensuse-tumbleweed", "opensuse-leap",
            "manjaro", "void", "linux",
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

    CASES = (
        ("install-apt", "install", ("lldpd", "apt"), "equal", "apt install -y lldpd"),
        ("install-dnf", "install", ("lldpd", "dnf"), "equal", "dnf install -y lldpd"),
        ("install-pacman", "install", ("lldpd", "pacman"), "equal", "pacman -S --noconfirm lldpd"),
        ("install-apk", "install", ("lldpd", "apk"), "equal", "apk add lldpd"),
        ("query-apt", "query", ("openssh-server", "apt"), "contains", "dpkg"),
        ("query-dnf", "query", ("openssh-server", "dnf"), "contains", "rpm"),
        ("reboot-apt", "reboot", ("apt",), "contains", "reboot-required"),
        ("reboot-dnf", "reboot", ("dnf",), "contains", "needs-restarting"),
        ("hint-debian", "hint", ("sshpass", "debian"), "equal", "apt install sshpass"),
        ("hint-rhel", "hint", ("sshpass", "rhel"), "equal", "dnf install sshpass"),
        ("hint-alpine", "hint", ("sshpass", "alpine"), "equal", "apk add sshpass"),
        ("resolve-auditd-apt", "resolve", ("auditd", "apt"), "equal", "auditd"),
        ("resolve-auditd-dnf", "resolve", ("auditd", "dnf"), "equal", "audit"),
        ("resolve-auditd-pacman", "resolve", ("auditd", "pacman"), "equal", "audit"),
        ("resolve-unknown", "resolve", ("foo-bar", "apt"), "equal", "foo-bar"),
        ("install-unknown-manager", "install", ("foo", "nonexistent"), "contains", "Unknown"),
        ("supported-install-apt", "install", ("testpkg", "apt"), "not_contains", "Unknown"),
        ("supported-install-dnf", "install", ("testpkg", "dnf"), "not_contains", "Unknown"),
        ("supported-install-yum", "install", ("testpkg", "yum"), "not_contains", "Unknown"),
        ("supported-install-pacman", "install", ("testpkg", "pacman"), "not_contains", "Unknown"),
        ("supported-install-zypper", "install", ("testpkg", "zypper"), "not_contains", "Unknown"),
        ("supported-install-apk", "install", ("testpkg", "apk"), "not_contains", "Unknown"),
        ("supported-install-xbps", "install", ("testpkg", "xbps"), "not_contains", "Unknown"),
        ("supported-install-pkg", "install", ("testpkg", "pkg"), "not_contains", "Unknown"),
        ("supported-install-emerge", "install", ("testpkg", "emerge"), "not_contains", "Unknown"),
    )

    def test_package_policy_matrix(self):
        from freq.core.packages import (
            install_cmd,
            install_hint,
            query_installed_cmd,
            reboot_required_cmd,
            resolve_pkg_name,
        )

        operations = {
            "install": install_cmd,
            "query": query_installed_cmd,
            "reboot": reboot_required_cmd,
            "hint": install_hint,
            "resolve": resolve_pkg_name,
        }
        self.assertEqual(len(self.CASES), 25)
        case_ids = tuple(case_id for case_id, *_rest in self.CASES)
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for case_id, operation, args, comparison, expected in self.CASES:
            with self.subTest(case=case_id, operation=operation):
                actual = operations[operation](*args)
                if comparison == "equal":
                    self.assertEqual(actual, expected)
                elif comparison == "contains":
                    self.assertIn(expected, actual)
                else:
                    self.assertNotIn(expected, actual)

class TestServices(unittest.TestCase):
    """Test service manager abstraction."""

    CASES = (
        ("action-systemd-start", "action", ("start", "sshd", "systemd"), "equal", "systemctl start sshd"),
        ("action-openrc-restart", "action", ("restart", "sshd", "openrc"), "equal", "rc-service sshd restart"),
        ("action-runit-stop", "action", ("stop", "nginx", "runit"), "equal", "sv stop nginx"),
        ("action-rcd-status", "action", ("status", "sshd", "rc.d"), "equal", "service sshd status"),
        ("enable-systemd", "enable", ("nginx", "systemd"), "equal", "systemctl enable nginx"),
        ("enable-openrc", "enable", ("nginx", "openrc"), "contains", "rc-update add"),
        ("disable-systemd", "enable", ("nginx", "systemd", False), "equal", "systemctl disable nginx"),
        ("active-systemd", "active", ("nginx", "systemd"), "contains", "is-active"),
        ("logs-systemd", "logs", ("nginx", "systemd", 100), "contains_all", ("journalctl", "100")),
        ("logs-openrc", "logs", ("nginx", "openrc", 50), "contains_all", ("tail", "50")),
        ("name-sshd-debian", "name", ("sshd", "systemd", "debian"), "equal", "ssh"),
        ("name-sshd-rhel", "name", ("sshd", "systemd", "rhel"), "equal", "sshd"),
        ("name-cron-rhel", "name", ("cron", "systemd", "rhel"), "equal", "crond"),
        ("list-systemd", "list", ("systemd",), "contains", "systemctl"),
        ("supported-action-systemd", "action", ("status", "test", "systemd"), "not_contains", "Unknown"),
        ("supported-action-openrc", "action", ("status", "test", "openrc"), "not_contains", "Unknown"),
        ("supported-action-runit", "action", ("status", "test", "runit"), "not_contains", "Unknown"),
        ("supported-action-sysvinit", "action", ("status", "test", "sysvinit"), "not_contains", "Unknown"),
        ("supported-action-rcd", "action", ("status", "test", "rc.d"), "not_contains", "Unknown"),
    )

    def test_service_policy_matrix(self):
        from freq.core.services import (
            _resolve_service_name,
            is_active_cmd,
            list_services_cmd,
            service_cmd,
            service_enable_cmd,
            service_logs_cmd,
        )

        operations = {
            "action": service_cmd,
            "enable": service_enable_cmd,
            "active": is_active_cmd,
            "logs": service_logs_cmd,
            "name": _resolve_service_name,
            "list": list_services_cmd,
        }
        self.assertEqual(len(self.CASES), 19)
        case_ids = tuple(case_id for case_id, *_rest in self.CASES)
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for case_id, operation, args, comparison, expected in self.CASES:
            with self.subTest(case=case_id, operation=operation):
                actual = operations[operation](*args)
                if comparison == "equal":
                    self.assertEqual(actual, expected)
                elif comparison == "contains":
                    self.assertIn(expected, actual)
                elif comparison == "contains_all":
                    for token in expected:
                        self.assertIn(token, actual)
                else:
                    self.assertNotIn(expected, actual)

if __name__ == "__main__":
    unittest.main()
