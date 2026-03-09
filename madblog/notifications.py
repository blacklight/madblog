import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from typing import Optional


@dataclass(frozen=True)
class SmtpConfig:
    """
    Configuration for an SMTP server.
    """

    server: str
    port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None
    starttls: bool = True
    enable_starttls_auto: bool = True
    sender: Optional[str] = None


def send_email(
    *,
    smtp: SmtpConfig,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    """
    Send an email.

    :param smtp: Configuration for an SMTP server.
    :param recipient: Email address of the recipient.
    :param subject: Subject of the email.
    :param body: Body of the email.
    """

    msg = EmailMessage()
    msg["To"] = recipient
    msg["From"] = smtp.sender or smtp.username or recipient
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg["Message-ID"] = make_msgid(domain=None)
    msg.set_content(body)

    with smtplib.SMTP(smtp.server, smtp.port) as client:
        if smtp.enable_starttls_auto:
            client.ehlo()

        if smtp.starttls:
            client.starttls()
            if smtp.enable_starttls_auto:
                client.ehlo()

        if smtp.username:
            client.login(smtp.username, smtp.password or "")

        client.send_message(msg)
