"""Pure bounded QEMU status body projection, without acquisition or authority.

The exact adjacent guest_network dependency supplies the reviewed bounded JSON
reader. Its qualification does not qualify this new consumer. Original source,
framing, lifetime, cleanup, observation time and final admission remain outside.
"""

from decimal import Decimal, DecimalException
import math

from .guest_network import Number, Reader, Refused as BodyRefused
from .guest_network import fields, text, unsigned


class Refused(ValueError):
    pass


def require(condition):
    if not condition:
        raise Refused("Guest status unavailable")


def fraction(value):
    # The bounded reader validates grammar and the <=64-byte numeric lexeme.
    # Check the exact decimal range before binary conversion: a negative tiny
    # value must not become acceptable -0, nor a value above 1 round down to 1.
    require(type(value) is Number)
    try:
        exact = Decimal(value)
        require(exact.is_finite() and Decimal(0) <= exact <= Decimal(1))
        result = float(exact)
    except (DecimalException, ValueError, OverflowError):
        raise Refused("Guest status unavailable") from None
    require(math.isfinite(result) and 0 <= result <= 1)
    # Do not turn reported positive usage into a fabricated zero by underflow.
    require(result != 0 or exact == 0)
    return result


def decode_guest_status(body):
    """Return four internal display values or a fixed refusal.

    Known provider 'ha' stays a checked flat object. The named blockstat,
    nics and proxmox-support object trees are completely validated/charged by
    Reader before discard. They supply no displayed values or authority.
    Other unknown containers refuse; unknown scalars remain charged/discarded.
    """
    try:
        root = fields(Reader(body).read(), ("data",))
        require(set(root) == {"data"})
        data = fields(root["data"], ("status",),
                      ("cpu", "mem", "maxmem", "ha", "blockstat", "nics",
                       "proxmox-support"))
        for key in ("blockstat", "nics", "proxmox-support"):
            if key in data:
                # Ignore only these explicit metadata namespaces. The same
                # complete Reader has already bounded every nested key/value,
                # number lexeme, depth, member/scalar count and decoded byte.
                # No counters/features/network details escape this decoder.
                require(type(data[key]) is dict)
        state = text(data["status"], 64, True)
        if "ha" in data:
            ha = data["ha"]
            require(type(ha) is dict)
            require(all(type(value) not in (dict, list) for value in ha.values()))
        cpu = fraction(data["cpu"]) if "cpu" in data else None
        used = unsigned(data["mem"], 9007199254740991) if "mem" in data else None
        limit = unsigned(data["maxmem"], 9007199254740991) if "maxmem" in data else None
        return {"state": state, "cpu_fraction": cpu,
                "memory_used_bytes": used, "memory_limit_bytes": limit}
    except BodyRefused:
        # No provider text, parser exception or partial projection escapes.
        raise Refused("Guest status unavailable") from None
