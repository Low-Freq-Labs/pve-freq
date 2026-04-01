"""Drive sanitization station client for FREQ.

Domain: freq hw <gwipe-status|gwipe-start|gwipe-list|gwipe-verify>

Connects to a GWIPE station REST API (port 7980) to manage secure drive
wipe operations. Supports DoD 5220.22-M and NIST 800-88 wipe standards.
Credentials resolved from FREQ vault or CLI flags.

Replaces: DBAN (no remote management), Blancco ($18/drive license)

Architecture:
    - REST client using urllib.request (stdlib) to GWIPE API
    - API key auth via X-API-Key header
    - Credential resolution: CLI flags first, vault fallback
    - Vault integration via freq/modules/vault.py

Design decisions:
    - Client-only, not the wipe engine. GWIPE station is a separate
      appliance. FREQ just talks to its API for fleet-integrated control.
"""
import json
import logging
import urllib.request
import urllib.error

from freq.core import fmt
from freq.core import validate

logger = logging.getLogger(__name__)


def _gwipe_api(host, key, method, endpoint, body=None, timeout=10):
    """Make a GWIPE API call. Returns (data, error_string)."""
    url = "http://{}:7980/api/v1/{}".format(host, endpoint)
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-API-Key", key)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        try:
            return None, json.loads(e.read().decode()).get("error", "HTTP {}".format(e.code))
        except Exception:
            return None, "HTTP {}".format(e.code)
    except Exception as e:
        return None, str(e)


def _resolve_creds(cfg, args):
    """Resolve host + key from args or vault."""
    host = getattr(args, "host", None) or ""
    key = getattr(args, "key", None) or ""
    if not host or not key:
        try:
            from freq.modules.vault import vault_get
            if not host:
                host = vault_get(cfg, "gwipe", "gwipe_host") or ""
            if not key:
                key = vault_get(cfg, "gwipe", "gwipe_api_key") or ""
        except Exception as e:
            logger.warning("gwipe vault lookup failed: %s", e)
    return host, key


def _show_status(host, key):
    d, err = _gwipe_api(host, key, "GET", "status")
    if err:
        fmt.line("  {r}Error: {e}{z}".format(r=fmt.C.RED, e=err, z=fmt.C.RESET))
        return 1
    fmt.line("  {p}Station:{z} {h}:7980  {g}v{v}{z}".format(
        p=fmt.C.PURPLE, z=fmt.C.RESET, h=host, g=fmt.C.GREEN,
        v=d.get("version", "?")))
    fmt.line("  {p}Bays:{z}    {t} total, {o} occupied".format(
        p=fmt.C.PURPLE, z=fmt.C.RESET,
        t=d.get("bays_total", 0), o=d.get("bays_occupied", 0)))
    fmt.line("  {p}Wiping:{z}  {y}{w}{z}".format(
        p=fmt.C.PURPLE, z=fmt.C.RESET, y=fmt.C.YELLOW, w=d.get("wiping", 0)))
    fmt.line("  {p}Wiped:{z}   {g}{w}{z}".format(
        p=fmt.C.PURPLE, z=fmt.C.RESET, g=fmt.C.GREEN, w=d.get("wiped", 0)))
    fmt.line("  {p}Failed:{z}  {r}{f}{z}".format(
        p=fmt.C.PURPLE, z=fmt.C.RESET, r=fmt.C.RED, f=d.get("failed", 0)))
    fmt.line("  {p}Session:{z} {s}  |  Lifetime: {l}".format(
        p=fmt.C.PURPLE, z=fmt.C.RESET,
        s=d.get("session_counter", 0), l=d.get("lifetime_counter", 0)))
    fmt.blank()
    return 0


def _show_bays(host, key):
    d, err = _gwipe_api(host, key, "GET", "bays")
    if err:
        fmt.line("  {r}Error: {e}{z}".format(r=fmt.C.RED, e=err, z=fmt.C.RESET))
        return 1
    bays = d.get("bays", {})
    state_colors = {
        "WIPING": fmt.C.YELLOW, "WIPED": fmt.C.GREEN, "TESTED": fmt.C.GREEN,
        "SMART_FAILED": fmt.C.RED, "TESTING": fmt.C.CYAN, "DETECTED": fmt.C.BLUE,
    }
    for dev in sorted(bays.keys()):
        b = bays[dev]
        state = b.get("state", "EMPTY")
        model = (b.get("model", "") or "-")[:30]
        size = b.get("size", "") or "-"
        serial = b.get("serial", "") or "-"
        sc = state_colors.get(state, fmt.C.DIM)
        fmt.line("  /dev/{d}  {sc}{s:15}{z}  {m:30}  {sz:10}  {sr}".format(
            d=dev, sc=sc, s=state, z=fmt.C.RESET, m=model, sz=size, sr=serial))
        if state == "WIPING":
            pct = b.get("wipe", {}).get("percent", 0)
            speed = b.get("wipe", {}).get("speed", "")
            eta = b.get("wipe", {}).get("eta", "")
            bar_len = 30
            filled = int(pct / 100 * bar_len)
            bar = "{f}{e}".format(f="#" * filled, e="-" * (bar_len - filled))
            fmt.line("           [{b}] {p:.1f}%  {sp}  ETA: {et}".format(
                b=bar, p=pct, sp=speed, et=eta))
    fmt.blank()
    return 0


def _show_history(host, key):
    d, err = _gwipe_api(host, key, "GET", "history")
    if err:
        fmt.line("  {r}Error: {e}{z}".format(r=fmt.C.RED, e=err, z=fmt.C.RESET))
        return 1
    for entry in d.get("history", []):
        rc = fmt.C.GREEN if entry.get("result") == "WIPED" else fmt.C.RED
        fmt.line("  {ts:20}  {bay:5}  {model:25}  {sz:10}  {rc}{res:8}{z}  {dur}".format(
            ts=entry.get("timestamp", "?"), bay=entry.get("bay", "?"),
            model=entry.get("model", "?")[:25], sz=entry.get("size", "?"),
            rc=rc, res=entry.get("result", "?"), z=fmt.C.RESET,
            dur=entry.get("duration", "?")))
    if not d.get("history"):
        fmt.line("  {d}No wipe history{z}".format(d=fmt.C.DIM, z=fmt.C.RESET))
    fmt.blank()
    return 0


def _post_action(host, key, endpoint, color, timeout=30):
    """POST to endpoint and show result message."""
    d, err = _gwipe_api(host, key, "POST", endpoint, timeout=timeout)
    if err:
        fmt.line("  {r}Error: {e}{z}".format(r=fmt.C.RED, e=err, z=fmt.C.RESET))
        return 1
    fmt.line("  {c}{m}{z}".format(c=color, m=d.get("message", "OK"), z=fmt.C.RESET))
    fmt.blank()
    return 0


def cmd_gwipe(cfg, pack, args):
    """FREQ WIPE — drive sanitization station."""
    host, key = _resolve_creds(cfg, args)
    action = getattr(args, "action", "status") or "status"
    target = getattr(args, "target", None)

    # Validate bay target if provided (path traversal prevention)
    if target and not validate.bay_device(target):
        fmt.line("  {r}Invalid bay: {t}{z}".format(r=fmt.C.RED, t=target, z=fmt.C.RESET))
        return 1

    # Connect: save credentials to vault
    if action == "connect":
        if not host or not key:
            fmt.line("  {r}Usage: freq gwipe connect --host <ip> --key <apikey>{z}".format(
                r=fmt.C.RED, z=fmt.C.RESET))
            return 1
        try:
            import os
            from freq.modules.vault import vault_set, vault_init
            if not os.path.exists(cfg.vault_file):
                vault_init(cfg)
            vault_set(cfg, "gwipe", "gwipe_host", host)
            vault_set(cfg, "gwipe", "gwipe_api_key", key)
            fmt.line("  {g}GWIPE station saved: {h}{z}".format(
                g=fmt.C.GREEN, h=host, z=fmt.C.RESET))
        except Exception as e:
            fmt.line("  {r}Failed to save: {e}{z}".format(
                r=fmt.C.RED, e=e, z=fmt.C.RESET))
        return 0

    # No station configured
    if not host or not key:
        fmt.header("FREQ WIPE")
        fmt.blank()
        fmt.line("  {r}No wipe station configured.{z}".format(
            r=fmt.C.RED, z=fmt.C.RESET))
        fmt.line("  {d}Connect: freq gwipe connect --host <ip> --key <apikey>{z}".format(
            d=fmt.C.DIM, z=fmt.C.RESET))
        fmt.line("  {d}Or set via vault:{z}".format(d=fmt.C.DIM, z=fmt.C.RESET))
        fmt.line("  {d}  freq vault set gwipe gwipe_host <ip>{z}".format(
            d=fmt.C.DIM, z=fmt.C.RESET))
        fmt.line("  {d}  freq vault set gwipe gwipe_api_key <key>{z}".format(
            d=fmt.C.DIM, z=fmt.C.RESET))
        fmt.blank()
        return 1

    fmt.header("FREQ WIPE")
    fmt.blank()

    handlers = {
        "status": lambda: _show_status(host, key),
        "bays": lambda: _show_bays(host, key),
        "history": lambda: _show_history(host, key),
    }

    if action in handlers:
        return handlers[action]()

    if action in ("test", "smart"):
        endpoint = "bays/{}/smart".format(target) if target else "test-all"
        return _post_action(host, key, endpoint, fmt.C.GREEN)

    if action == "wipe":
        if not target:
            fmt.line("  {r}Usage: freq gwipe wipe <bay>  (e.g. freq gwipe wipe sdb){z}".format(
                r=fmt.C.RED, z=fmt.C.RESET))
            return 1
        d, err = _gwipe_api(host, key, "POST", "bays/{}/wipe".format(target),
                            body={"confirm": "YES"}, timeout=30)
        if err:
            fmt.line("  {r}Error: {e}{z}".format(r=fmt.C.RED, e=err, z=fmt.C.RESET))
            return 1
        fmt.line("  {y}{m}{z}".format(y=fmt.C.YELLOW, m=d.get("message", "OK"), z=fmt.C.RESET))
        fmt.blank()
        return 0

    if action == "full-send":
        return _post_action(host, key, "full-send", fmt.C.GREEN)

    if action == "pause":
        endpoint = "bays/{}/pause".format(target) if target else "pause-all"
        return _post_action(host, key, endpoint, fmt.C.YELLOW)

    if action == "resume":
        endpoint = "bays/{}/resume".format(target) if target else "resume-all"
        return _post_action(host, key, endpoint, fmt.C.GREEN)

    # Unknown action — show help
    fmt.line("  {d}Actions: status | bays | history | test [bay] | wipe <bay> | "
             "full-send | pause [bay] | resume [bay] | connect{z}".format(
                 d=fmt.C.DIM, z=fmt.C.RESET))
    fmt.blank()
    return 0
