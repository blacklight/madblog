import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from html.parser import HTMLParser
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


class _HTMLToTextParser(HTMLParser):
    """Simple HTML-to-text converter using stdlib html.parser."""

    def __init__(self):
        super().__init__()
        self._text_parts: list = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("br", "p", "div", "li", "tr"):
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._text_parts.append(data)

    def get_text(self) -> str:
        import re

        text = "".join(self._text_parts)
        # Collapse multiple newlines into at most two
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_text(html: str) -> str:
    """
    Convert HTML to plain text.

    Strips tags and converts block elements to newlines.
    """
    parser = _HTMLToTextParser()
    parser.feed(html)
    return parser.get_text()


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
