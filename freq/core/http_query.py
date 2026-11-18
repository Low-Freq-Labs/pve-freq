"""Dependency-clean URL query parsing shared by HTTP consumers."""

from urllib.parse import parse_qs, urlparse


def parse_query(handler):
    """Parse a request handler path into ``{key: [values]}``."""
    return parse_qs(urlparse(handler.path).query)


def parse_query_flat(path_str):
    """Parse a URL path into ``{key: first_value}``."""
    raw = parse_qs(urlparse(path_str).query)
    return {key: values[0] if values else "" for key, values in raw.items()}


def parse_query_handler_flat(handler):
    """Parse a request handler path into ``{key: first_value}``."""
    return parse_query_flat(handler.path)
