from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app import runtime_settings


def _smtp_config() -> tuple[str, int, str, str, str, str]:
    host = runtime_settings.get_required_setting(
        "SMTP_HOST",
        "SMTP Host 未配置，无法发送价格提醒邮件。",
    )
    port = int(
        runtime_settings.get_setting("SMTP_PORT", "587")
        or "587"
    )
    username = runtime_settings.get_required_setting(
        "SMTP_USERNAME",
        "SMTP 用户名未配置，无法发送价格提醒邮件。",
    )
    password = runtime_settings.get_required_setting(
        "SMTP_PASSWORD",
        "SMTP 密码未配置，无法发送价格提醒邮件。",
    )
    sender = runtime_settings.get_required_setting(
        "SMTP_FROM",
        "SMTP 发件人未配置，无法发送价格提醒邮件。",
    )
    recipient = (
        runtime_settings.get_setting("ALERT_EMAIL_TO", "")
        or sender
    )
    return host, port, username, password, sender, recipient


def _send_message_sync(subject: str, body: str) -> None:
    host, port, username, password, sender, recipient = _smtp_config()

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(message)


async def send_price_alert_email(subject: str, body: str) -> None:
    await asyncio.to_thread(_send_message_sync, subject, body)
