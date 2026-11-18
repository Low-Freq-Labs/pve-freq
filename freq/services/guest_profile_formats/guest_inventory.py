"""Pure ordered guest selection; no source, selector or currentness authority.

The complete accepted raw resource grammar runs before any projection. Internal
rows deliberately contain no guest_ref: only an original session owner can issue
that capability after atomically reserving the whole response's capacity.
"""

import re

from .raw import InvalidRaw, canonical_integer, decode_rows


class Refused(ValueError):
    pass


def _refuse():
    raise Refused("Guest inventory unavailable")


def decode_guest_inventory(body):
    """Return fresh internal rows or refuse the entire complete resource body.

    A missing/malformed type refuses rather than silently losing a possible
    guest. Other nonempty scalar string types are not guest rows. Templates are
    not silently filtered: qemu/lxc are the accepted contract's only selectors.
    Raw decoder bounds are distinct from the later whole application wire cap.
    """
    try:
        rows = decode_rows(body)
    except InvalidRaw:
        _refuse()
    selected, seen = [], set()
    for pairs in rows:
        row = dict(pairs)
        kind = row.get("type")
        if type(kind) is not str or not kind:
            _refuse()
        if kind not in ("qemu", "lxc"):
            continue
        node = row.get("node")
        if type(node) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,63}", node) is None:
            _refuse()
        vmid = canonical_integer(row.get("vmid"))
        if vmid is None or not 100 <= vmid <= 999999999:
            _refuse()
        name = row.get("name")
        if name is not None:
            if type(name) is not str:
                _refuse()
            if len(name.encode("utf-8")) > 256:
                _refuse()
        identity = (node, kind, vmid)
        if identity in seen or len(selected) >= 256:
            _refuse()
        seen.add(identity)
        selected.append(dict(node=node, guest_kind=kind, vmid=vmid, name=name))
    return selected
