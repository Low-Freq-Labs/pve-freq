"""Portable setup-input path compatibility helpers."""

import os

_LEGACY_HOST_ROOT = "/root/freq-init-inputs"
_CONTAINER_ROOT = "/freq-init-inputs"


def legacy_init_input_candidate(path):
    """Map a contained default-host-layout path to its container candidate.

    This pure compatibility mapper neither probes existence nor chooses a
    caller's error policy. Customized host staging directories are deliberately
    not translated: container-authored TOML always names /freq-init-inputs.
    """
    raw = os.path.normpath(str(path or "").strip())
    if not raw or raw == _LEGACY_HOST_ROOT:
        return ""
    try:
        relative = os.path.relpath(raw, _LEGACY_HOST_ROOT)
    except ValueError:
        return ""
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return ""
    return os.path.join(_CONTAINER_ROOT, relative)
