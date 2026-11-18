"""Pure proposed guest application-wire projection; no request or native authority.

Input is an internal built-in object, never a provider body. The original owner
must perform its own lifetime/currentness/recipient admission after this returns.
All limits are logical data bounds, not physical process or clock containment.
"""

import datetime
import ipaddress
import json
import math
import re


class Refused(ValueError):
    """Fixed refusal without provider or caller data in the exception text."""


def require(ok):
    if not ok:
        raise Refused("Guest wire unavailable")


def obj(value, keys):
    require(type(value) is dict and len(value) == len(keys))
    require(all(type(key) is str for key in value))
    require(set(value) == set(keys))
    return value


def rows(value, limit):
    require(type(value) is list and len(value) <= limit)
    return value


def integer(value, low, high):
    require(type(value) is int and low <= value <= high)
    return value


class Projection:
    def __init__(self):
        self.string_bytes = 0

    def text(self, value, limit, nonempty=False):
        require(type(value) is str and len(value) <= limit)
        require(not nonempty or len(value) > 0)
        try:
            size = len(value.encode("utf-8", "strict"))
        except UnicodeEncodeError:
            raise Refused("Guest wire unavailable") from None
        require(size <= limit)
        self.string_bytes += size
        require(self.string_bytes <= 65536)
        return value

    def maybe_text(self, value, limit):
        return None if value is None else self.text(value, limit)

    def timestamp(self, value):
        value = self.text(value, 24)
        require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", value) is not None)
        try:
            datetime.datetime(int(value[0:4]), int(value[5:7]), int(value[8:10]),
                              int(value[11:13]), int(value[14:16]), int(value[17:19]),
                              int(value[20:23]) * 1000, tzinfo=datetime.timezone.utc)
        except ValueError:
            raise Refused("Guest wire unavailable") from None
        return value

    def reference(self, value):
        value = self.text(value, 64)
        require(re.fullmatch(r"[0-9a-f]{64}", value) is not None)
        return value

    def node(self, value):
        value = self.text(value, 64)
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,63}", value) is not None)
        return value

    def kind(self, value):
        value = self.text(value, 4)
        require(value in ("qemu", "lxc"))
        return value

    def address(self, value, prefix):
        keys = ("family", "address", "prefix") if prefix else ("family", "address")
        obj(value, keys)
        family = self.text(value["family"], 4)
        require(family in ("ipv4", "ipv6"))
        address = self.text(value["address"], 45, True)
        require(address.isascii() and "%" not in address and "/" not in address)
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            raise Refused("Guest wire unavailable") from None
        require(parsed.version == (4 if family == "ipv4" else 6))
        # Representation remains exactly the reviewed producer's string. This
        # projection validates it; it neither chooses nor rewrites an address.
        result = {"family": family, "address": address}
        if prefix:
            result["prefix"] = integer(value["prefix"], 0, 32 if family == "ipv4" else 128)
        return result

    def configured(self, value):
        result, seen = [], set()
        for row in rows(value, 32):
            obj(row, ("key", "model", "mac", "bridge", "vlan", "addresses", "gateways"))
            key = self.text(row["key"], 5)
            require(re.fullmatch(r"net(?:[0-9]|[12][0-9]|3[01])", key) is not None and key not in seen)
            seen.add(key)
            result.append({"key": key, "model": self.maybe_text(row["model"], 128),
                           "mac": self.maybe_text(row["mac"], 128),
                           "bridge": self.maybe_text(row["bridge"], 128),
                           "vlan": None if row["vlan"] is None else integer(row["vlan"], 0, 4094),
                           "addresses": [self.address(a, True) for a in rows(row["addresses"], 16)],
                           "gateways": [self.address(a, False) for a in rows(row["gateways"], 2)]})
        return result

    def guest(self, value):
        result = []
        for row in rows(value, 64):
            obj(row, ("name", "mac", "addresses"))
            result.append({"name": self.text(row["name"], 128, True),
                           "mac": self.maybe_text(row["mac"], 128),
                           "addresses": [self.address(a, True) for a in rows(row["addresses"], 16)]})
        return result

    def status(self, value):
        obj(value, ("state", "cpu_fraction", "memory_used_bytes", "memory_limit_bytes"))
        cpu = value["cpu_fraction"]
        if cpu is not None:
            require(type(cpu) in (int, float))
            require(0 <= cpu <= 1 and (type(cpu) is int or math.isfinite(cpu)))
        return {"state": self.text(value["state"], 64, True), "cpu_fraction": cpu,
                "memory_used_bytes": None if value["memory_used_bytes"] is None else integer(value["memory_used_bytes"], 0, 9007199254740991),
                "memory_limit_bytes": None if value["memory_limit_bytes"] is None else integer(value["memory_limit_bytes"], 0, 9007199254740991)}

    def section(self, value, project, lxc):
        obj(value, ("outcome", "observed_at", "data"))
        outcome = self.text(value["outcome"], 11)
        require(outcome in ("reported", "unavailable", "unsupported"))
        require(not lxc or outcome == "unsupported")
        if outcome != "reported":
            require(value["observed_at"] is None and value["data"] is None)
            return {"outcome": outcome, "observed_at": None, "data": None}
        return {"outcome": outcome, "observed_at": self.timestamp(value["observed_at"]),
                "data": project(value["data"])}

    def target(self, value, inventory=False):
        keys = ("guest_ref", "node", "guest_kind", "vmid", "name") if inventory else ("source_label", "node", "guest_kind", "vmid", "name")
        obj(value, keys)
        result = {"node": self.node(value["node"]), "guest_kind": self.kind(value["guest_kind"]),
                  "vmid": integer(value["vmid"], 100, 999999999),
                  "name": self.maybe_text(value["name"], 256)}
        if inventory:
            result["guest_ref"] = self.reference(value["guest_ref"])
        else:
            result["source_label"] = self.text(value["source_label"], 256, True)
        return result

    def document(self, value):
        require(type(value) is dict and len(value) <= 7)
        require(all(type(key) is str for key in value))
        require(type(value.get("schema")) is int and value["schema"] == 1)
        kind = self.text(value.get("kind"), 17)
        if kind == "guest-unavailable":
            obj(value, ("schema", "kind"))
            return {"schema": 1, "kind": kind}
        if kind == "guest-sources":
            obj(value, ("schema", "kind", "sources", "completed_at"))
            sources, seen = [], set()
            for row in rows(value["sources"], 32):
                obj(row, ("source_ref", "label"))
                ref = self.reference(row["source_ref"])
                require(ref not in seen)
                seen.add(ref)
                sources.append({"source_ref": ref, "label": self.text(row["label"], 256, True)})
            return {"schema": 1, "kind": kind, "sources": sources,
                    "completed_at": self.timestamp(value["completed_at"])}
        if kind == "guest-inventory":
            obj(value, ("schema", "kind", "source_label", "observed_at", "completed_at", "guests"))
            guests, seen, refs = [], set(), set()
            for row in rows(value["guests"], 256):
                guest = self.target(row, True)
                key = (guest["node"], guest["guest_kind"], guest["vmid"])
                require(key not in seen and guest["guest_ref"] not in refs)
                seen.add(key)
                refs.add(guest["guest_ref"])
                guests.append(guest)
            return {"schema": 1, "kind": kind, "source_label": self.text(value["source_label"], 256, True),
                    "observed_at": self.timestamp(value["observed_at"]),
                    "completed_at": self.timestamp(value["completed_at"]), "guests": guests}
        require(kind == "guest-profile")
        obj(value, ("schema", "kind", "target", "completed_at", "status", "configured_network", "guest_network"))
        target = self.target(value["target"])
        lxc = target["guest_kind"] == "lxc"
        return {"schema": 1, "kind": kind, "target": target,
                "completed_at": self.timestamp(value["completed_at"]),
                "status": self.section(value["status"], self.status, lxc),
                "configured_network": self.section(value["configured_network"], self.configured, lxc),
                "guest_network": self.section(value["guest_network"], self.guest, lxc)}


def project_guest_wire(value):
    """Return an independent bounded UTF-8 byte string or fixed Refused.

    This does not parse raw JSON/provider data, mint selectors, consume a request,
    reserve original physical resources, acknowledge a modal or admit a result.
    Only exact built-in containers/scalars are accepted; no user serializer hooks.
    """
    projection = Projection()
    snapshot = projection.document(value)
    # Values were charged while validating. Charge every fixed object key too;
    # the contract's decoded-string budget includes keys and values alike.
    def charge_keys(node):
        if type(node) is dict:
            for key, child in node.items():
                projection.text(key, 64)
                charge_keys(child)
        elif type(node) is list:
            for child in node:
                charge_keys(child)
    charge_keys(snapshot)
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, sort_keys=True,
                               separators=(",", ":"))
    output = bytearray()
    for chunk in encoder.iterencode(snapshot):
        data = chunk.encode("utf-8", "strict")
        require(len(output) + len(data) <= 131072)
        output.extend(data)
    return bytes(output)
