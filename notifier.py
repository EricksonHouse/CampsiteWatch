"""Notification channels: email (SMTP), push via ntfy.sh (free, no account
needed), and SMS via carrier email-to-text gateways (free, uses SMTP)."""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any

import requests

logger = logging.getLogger("campwatch.notifier")


def send_email(cfg: dict[str, Any], subject: str, body: str) -> None:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = cfg["from_address"]
    msg["To"] = cfg["to_address"]
    with smtplib.SMTP(cfg["smtp_server"], cfg.get("smtp_port", 587)) as server:
        server.starttls()
        server.login(cfg["from_address"], cfg["from_password"])
        server.sendmail(cfg["from_address"], [cfg["to_address"]], msg.as_string())
    logger.info("Email sent: %s", subject)


def send_sms_via_email_gateway(cfg: dict[str, Any], body: str) -> None:
    """Most US carriers offer a free number@gateway.com SMS bridge, e.g.
    5551234567@txt.att.net (AT&T), @vtext.com (Verizon), @tmomail.net (T-Mobile).
    Reuses the email config's SMTP credentials. Keep body short (~150 chars);
    most gateways truncate."""
    gateway_cfg = dict(cfg["email"])
    gateway_cfg["to_address"] = cfg["sms_gateway_address"]
    send_email(gateway_cfg, subject="", body=body[:150])


def send_ntfy(cfg: dict[str, Any], title: str, body: str) -> None:
    """ntfy.sh push notification. No account needed: pick a private topic
    name (treat it like a password -- anyone who knows it can read your
    alerts), install the ntfy app, and subscribe to that topic."""
    topic = cfg["topic"]
    server = cfg.get("server", "https://ntfy.sh")
    resp = requests.post(
        f"{server}/{topic}",
        data=body.encode("utf-8"),
        headers={"Title": title, "Priority": cfg.get("priority", "high")},
        timeout=10,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"ntfy push failed: {resp.status_code} {resp.text[:200]}")
    logger.info("ntfy push sent: %s", title)


def notify_all(config: dict[str, Any], title: str, body: str) -> None:
    n = config.get("notifications", {})
    errors = []

    if n.get("email", {}).get("enabled"):
        try:
            send_email(n["email"], title, body)
        except Exception as e:  # noqa: BLE001
            errors.append(f"email: {e}")

    if n.get("sms", {}).get("enabled"):
        try:
            send_sms_via_email_gateway(n["sms"], body)
        except Exception as e:  # noqa: BLE001
            errors.append(f"sms: {e}")

    if n.get("ntfy", {}).get("enabled"):
        try:
            send_ntfy(n["ntfy"], title, body)
        except Exception as e:  # noqa: BLE001
            errors.append(f"ntfy: {e}")

    if errors:
        logger.error("Some notification channels failed: %s", "; ".join(errors))
