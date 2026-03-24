"""Notification system for FREQ.

Send alerts to Discord and Slack via webhooks.
Integrates with patrol, sweep, and audit for automated alerts.

Usage:
  freq notify "Fleet health check passed"              # send to all configured channels
  freq notify --discord "VM 5010 created"               # Discord only
  freq notify --slack "Drift detected on lab-pve1"      # Slack only
"""
import json
import urllib.request
import urllib.error

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig


def send_discord(webhook_url: str, message: str, title: str = "PVE FREQ",
                 color: int = 0x7B2FBE, brand: str = "PVE FREQ") -> bool:
    """Send a message to Discord via webhook."""
    if not webhook_url:
        return False

    payload = {
        "embeds": [{
            "title": title,
            "description": message,
            "color": color,
            "footer": {"text": brand},
        }]
    }

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except (urllib.error.URLError, OSError) as e:
        logger.error(f"Discord notification failed: {e}")
        return False


def send_slack(webhook_url: str, message: str, title: str = "PVE FREQ",
               brand: str = "PVE FREQ") -> bool:
    """Send a message to Slack via webhook."""
    if not webhook_url:
        return False

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message},
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_{brand}_"}],
            },
        ]
    }

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except (urllib.error.URLError, OSError) as e:
        logger.error(f"Slack notification failed: {e}")
        return False


def notify(cfg: FreqConfig, message: str, title: str = "PVE FREQ",
           severity: str = "info") -> dict:
    """Send notification to all configured channels.

    Returns dict of {channel: success} results.
    """
    results = {}

    # Color by severity
    colors = {
        "info": 0x7B2FBE,     # Purple
        "success": 0x52D726,   # Green
        "warn": 0xFFB100,      # Yellow
        "error": 0xFF4444,     # Red
        "critical": 0xFF0000,  # Bright red
    }
    color = colors.get(severity, 0x7B2FBE)

    if cfg.discord_webhook:
        results["discord"] = send_discord(cfg.discord_webhook, message, title, color)

    if cfg.slack_webhook:
        results["slack"] = send_slack(cfg.slack_webhook, message, title)

    return results


def cmd_notify(cfg: FreqConfig, pack, args) -> int:
    """Send a notification to configured channels."""
    message_parts = getattr(args, "message", [])
    message = " ".join(message_parts) if message_parts else ""

    if not message:
        fmt.header("Notify")
        fmt.blank()

        # Show configuration status
        fmt.line(f"{fmt.C.BOLD}Notification channels:{fmt.C.RESET}")
        fmt.blank()

        if cfg.discord_webhook:
            fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} Discord: configured")
        else:
            fmt.line(f"  {fmt.C.GRAY}{fmt.S.CROSS}{fmt.C.RESET} Discord: not configured")

        if cfg.slack_webhook:
            fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} Slack: configured")
        else:
            fmt.line(f"  {fmt.C.GRAY}{fmt.S.CROSS}{fmt.C.RESET} Slack: not configured")

        fmt.blank()
        fmt.line(f"  {fmt.C.GRAY}Configure in freq.toml under [notifications]{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.GRAY}Usage: freq notify \"your message here\"{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Send notification
    if not cfg.discord_webhook and not cfg.slack_webhook:
        fmt.error("No notification channels configured.")
        fmt.info("Set discord_webhook or slack_webhook in freq.toml [notifications]")
        return 1

    results = notify(cfg, message)

    for channel, success in results.items():
        if success:
            fmt.step_ok(f"Sent to {channel}")
        else:
            fmt.step_fail(f"Failed to send to {channel}")

    return 0 if all(results.values()) else 1
