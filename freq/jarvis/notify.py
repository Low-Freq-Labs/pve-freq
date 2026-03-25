"""Notification system for FREQ.

Provider-based notification dispatch. Each provider is a function:
  (cfg, message, title, severity) → bool

Supported providers:
  Discord, Slack, Telegram, Email (SMTP), ntfy, Gotify, Pushover, Generic Webhook

Usage:
  freq notify "Fleet health check passed"              # send to all configured channels
  freq notify --discord "VM 5010 created"               # Discord only
  freq notify --slack "Drift detected on lab-pve1"      # Slack only
"""
import json
import urllib.parse
import urllib.request
import urllib.error

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig

# Notification timeouts
NOTIFY_TIMEOUT = 10

# Severity → color mapping for providers that support colors
SEVERITY_COLORS = {
    "info": 0x7B2FBE,     # Purple
    "success": 0x52D726,   # Green
    "warn": 0xFFB100,      # Yellow
    "warning": 0xFFB100,   # Yellow (alias)
    "error": 0xFF4444,     # Red
    "critical": 0xFF0000,  # Bright red
}


# ── Provider Registry ──────────────────────────────────────────────────

def _providers():
    """Return list of (name, config_check, send_func) tuples."""
    return [
        ("discord", lambda c: bool(c.discord_webhook), send_discord),
        ("slack", lambda c: bool(c.slack_webhook), send_slack),
        ("telegram", lambda c: bool(c.telegram_bot_token and c.telegram_chat_id), send_telegram),
        ("email", lambda c: bool(c.smtp_host and c.smtp_to), send_email),
        ("ntfy", lambda c: bool(c.ntfy_url and c.ntfy_topic), send_ntfy),
        ("gotify", lambda c: bool(c.gotify_url and c.gotify_token), send_gotify),
        ("pushover", lambda c: bool(c.pushover_user and c.pushover_token), send_pushover),
        ("webhook", lambda c: bool(c.webhook_url), send_webhook),
    ]


def configured_providers(cfg: FreqConfig) -> list:
    """Return list of provider names that are configured."""
    return [name for name, check, _ in _providers() if check(cfg)]


# ── Discord ─────────────────────────────────────────────────────────────

def send_discord(cfg: FreqConfig, message: str, title: str = "PVE FREQ",
                 severity: str = "info") -> bool:
    """Send a message to Discord via webhook."""
    url = cfg.discord_webhook
    if not url:
        return False

    color = SEVERITY_COLORS.get(severity, 0x7B2FBE)
    payload = {
        "embeds": [{
            "title": title,
            "description": message,
            "color": color,
            "footer": {"text": cfg.brand},
        }]
    }

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT)
        return True
    except (urllib.error.URLError, OSError) as e:
        logger.error(f"Discord notification failed: {e}")
        return False


# ── Slack ───────────────────────────────────────────────────────────────

def send_slack(cfg: FreqConfig, message: str, title: str = "PVE FREQ",
               severity: str = "info") -> bool:
    """Send a message to Slack via webhook."""
    url = cfg.slack_webhook
    if not url:
        return False

    payload = {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": message}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{cfg.brand}_"}]},
        ]
    }

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT)
        return True
    except (urllib.error.URLError, OSError) as e:
        logger.error(f"Slack notification failed: {e}")
        return False


# ── Telegram ────────────────────────────────────────────────────────────

def send_telegram(cfg: FreqConfig, message: str, title: str = "PVE FREQ",
                  severity: str = "info") -> bool:
    """Send a message to Telegram via Bot API."""
    token = cfg.telegram_bot_token
    chat_id = cfg.telegram_chat_id
    if not token or not chat_id:
        return False

    text = f"*{title}*\n{message}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT)
        return True
    except (urllib.error.URLError, OSError) as e:
        logger.error(f"Telegram notification failed: {e}")
        return False


# ── Email (SMTP) ────────────────────────────────────────────────────────

def send_email(cfg: FreqConfig, message: str, title: str = "PVE FREQ",
               severity: str = "info") -> bool:
    """Send a notification email via SMTP."""
    if not cfg.smtp_host or not cfg.smtp_to:
        return False

    import smtplib
    from email.mime.text import MIMEText

    msg = MIMEText(message)
    msg["Subject"] = f"[{severity.upper()}] {title}"
    msg["From"] = cfg.smtp_user or f"freq@{cfg.smtp_host}"
    msg["To"] = cfg.smtp_to

    try:
        if cfg.smtp_tls:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=NOTIFY_TIMEOUT)
            server.starttls()
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=NOTIFY_TIMEOUT)
        if cfg.smtp_user and cfg.smtp_password:
            server.login(cfg.smtp_user, cfg.smtp_password)
        server.sendmail(msg["From"], [cfg.smtp_to], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        logger.error(f"Email notification failed: {e}")
        return False


# ── ntfy ────────────────────────────────────────────────────────────────

def send_ntfy(cfg: FreqConfig, message: str, title: str = "PVE FREQ",
              severity: str = "info") -> bool:
    """Send a notification via ntfy (https://ntfy.sh)."""
    base_url = cfg.ntfy_url.rstrip("/")
    topic = cfg.ntfy_topic
    if not base_url or not topic:
        return False

    # ntfy priority mapping
    priority_map = {"info": "default", "success": "low", "warn": "high",
                    "warning": "high", "error": "urgent", "critical": "max"}
    priority = priority_map.get(severity, "default")

    url = f"{base_url}/{topic}"
    try:
        data = message.encode()
        req = urllib.request.Request(url, data=data)
        req.add_header("Title", title)
        req.add_header("Priority", priority)
        req.add_header("Tags", severity)
        urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT)
        return True
    except (urllib.error.URLError, OSError) as e:
        logger.error(f"ntfy notification failed: {e}")
        return False


# ── Gotify ──────────────────────────────────────────────────────────────

def send_gotify(cfg: FreqConfig, message: str, title: str = "PVE FREQ",
                severity: str = "info") -> bool:
    """Send a notification via Gotify."""
    base_url = cfg.gotify_url.rstrip("/")
    token = cfg.gotify_token
    if not base_url or not token:
        return False

    # Gotify priority: 0-10
    priority_map = {"info": 2, "success": 1, "warn": 5, "warning": 5,
                    "error": 8, "critical": 10}
    priority = priority_map.get(severity, 2)

    url = f"{base_url}/message?token={token}"
    payload = {"title": title, "message": message, "priority": priority}

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT)
        return True
    except (urllib.error.URLError, OSError) as e:
        logger.error(f"Gotify notification failed: {e}")
        return False


# ── Pushover ────────────────────────────────────────────────────────────

def send_pushover(cfg: FreqConfig, message: str, title: str = "PVE FREQ",
                  severity: str = "info") -> bool:
    """Send a notification via Pushover."""
    user = cfg.pushover_user
    token = cfg.pushover_token
    if not user or not token:
        return False

    # Pushover priority: -2 to 2
    priority_map = {"info": 0, "success": -1, "warn": 1, "warning": 1,
                    "error": 1, "critical": 2}
    priority = priority_map.get(severity, 0)

    payload = {
        "token": token,
        "user": user,
        "title": title,
        "message": message,
        "priority": priority,
    }
    # Emergency priority requires retry/expire
    if priority == 2:
        payload["retry"] = 60
        payload["expire"] = 300

    try:
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request("https://api.pushover.net/1/messages.json",
                                     data=data)
        urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT)
        return True
    except (urllib.error.URLError, OSError) as e:
        logger.error(f"Pushover notification failed: {e}")
        return False


# ── Generic Webhook ─────────────────────────────────────────────────────

def send_webhook(cfg: FreqConfig, message: str, title: str = "PVE FREQ",
                 severity: str = "info") -> bool:
    """Send a notification via generic webhook (POST JSON)."""
    url = cfg.webhook_url
    if not url:
        return False

    payload = {
        "title": title,
        "message": message,
        "severity": severity,
        "source": cfg.brand,
    }

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT)
        return True
    except (urllib.error.URLError, OSError) as e:
        logger.error(f"Webhook notification failed: {e}")
        return False


# ── Main Dispatch ───────────────────────────────────────────────────────

def notify(cfg: FreqConfig, message: str, title: str = "PVE FREQ",
           severity: str = "info") -> dict:
    """Send notification to all configured channels.

    Returns dict of {channel: success} results.
    """
    results = {}
    for name, check, send_func in _providers():
        if check(cfg):
            try:
                results[name] = send_func(cfg, message, title, severity)
            except Exception as e:
                logger.error(f"{name} notification failed: {e}")
                results[name] = False
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

        for name, check, _ in _providers():
            if check(cfg):
                fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {name.capitalize()}: configured")
            else:
                fmt.line(f"  {fmt.C.GRAY}{fmt.S.CROSS}{fmt.C.RESET} {name.capitalize()}: not configured")

        fmt.blank()
        fmt.line(f"  {fmt.C.GRAY}Configure in freq.toml under [notifications]{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.GRAY}Usage: freq notify \"your message here\"{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Send notification
    active = configured_providers(cfg)
    if not active:
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
