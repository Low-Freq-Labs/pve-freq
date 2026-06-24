"""Shared metrics-agent health check helpers."""


def remote_agent_health_command(port):
    """Return a portable remote shell command for freq-agent /health.

    Some minimal hosts do not ship curl. The metrics collector itself requires
    Python, so prefer Python stdlib as the fallback before wget.
    """
    port = int(port or 9990)
    url = f"http://127.0.0.1:{port}/health"
    py = (
        "import urllib.request,sys; "
        f"sys.stdout.write(urllib.request.urlopen({url!r}, timeout=3).read().decode())"
    )
    return (
        f"if command -v curl >/dev/null 2>&1; then "
        f"curl -fsS --max-time 3 {url} 2>/dev/null; "
        f"elif command -v python3 >/dev/null 2>&1; then "
        f"python3 -c {py!r}; "
        f"elif command -v wget >/dev/null 2>&1; then "
        f"wget -q -T 3 -O - {url} 2>/dev/null; "
        f"else echo FREQ_AGENT_HEALTH_CHECK_NO_CLIENT; exit 127; fi"
    )
