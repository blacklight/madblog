import logging
from typing import Callable, Optional

from webmentions import Webmention, WebmentionDirection, WebmentionStatus

from madblog.notifications import SmtpConfig, send_email as _send_email

logger = logging.getLogger(__name__)


def build_webmention_email_notifier(
    *,
    recipient: str,
    blog_base_url: str,
    smtp: SmtpConfig,
    sender: Optional[str] = None,
    send_email: Callable[..., None] = _send_email,
) -> Callable[[Webmention], None]:
    """
    Build a callback that sends an email when a Webmention is received.
    """

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

        if getattr(mention, "status", None) == WebmentionStatus.DELETED:
            return

        if (
            mention.created_at
            and mention.updated_at
            and mention.created_at != mention.updated_at
        ):
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
