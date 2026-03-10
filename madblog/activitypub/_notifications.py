import logging
from typing import Callable, Optional

from madblog.notifications import SmtpConfig, html_to_text, send_email as _send_email

logger = logging.getLogger(__name__)


def build_activitypub_email_notifier(
    *,
    recipient: str,
    blog_base_url: str,
    smtp: SmtpConfig,
    ap_base_url: Optional[str] = None,
    actor_url: Optional[str] = None,
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

    base_url = blog_base_url.rstrip("/")
    ap_url = (ap_base_url or "").rstrip("/")
    valid_prefixes = tuple({p + "/" for p in (base_url, ap_url) if p})

    def _on_interaction_received(interaction: Interaction) -> None:
        if getattr(interaction, "status", None) == InteractionStatus.DELETED:
            return

        target = interaction.target_resource or ""
        is_local_target = bool(valid_prefixes and target.startswith(valid_prefixes))
        mentioned_actors = getattr(interaction, "mentioned_actors", None) or []
        mentions_actor = bool(actor_url and actor_url in mentioned_actors)

        if not is_local_target and not mentions_actor:
            logger.debug("Skipping notification for non-local target: %s", target)
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
            content_text = html_to_text(interaction.content)
            lines.extend(["", "Content:", content_text])

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
