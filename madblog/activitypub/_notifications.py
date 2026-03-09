import logging
from typing import Callable, Optional

from madblog.notifications import SmtpConfig, send_email as _send_email

logger = logging.getLogger(__name__)


def build_activitypub_email_notifier(
    *,
    recipient: str,
    blog_base_url: str,
    smtp: SmtpConfig,
    sender: Optional[str] = None,
    send_email: Callable[..., None] = _send_email,
) -> Callable:
    """
    Build a callback that sends an email when an ActivityPub interaction
    is received (reply, like, boost).

    Compatible with ``ActivityPubHandler(on_interaction_received=...)``.
    """
    from pubby import Interaction, InteractionStatus

    smtp = SmtpConfig(
        server=smtp.server,
        port=smtp.port,
        username=smtp.username,
        password=smtp.password,
        starttls=smtp.starttls,
        enable_starttls_auto=smtp.enable_starttls_auto,
        sender=sender or smtp.sender,
    )

    def _on_interaction_received(interaction: Interaction) -> None:
        if getattr(interaction, "status", None) == InteractionStatus.DELETED:
            return

        itype = str(interaction.interaction_type.value).capitalize()
        subject = f"New ActivityPub {itype} received for {blog_base_url}"

        lines = [
            f"A new ActivityPub {itype.lower()} has been received.",
            "",
            f"From: {interaction.source_actor_id}",
            f"Target: {interaction.target_resource}",
        ]

        if interaction.author_name or interaction.author_url:
            lines.append(
                f"Author: {interaction.author_name or ''}"
                f" {interaction.author_url or ''}".strip()
            )

        if interaction.content:
            lines.extend(["", "Content:", interaction.content])

        try:
            send_email(
                smtp=smtp,
                recipient=recipient,
                subject=subject,
                body="\n".join(lines) + "\n",
            )
        except Exception:
            logger.exception(
                "Failed to send ActivityPub notification email (actor=%s target=%s)",
                interaction.source_actor_id,
                interaction.target_resource,
            )

    return _on_interaction_received
