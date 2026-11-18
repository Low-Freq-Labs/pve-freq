"""Bounded document-state event stream; selected fields are not validated yet."""
from .lines import InvalidDocument, supplied_lines
from .statements import statement
from .values import Counters


def _reject():
    raise InvalidDocument("Policy document unavailable")


def _events(lines):
    counters = Counters()
    current_document = None
    current = None
    names = set()
    tables = set()
    infrastructure = set()
    hosts = 0
    categories = 0
    for document, number, text in lines:
        if document != current_document:
            current_document = document
            current = None
            names = set()
        leading = text.lstrip(" \t")
        if not leading or leading.startswith("#"):
            continue
        # Refuse an exhausted record/section before parsing its next value.
        if not leading.startswith("["):
            if current is None:
                _reject()
            if current == ("tiers",):
                limit = 64
            elif current in (("physical",), ("pve_nodes",)):
                limit = 128
                if len(infrastructure) >= 128:
                    _reject()
            elif current[0] in ("physical", "pve_nodes"):
                limit = 16
            else:
                limit = 32
            if len(names) >= limit:
                _reject()
        parsed = statement(text, document, counters)
        if parsed[0] == "header":
            path = parsed[1]
            if document == 0:
                if hosts >= 512:
                    _reject()
                hosts += 1
            else:
                if path in tables:
                    _reject()
                if path[0] == "categories":
                    if categories >= 64:
                        _reject()
                    categories += 1
                elif len(path) == 2:
                    if path in infrastructure or len(infrastructure) >= 128:
                        _reject()
                    infrastructure.add(path)
                tables.add(path)
            current = path
            names = set()
            yield document, number, parsed
        else:
            name, item = parsed[1:]
            if name in names:
                _reject()
            if current in (("physical",), ("pve_nodes",)):
                identity = (current[0], name)
                if identity in infrastructure:
                    _reject()
                # Parent infrastructure entries must be flat inline records.
                if type(item) is not dict:
                    _reject()
                infrastructure.add(identity)
            names.add(name)
            yield document, number, parsed


def document_events(hosts, fleet):
    """Preflight bytes, then yield bounded structural events.

    Consumers must exhaust both documents and validate every selected field
    before publishing anything. Events are not accepted policy or provenance.
    No unrelated metadata is retained after its event is consumed.
    """
    return _events(supplied_lines(hosts, fleet))
