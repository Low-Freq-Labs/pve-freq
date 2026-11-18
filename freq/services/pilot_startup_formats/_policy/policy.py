"""Disabled supplied VM List policy snapshot; no original source or authority.

Input must be exclusively owned native primitives for this synchronous call.
Logical work/byte bounds do not establish wall time, RSS or generation custody.
The original executor must enforce its one deadline and recheck before exposure.
Snapshot identity is a data type, never a provenance or admission credential.
"""

from collections import namedtuple

_MAX_ID = 9007199254740991
_HIDDEN = frozenset(("out_of_contract", "discovered_unowned", "inventory_only", "unowned"))
_VISIBLE = frozenset(("production", "lab", "infrastructure", "prod_media", "prod_other", "personal"))
_PRODUCTION = frozenset(("infrastructure", "prod_media", "prod_other", "production"))
_Snapshot = namedtuple("_Snapshot", "categories tiers visible hidden managed labels boundary encoded")


class InvalidPolicy(ValueError):
    pass


def _reject():
    raise InvalidPolicy("VM List supplied policy unavailable")


class _Budget:
    def __init__(self):
        self.characters = 0
        self.members = 0
        self.actions = 0

    def text(self, value, minimum, maximum):
        if type(value) is not str or not minimum <= len(value) <= maximum:
            _reject()
        self.characters += len(value)
        if self.characters > 524288:
            _reject()
        for char in value:
            code = ord(char)
            if code < 32 or code == 127 or 0xD800 <= code <= 0xDFFF:
                _reject()
        return value

    def members_add(self, count):
        self.members += count
        if self.members > 8192:
            _reject()


def _record(value, keys, budget):
    if type(value) is not dict or len(value) != len(keys):
        _reject()
    for key in value:
        budget.text(key, 1, 64)
    if frozenset(value) != keys:
        _reject()


def _array(value, maximum):
    if type(value) is not list or len(value) > maximum:
        _reject()
    return value


def _identity(value):
    if type(value) is not int or not 1 <= value <= _MAX_ID:
        _reject()
    return value


def _label(value):
    normalized = value.strip().lower().replace("_", "-")
    if len(normalized) > 128:
        _reject()
    return normalized


class _Stage:
    """Known grammar encoder. Reserve expansion before extending bounded buffer."""

    def __init__(self):
        self.body = bytearray()

    def put(self, chunk):
        if len(self.body) + len(chunk) > 1048576:
            _reject()
        self.body.extend(chunk)

    def string(self, value):
        self.put(b'"')
        for char in value:
            if char == '"':
                self.put(b'\\"')
            elif char == "\\":
                self.put(b"\\\\")
            else:
                # Validation already forbids controls/surrogates. Temporary<=4B.
                self.put(char.encode("utf-8"))
        self.put(b'"')

    def integer(self, value):
        # Exact safe positive integers were validated; temporary<=16B.
        self.put(str(value).encode("ascii"))


def _stage(categories, hosts, tiers):
    out = _Stage()
    out.put(b'{"categories":[')
    for index, (name, tier, ids, first, second) in enumerate(categories):
        if index:
            out.put(b",")
        out.put(b'{"name":')
        out.string(name)
        out.put(b',"tier":')
        out.string(tier)
        out.put(b',"vmids":[')
        for offset, vmid in enumerate(ids):
            if offset:
                out.put(b",")
            out.integer(vmid)
        out.put(b'],"range":')
        if first is None:
            out.put(b"null")
        else:
            out.put(b"[")
            out.integer(first)
            out.put(b",")
            out.integer(second)
            out.put(b"]")
        out.put(b"}")
    out.put(b'],"hosts":[')
    for index, (managed, kind, label, vmid) in enumerate(hosts):
        if index:
            out.put(b",")
        out.put(b'{"managed":')
        out.put(b"true" if managed else b"false")
        out.put(b',"htype":')
        out.string(kind)
        out.put(b',"label":')
        out.string(label)
        out.put(b',"vmid":')
        if vmid is None:
            out.put(b"null")
        else:
            out.integer(vmid)
        out.put(b"}")
    out.put(b'],"tiers":[')
    for index, (name, actions) in enumerate(tiers):
        if index:
            out.put(b",")
        out.put(b'{"name":')
        out.string(name)
        out.put(b',"actions":[')
        for offset, action in enumerate(actions):
            if offset:
                out.put(b",")
            out.string(action)
        out.put(b"]}")
    out.put(b"]}")
    return bytes(out.body)


def build_policy(value):
    """Validate, detach, stage full metadata, then construct bounded policy views."""
    budget = _Budget()
    _record(value, frozenset(("categories", "hosts", "tiers")), budget)
    categories = _array(value["categories"], 64)
    hosts = _array(value["hosts"], 512)
    tiers = _array(value["tiers"], 64)
    prepared, host_rows, tier_rows = [], [], []
    names = set()
    for category in categories:
        _record(category, frozenset(("name", "tier", "vmids", "range")), budget)
        name = budget.text(category["name"], 1, 64)
        tier = budget.text(category["tier"], 0, 32)
        if name in names:
            _reject()
        names.add(name)
        ids = _array(category["vmids"], 512)
        budget.members_add(len(ids))
        for vmid in ids:
            _identity(vmid)
        first = second = None
        span = category["range"]
        if span is not None:
            _array(span, 2)
            if len(span) != 2:
                _reject()
            first, second = _identity(span[0]), _identity(span[1])
            length = abs(first - second) + 1
            if length > 4096:
                _reject()
            budget.members_add(length)
        prepared.append((name, tier, tuple(ids), first, second))
    managed, labels = set(), set()
    for host in hosts:
        _record(host, frozenset(("managed", "htype", "label", "vmid")), budget)
        flag = host["managed"]
        if type(flag) is not bool:
            _reject()
        kind = budget.text(host["htype"], 0, 32)
        raw_label = budget.text(host["label"], 0, 128)
        label = _label(raw_label)
        vmid = host["vmid"]
        if vmid is not None:
            _identity(vmid)
        if flag and kind != "pve":
            if vmid is not None:
                budget.members_add(1)
                managed.add(vmid)
            if label:
                labels.add(label)
        host_rows.append((flag, kind, raw_label, vmid))
    names = set()
    for tier in tiers:
        _record(tier, frozenset(("name", "actions")), budget)
        name = budget.text(tier["name"], 1, 32)
        if name in names:
            _reject()
        names.add(name)
        actions = _array(tier["actions"], 64)
        budget.actions += len(actions)
        if budget.actions > 4096:
            _reject()
        for action in actions:
            budget.text(action, 0, 64)
        tier_rows.append((name, tuple(actions)))
    # All global membership/range charges precede any range expansion.
    encoded = _stage(prepared, host_rows, tier_rows)
    visible, hidden = set(), set()
    for name, tier, ids, first, second in prepared:
        target = None
        if name in _HIDDEN:
            target = hidden
        elif name != "templates" and (name in _VISIBLE or tier in ("operator", "admin")):
            target = visible
        if target is not None:
            target.update(ids)
            if first is not None:
                target.update(range(min(first, second), max(first, second) + 1))
    return _Snapshot(tuple(prepared), tuple(tier_rows), frozenset(visible),
                     frozenset(hidden), frozenset(managed), frozenset(labels),
                     bool(visible or hidden), encoded)


def _snapshot(value):
    if type(value) is not _Snapshot:
        _reject()


def visible(snapshot, vmid, observed_name=None):
    """No generated label input; caller must supply actual observed name or None."""
    _snapshot(snapshot)
    _identity(vmid)
    if observed_name is not None:
        _Budget().text(observed_name, 0, 128)
        observed_name = _label(observed_name)
    if vmid in snapshot.hidden:
        return False
    if vmid in snapshot.visible:
        return True
    if snapshot.boundary:
        return False
    return vmid in snapshot.managed or bool(observed_name and observed_name in snapshot.labels)


def describe(snapshot, vmid):
    """Return display category,tier,actions,production; never operation authority."""
    _snapshot(snapshot)
    _identity(vmid)
    category, tier = "unknown", "probe"
    for name, level, ids, first, second in snapshot.categories:
        # Deliberately preserve raw orientation here, unlike visibility spans.
        if vmid in ids or (first is not None and first <= vmid <= second):
            category, tier = name, level
            break
    actions = ("view",)
    for name, values in snapshot.tiers:
        if name == tier:
            actions = values
            break
    return category, tier, actions, category in _PRODUCTION
