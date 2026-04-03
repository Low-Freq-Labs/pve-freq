"""Package data — config templates, personality packs, knowledge base."""

from importlib import resources
from pathlib import Path


def get_data_path() -> Path:
    """Return path to freq/data/ directory."""
    return Path(str(resources.files("freq.data")))
