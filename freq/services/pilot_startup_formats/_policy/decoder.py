"""Strict supplied-document full VM List projection; no original authority.

Earlier clone-only decoder is preserved. The syntax/structural modules remain
unchanged. This extension narrows selected tier names/actions and retains their
original order in the detached full-policy snapshot and bounded staged bytes.
"""
from .documents import document_events
from .lines import InvalidDocument
from .policy import build_policy


def _reject():
    raise InvalidDocument("Policy document unavailable")


def _text(value, maximum, selected=False):
    if type(value) is not str or len(value) > maximum:
        _reject()
    if selected and any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF
                        for c in value):
        _reject()


def _id(value, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= 9007199254740991:
        _reject()


_HOST_STRINGS = frozenset(("ip", "label", "type", "display_name", "name", "groups",
                           "hostname", "fqdn", "dns_name", "service_tag",
                           "identity_source"))


def decode_policy(hosts, fleet):
    """Fully exhaust and validate both supplied byte documents before return.

    Defaults describe syntactic absence in this restricted schema. They do not
    repair missing native storage or establish successful physical acquisition.
    Unrelated metadata is checked then discarded. Any failure aborts the pair.
    """
    result = {"categories": [], "hosts": [], "tiers": []}
    current = None
    selected = None
    endpoints = {}
    attempts = 0

    def flush():
        nonlocal selected, endpoints, attempts
        if selected is None:
            return
        if current == ("host",):
            amount = int(selected["managed"] and selected["htype"] != "pve"
                         and selected["vmid"] is not None)
            destination = result["hosts"]
        else:
            if len(endpoints) == 1:
                _reject()
            length = 0
            if endpoints:
                first, last = endpoints["range_start"], endpoints["range_end"]
                length = abs(last - first) + 1
                if length > 4096:
                    _reject()
                selected["range"] = [first, last]
            amount = len(selected["vmids"]) + length
            destination = result["categories"]
        if attempts + amount > 8192:
            _reject()
        attempts += amount
        destination.append(selected)
        selected = None
        endpoints = {}

    for document, number, event in document_events(hosts, fleet):
        if event[0] == "header":
            flush()
            current = event[1]
            if current == ("host",):
                selected = dict(managed=True, htype="linux", label="", vmid=None)
            elif current[0] == "categories":
                selected = dict(name=current[1], tier="probe", vmids=[], range=None)
            continue
        name, item = event[1:]
        if current == ("host",):
            if name in _HOST_STRINGS:
                maximum = 128 if name == "label" else 32 if name == "type" else 4096
                _text(item, maximum, name in ("label", "type"))
                if name in ("label", "type"):
                    selected["htype" if name == "type" else "label"] = item
            elif name == "managed":
                if type(item) is not bool:
                    _reject()
                selected["managed"] = item
            elif name == "vmid":
                _id(item, zero=True)
                selected["vmid"] = None if item == 0 else item
            elif name == "all_ips":
                if type(item) is not list:
                    _reject()
                for ip in item:
                    _text(ip, 4096)
            else:
                _reject()
        elif current[0] == "categories":
            if name in ("description", "tier"):
                _text(item, 32 if name == "tier" else 4096, name == "tier")
                if name == "tier":
                    selected["tier"] = item
            elif name == "vmids":
                if type(item) is not list:
                    _reject()
                for vmid in item:
                    _id(vmid)
                selected["vmids"] = item
            elif name in ("range_start", "range_end"):
                _id(item)
                endpoints[name] = item
            else:
                _reject()
        elif current == ("tiers",):
            _text(name, 32, True)
            if not name or type(item) is not list or len(item) > 64:
                _reject()
            for action in item:
                _text(action, 64, True)
            #Document owner rejects duplicate assignments before this event;
            #full supplied policy independently checks unique tier names.
            result["tiers"].append({"name": name, "actions": item})
        elif len(current) == 2:
            # Named infrastructure metadata cannot contain collections.
            if type(item) not in (str, bool, int):
                _reject()
        # Parent infrastructure inline values were validated by the scalar-only
        # inline parser and structural owner; they confer no policy membership.
    flush()
    #Fully validated syntactic absence may produce empty catalog/defaults.
    #Nothing here establishes successful original file acquisition or custody.
    return build_policy(result)
