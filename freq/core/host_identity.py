"""Canonical host identity helpers shared by discovery consumers."""

import ipaddress
import re


def is_docker_bridge_ip(ip) -> bool:
    """Return whether *ip* is a valid IPv4 address in 172.17-31/16."""
    try:
        address = ipaddress.IPv4Address(ip)
    except (ipaddress.AddressValueError, TypeError):
        return False
    first, second, _third, _fourth = address.packed
    return first == 172 and 17 <= second <= 31


def _physical_ip_sort_key(ip: str):
    try:
        return tuple(int(part) for part in str(ip or "").split("."))
    except ValueError:
        return (999, 999, 999, 999)


def _generic_physical_label(label, dtype):
    label = str(label or "").strip().lower()
    dtype = str(dtype or "").strip().lower()
    if not label:
        return True
    if label == dtype:
        return True
    if re.match(r"^(bmc|idrac|ilo|ipmi)[-_]?\d+$", label):
        return True
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", label):
        return True
    return False


def _bmc_display_prefix(dtype):
    dtype = str(dtype or "").strip().lower()
    if dtype == "idrac":
        return "iDRAC"
    if dtype == "ilo":
        return "iLO"
    if dtype == "ipmi":
        return "IPMI"
    return "BMC"


def _node_display_name(name):
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name or "").strip()).strip("-_.")
    return cleaned.upper()


def operator_physical_display_label(cfg, dev, identity_label=""):
    """Derive the operator-facing label for a physical fleet device."""
    display_name = getattr(dev, "display_name", "") or ""
    if display_name:
        return display_name
    dtype = (getattr(dev, "device_type", "") or "").strip().lower()
    label = getattr(dev, "label", "") or ""
    if not _generic_physical_label(label, dtype):
        return label
    if identity_label:
        return identity_label
    if dtype in {"idrac", "bmc", "ilo", "ipmi"}:
        prefix = _bmc_display_prefix(dtype)
        fb = getattr(cfg, "fleet_boundaries", None)
        physical = getattr(fb, "physical", {}) if fb else {}
        bmc_devices = [
            item
            for item in physical.values()
            if (getattr(item, "device_type", "") or "").strip().lower()
            in {"idrac", "bmc", "ilo", "ipmi"}
            and (getattr(item, "scope", "core") or "core").strip().lower() != "lab"
        ]
        bmc_devices.sort(
            key=lambda item: (
                _physical_ip_sort_key(getattr(item, "ip", "")),
                getattr(item, "key", ""),
            )
        )

        pve_nodes = getattr(fb, "pve_nodes", {}) if fb else {}
        node_items = [(name, getattr(node, "ip", "")) for name, node in pve_nodes.items()]
        if not node_items:
            names = list(getattr(cfg, "pve_node_names", []) or [])
            for idx, ip in enumerate(getattr(cfg, "pve_nodes", []) or []):
                node_items.append(
                    (
                        names[idx] if idx < len(names) and names[idx] else f"pve{idx + 1:02d}",
                        ip,
                    )
                )
        node_items.sort(key=lambda item: (_physical_ip_sort_key(item[1]), item[0]))

        dev_ip = getattr(dev, "ip", "") or ""
        dev_idx = next(
            (
                idx
                for idx, item in enumerate(bmc_devices)
                if item is dev or (getattr(item, "ip", "") or "") == dev_ip
            ),
            -1,
        )
        if 0 <= dev_idx < len(node_items):
            return f"{prefix}-{_node_display_name(node_items[dev_idx][0])}"

        fallback = getattr(dev, "hostname", "") or getattr(dev, "service_tag", "") or ""
        if fallback:
            return f"{prefix}-{_node_display_name(fallback)}"
        if dev_ip:
            return f"{prefix}-{dev_ip.rsplit('.', 1)[-1]}"
    return label


def physical_display_name_for_mapping(dev: dict, all_physical: dict, all_pve: dict, cfg=None) -> str:
    """Derive a persisted operator display name from dictionary-form discovery data."""
    if not isinstance(dev, dict):
        return ""
    existing = str(dev.get("display_name") or dev.get("name") or "").strip()
    if existing:
        return existing
    dtype = str(dev.get("type") or "unknown").strip().lower()
    label = str(dev.get("label") or "").strip()
    if not _generic_physical_label(label, dtype):
        return ""

    if dtype in {"idrac", "bmc", "ilo", "ipmi"}:
        prefix = _bmc_display_prefix(dtype)
        bmc_items = [
            (key, item)
            for key, item in (all_physical or {}).items()
            if isinstance(item, dict)
            and str(item.get("type") or "").strip().lower() in {"idrac", "bmc", "ilo", "ipmi"}
            and str(item.get("scope") or "core").strip().lower() != "lab"
        ]
        bmc_items.sort(
            key=lambda item: (
                _physical_ip_sort_key(item[1].get("ip", "")),
                str(item[0]),
            )
        )

        node_items = []
        for key, item in (all_pve or {}).items():
            if isinstance(item, dict):
                node_items.append((str(key), item.get("ip", "")))
        if not node_items and cfg is not None:
            names = list(getattr(cfg, "pve_node_names", []) or [])
            ips = list(getattr(cfg, "pve_nodes", []) or [])
            for idx, ip in enumerate(ips):
                node_items.append(
                    (
                        names[idx] if idx < len(names) and names[idx] else f"pve{idx + 1:02d}",
                        ip,
                    )
                )
        node_items.sort(key=lambda item: (_physical_ip_sort_key(item[1]), item[0]))

        dev_ip = str(dev.get("ip") or "")
        dev_key = next(
            (
                key
                for key, item in bmc_items
                if item is dev or str(item.get("ip") or "") == dev_ip
            ),
            "",
        )
        dev_idx = next((idx for idx, (key, _item) in enumerate(bmc_items) if key == dev_key), -1)
        if 0 <= dev_idx < len(node_items):
            return f"{prefix}-{_node_display_name(node_items[dev_idx][0])}"

        hostname = str(dev.get("hostname") or dev.get("service_tag") or "").strip()
        if hostname:
            return f"{prefix}-{_node_display_name(hostname)}"
        if dev_ip:
            return f"{prefix}-{dev_ip.rsplit('.', 1)[-1]}"

    return ""
