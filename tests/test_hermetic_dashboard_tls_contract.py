"""Runtime contract for the configured Playwright dashboard TLS boundary."""

from __future__ import annotations

import json
import selectors
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYWRIGHT_CONFIG = REPO_ROOT / "playwright.hermetic.config.js"


def _start_configured_tls_server() -> tuple[subprocess.Popen[str], str]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.support.hermetic_dashboard",
            "--tls",
            "--port",
            "0",
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(
                    "hermetic TLS server exited before readiness: "
                    f"{process.stderr.read().strip()}"
                )
            if not selector.select(timeout=0.25):
                continue
            line = process.stdout.readline().strip()
            if line.startswith("HERMETIC_DASHBOARD "):
                return process, line.split(" ", 1)[1]
        pytest.fail("hermetic TLS server did not report readiness within 15 seconds")
    except BaseException:
        process.terminate()
        process.wait(timeout=5)
        raise
    finally:
        selector.close()


def _stop_server(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def test_playwright_config_requires_real_tls_without_a_product_bypass() -> None:
    source = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")

    assert "const baseURL = `https://127.0.0.1:${port}`;" in source
    assert "tests.support.hermetic_dashboard --tls --port ${port}" in source
    assert "url: `${baseURL}/healthz`" in source
    assert source.count("ignoreHTTPSErrors: true") == 2
    assert "trusted_prox" not in source
    assert "Origin" not in source


def test_configured_hermetic_server_is_https_with_a_throwaway_certificate() -> None:
    process, base_url = _start_configured_tls_server()
    try:
        assert base_url.startswith("https://127.0.0.1:")

        with pytest.raises(urllib.error.URLError) as verified_error:
            urllib.request.urlopen(f"{base_url}/healthz", timeout=3)
        assert isinstance(verified_error.value.reason, ssl.SSLCertVerificationError)

        context = ssl._create_unverified_context()
        with urllib.request.urlopen(
            f"{base_url}/healthz", context=context, timeout=3
        ) as response:
            assert response.status == 200
            assert json.load(response)["status"] == "ok"

        plain_url = base_url.replace("https://", "http://", 1)
        with pytest.raises((ConnectionError, OSError, urllib.error.URLError)):
            urllib.request.urlopen(f"{plain_url}/healthz", timeout=3)
    finally:
        _stop_server(process)
