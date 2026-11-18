"""Pure, conservative QEMU configured-network projection. SOURCE DRAFT.

No provider request, generated MAC, DHCP address, source time or authority.
The caller owns original acquisition, deployed compatibility and final admission.
"""

import ipaddress
import re

from .guest_network import Reader, Refused as BodyRefused


MODELS = frozenset(("e1000", "e1000-82540em", "e1000-82544gc", "e1000-82545em",
                    "e1000e", "i82551", "i82557b", "i82559er", "ne2k_isa",
                    "ne2k_pci", "pcnet", "rtl8139", "virtio", "vmxnet3"))


class Refused(ValueError):
    pass


def require(condition):
    if not condition:
        raise Refused("Guest configuration unavailable")


def unsigned_text(value, maximum, minimum=0):
    require(type(value) is str and re.fullmatch(r"0|[1-9][0-9]*", value) is not None)
    bound = str(maximum)
    require(len(value) < len(bound) or (len(value) == len(bound) and value <= bound))
    result = int(value)
    require(result >= minimum)
    return result


def properties(value, allow_bare_model=False):
    require(type(value) is str and len(value) <= 4096 and value.isascii())
    require(all(33 <= ord(char) <= 126 and char not in "\\\"'" for char in value))
    require(value.count(",") < 32)
    if value == "":
        require(not allow_bare_model)
        return {}
    result = {}
    for token in value.split(","):
        if "=" not in token:
            require(allow_bare_model and token in MODELS)
            key, item = "model", token
        else:
            require(token.count("=") == 1)
            key, item = token.split("=")
            require(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key) is not None and item != "")
        require(key not in result)
        result[key] = item
    return result


def literal(value, family):
    require(type(value) is str and 1 <= len(value) <= 45 and value.isascii())
    require("%" not in value and "/" not in value)
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        raise Refused("Guest configuration unavailable") from None
    require(parsed.version == (4 if family == "ipv4" else 6))
    return value


def configured_addresses(value):
    fields = properties(value)
    require(set(fields) <= {"ip", "gw", "ip6", "gw6"})
    addresses, gateways, static = [], [], set()
    for key, item in fields.items():
        if key not in ("ip", "ip6"):
            continue
        family = "ipv4" if key == "ip" else "ipv6"
        if item == "dhcp" or (key == "ip6" and item == "auto"):
            continue
        require(item.count("/") == 1)
        address, prefix = item.split("/")
        addresses.append({"family": family, "address": literal(address, family),
                          "prefix": unsigned_text(prefix, 32 if key == "ip" else 128)})
        static.add(key)
    for key, item in fields.items():
        if key not in ("gw", "gw6"):
            continue
        associated = "ip" if key == "gw" else "ip6"
        require(associated in static)
        family = "ipv4" if key == "gw" else "ipv6"
        gateways.append({"family": family, "address": literal(item, family)})
    return addresses, gateways


def nic(value):
    fields = properties(value, allow_bare_model=True)
    selected = {}
    for key, item in fields.items():
        if key in MODELS:
            require("model" not in selected and "macaddr" not in selected)
            selected["model"], selected["macaddr"] = key, item
        elif key in ("model", "macaddr", "bridge", "tag"):
            require(key not in selected)
            selected[key] = item
        elif key in ("firewall", "link_down", "host-tunnel"):
            require(item in ("0", "1"))
        elif key == "queues":
            unsigned_text(item, 64)
        elif key == "mtu":
            unsigned_text(item, 65520, 1)
        elif key == "rate":
            # Deliberately supported finite decimal subset; no exponent, sign,
            # float conversion or retained policy assertion from ignored rate.
            require(len(item) <= 64 and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", item) is not None)
        elif key == "trunks":
            require(item.count(";") < 64)
            for interval in item.split(";"):
                require(interval.count("-") <= 1)
                limits = interval.split("-")
                low = unsigned_text(limits[0], 4094, 1)
                if len(limits) == 2:
                    require(unsigned_text(limits[1], 4094, 1) >= low)
        else:
            raise Refused("Guest configuration unavailable")
    require(selected.get("model") in MODELS)
    mac = selected.get("macaddr")
    require(mac is None or re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac) is not None)
    bridge = selected.get("bridge")
    require(bridge is None or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", bridge) is not None)
    # Upstream tag is 1..4094; application schema also admits zero from other
    # producers, which does not enlarge this conservative provider grammar.
    vlan = unsigned_text(selected["tag"], 4094, 1) if "tag" in selected else None
    return {"model": selected["model"], "mac": mac, "bridge": bridge, "vlan": vlan}


def decode_guest_config(body):
    """Return internal NIC rows, preserving source NIC and address order.

    This parses a selected source's complete config response only. It does not
    choose that source or a guest, equate MACs, acquire data, or publish output.
    """
    try:
        root = Reader(body).read()
        require(type(root) is dict and set(root) == {"data"} and type(root["data"]) is dict)
        nets, ips = {}, {}
        for key, value in root["data"].items():
            prefix = "ipconfig" if key.startswith("ipconfig") else "net" if key.startswith("net") else None
            suffix = key[len(prefix):] if prefix is not None else ""
            if prefix is not None and suffix.isascii() and suffix.isdigit():
                index = unsigned_text(suffix, 31)
                require(type(value) is str)
                if prefix == "net":
                    nets[index] = (key, nic(value))
                else:
                    ips[index] = configured_addresses(value)
            else:
                # Full reader charges even unknown scalar keys/values; do not
                # pass through disks, SSH keys, descriptions or other config.
                require(type(value) not in (dict, list))
        require(set(ips) <= set(nets))
        result = []
        for index, (key, row) in nets.items():
            addresses, gateways = ips.get(index, ([], []))
            result.append({"key": key, **row, "addresses": addresses, "gateways": gateways})
        return result
    except BodyRefused:
        raise Refused("Guest configuration unavailable") from None
