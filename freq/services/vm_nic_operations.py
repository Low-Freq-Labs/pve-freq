"""Sequential NIC command receipts; no guest-state or durable operation claim."""

import re
import time

from freq.services.cloud_init_legacy_inputs import InvalidNetworkIntent, legacy_static_ipv4
from freq.services.cloud_init_ipconfig_patch import plan_ipv4_option


def parse_config(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Configuration unavailable")
    config = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key) or key in config:
            raise ValueError("Configuration ambiguous")
        if key.startswith(("net", "ipconfig")) and not re.fullmatch(r"(net|ipconfig)([0-9]|[12][0-9]|3[01])", key):
            raise ValueError("NIC identity ambiguous")
        config[key] = value.strip()
    if not config:
        raise ValueError("Configuration unavailable")
    return config


def execute(vmid, action, request, run, build_net):
    """run(argv, timeout) returns a transport result; every dispatch is recorded."""
    result = dict(
        schema="vm-nic-result-v1",
        action=action,
        vmid=vmid,
        request=request,
        ok=False,
        discovery="not_requested",
        steps=[],
        effects="not_attempted",
        configured_state_verified=False,
        guest_state_verified=False,
        durable=False,
        retry_authorized=False,
        observed_at=time.time(),
    )

    if action == "change-ip" and request.get("vlan") not in (None, ""):
        result["error"] = "Address-only edits cannot change VLAN or NIC hardware settings"
        return result

    # Validate request DATA before any transport read or mutation. Preserve the
    # original request in the receipt and canonicalize only a local copy.
    if action in ("add-nic", "update-nic", "change-ip"):
        address = request.get("ip")
        gateway = request.get("gw")
        if address is None or address == "":
            if action != "update-nic" or not (gateway is None or gateway == ""):
                result["error"] = "NIC edits require an explicit IPv4 CIDR with any gateway"
                return result
        else:
            try:
                address, gateway = legacy_static_ipv4(address, gateway)
            except InvalidNetworkIntent:
                result["error"] = "NIC edits require an explicit valid IPv4 CIDR and optional on-link gateway"
                return result
            request = dict(request, ip=address, gw=gateway)

    def command(argv, timeout):
        try:
            value = run(argv, timeout)
            code = value.returncode
            if type(code) is not int:
                return "unknown", None
            return ("acknowledged" if code == 0 else "failed"), value.stdout
        except Exception:
            return "unknown", None

    config = {}
    if action in ("clear-nics", "delete-nic", "add-nic", "update-nic", "change-ip"):
        status, text = command(("qm", "config", str(vmid)), 15)
        if status != "acknowledged":
            result.update(discovery="unavailable", error="Configuration discovery not confirmed")
            return result
        try:
            config = parse_config(text)
        except ValueError:
            result.update(discovery="unavailable", error="Configuration discovery ambiguous")
            return result
        result["discovery"] = "observed"

    commands = []

    def step(key, verb, value=None):
        argv = (
            ("qm", "set", str(vmid), "--delete", key)
            if verb == "delete"
            else ("qm", "set", str(vmid), "--" + key, value)
        )
        commands.append(argv)
        result["steps"].append(dict(key=key, operation=verb, status="not_attempted"))

    if action == "clear-nics":
        for key in sorted(config):
            if re.fullmatch(r"(net|ipconfig)\d+", key):
                step(key, "delete")
    elif action == "delete-nic":
        net, ip = "net" + str(request["nic"]), "ipconfig" + str(request["nic"])
        if net not in config:
            result.update(error="Requested NIC absent from observed configuration")
            return result
        step(net, "delete")
        if ip in config:
            step(ip, "delete")
    else:
        index = request.get("nic")
        if action == "add-nic":
            indexes = [int(re.search(r"\d+$", k)[0]) for k in config if re.fullmatch(r"(net|ipconfig)\d+", k)]
            index = max(indexes, default=-1) + 1
            if index > 31:
                result.update(error="No qualified next NIC index")
                return result
        net, ip = "net" + str(index), "ipconfig" + str(index)
        result["nic"] = net
        if action in ("update-nic", "change-ip") and net not in config:
            result.update(error="Requested NIC absent from observed configuration")
            return result
        ip_value = None
        if request.get("ip"):
            try:
                ip_value = plan_ipv4_option(config, index, request["ip"], request.get("gw"))
            except InvalidNetworkIntent:
                result.update(error="Address configuration is ambiguous, unsupported or conflicts with retained routes")
                return result
        if action != "change-ip":
            tag = ",tag=" + request["vlan"] if request.get("vlan") else ""
            value = "virtio,bridge=" + request["bridge"] + tag
            if action == "update-nic":
                value = build_net(config[net], request["bridge"], request["vlan"], request["firewall"])
            step(net, "set", value)
        if ip_value is not None:
            step(ip, "set", ip_value)

    for index, argv in enumerate(commands):
        result["effects"] = "unknown"
        status, _ = command(argv, 30)
        result["steps"][index]["status"] = status
        if status != "acknowledged":
            result["error"] = "Command result unconfirmed; remaining steps not attempted"
            return result
    result.update(ok=True, error="")
    return result
