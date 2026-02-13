import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Callable, Optional

from webmentions import Webmention, WebmentionDirection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmtpConfig:
    server: str
    port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None
    starttls: bool = True
    enable_starttls_auto: bool = True
    sender: Optional[str] = None


def _send_email(
    *,
    smtp: SmtpConfig,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    msg = EmailMessage()
    msg["To"] = recipient
    msg["From"] = smtp.sender or smtp.username or recipient
    msg["Subject"] = subject
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


def build_webmention_email_notifier(
    *,
    recipient: str,
    blog_base_url: str,
    smtp: SmtpConfig,
    sender: Optional[str] = None,
    send_email: Callable[..., None] = _send_email,
) -> Callable[[Webmention], None]:
    smtp = SmtpConfig(
        server=smtp.server,
        port=smtp.port,
        username=smtp.username,
        password=smtp.password,
        starttls=smtp.starttls,
        enable_starttls_auto=smtp.enable_starttls_auto,
        sender=sender or smtp.sender,
    )

    def _on_mention_processed(mention: Webmention) -> None:
        if mention.direction != WebmentionDirection.IN:
            return

        subject = f"New Webmention received for {blog_base_url}"

        lines = [
            "A new Webmention has been processed.",
            "",
            f"Source: {mention.source}",
            f"Target: {mention.target}",
        ]

        if mention.author_name or mention.author_url:
            lines.append(
                f"Author: {mention.author_name or ''} {mention.author_url or ''}".strip()
            )

        if mention.title:
            lines.append(f"Title: {mention.title}")

        if mention.excerpt:
            lines.extend(["", "Excerpt:", mention.excerpt])

        try:
            send_email(
                smtp=smtp,
                recipient=recipient,
                subject=subject,
                body="\n".join(lines) + "\n",
            )
        except Exception:
            logger.exception(
                "Failed to send Webmention notification email (source=%s target=%s)",
                mention.source,
                mention.target,
            )

    return _on_mention_processed
