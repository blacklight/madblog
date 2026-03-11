import logging
from abc import ABC, abstractmethod
from pathlib import Path

from flask import Flask
from markupsafe import Markup
from webmentions import WebmentionDirection, WebmentionsHandler
from webmentions.server.adapters.flask import bind_webmentions

from madblog.config import config
from madblog.moderation import is_allowed, is_blocked, is_actor_permitted
from madblog.monitor import ContentMonitor

from ._notifications import SmtpConfig, build_webmention_email_notifier
from ._storage import FileWebmentionsStorage

logger = logging.getLogger(__name__)


class WebmentionsMixin(ABC):  # pylint: disable=too-few-public-methods
    """
    Mixin for Webmentions support.
    """

    pages_dir: Path

    @property
    @abstractmethod
    def _app(self) -> Flask: ...

    def _init_webmentions(self):
        from madblog import __version__

        self.mentions_dir = config.resolved_state_dir / "mentions"

        self.webmentions_storage = FileWebmentionsStorage(
            content_dir=self.pages_dir,
            mentions_dir=self.mentions_dir,
            base_url=config.link,
            root_dir=config.content_dir,
            webmentions_hard_delete=config.webmentions_hard_delete,
        )

        on_mention_processed = None
        if config.author_email and config.smtp_server:
            on_mention_processed = build_webmention_email_notifier(
                recipient=config.author_email,
                blog_base_url=config.link,
                smtp=SmtpConfig(
                    server=config.smtp_server,
                    port=config.smtp_port,
                    username=config.smtp_username,
                    password=config.smtp_password,
                    starttls=config.smtp_starttls,
                    enable_starttls_auto=config.smtp_enable_starttls_auto,
                    sender=config.smtp_sender,
                ),
            )

        self.webmentions_handler = WebmentionsHandler(
            storage=self.webmentions_storage,
            base_url=config.link,
            user_agent=f"Madblog/{__version__} ({config.link})",
            on_mention_processed=on_mention_processed,
        )

        self.content_monitor = ContentMonitor(
            root_dir=str(self.pages_dir),
            throttle_seconds=config.throttle_seconds_on_update,
        )

        self.webmentions_storage.set_handler(self.webmentions_handler)
        self._install_webmention_moderation()

        if config.enable_webmentions:
            bind_webmentions(self._app, self.webmentions_handler)
            self.content_monitor.register(self.webmentions_storage.on_content_change)
            self.webmentions_storage.sync_on_startup()

    def _install_webmention_moderation(self):
        """
        Wrap the incoming webmention processor so that mentions from
        non-permitted actors are silently dropped before any storage or
        network I/O.

        In blocklist mode, mentions from blocked sources are rejected.
        In allowlist mode, only mentions from allowed sources are accepted.
        """
        original = self.webmentions_handler.process_incoming_webmention

        def _filtered_process(source_url, target_url):
            if source_url and not is_actor_permitted(source_url):
                logger.info("Rejected webmention from %s", source_url)
                return None
            return original(source_url, target_url)

        self.webmentions_handler.process_incoming_webmention = _filtered_process

    def _get_rendered_webmentions(self, metadata: dict) -> Markup:
        """
        Retrieve a Markup object with rendered Webmentions for the given page
        metadata.
        """
        mentions = self.webmentions_handler.retrieve_stored_webmentions(
            config.link + metadata.get("uri", ""),
            direction=WebmentionDirection.IN,
        )

        if config.blocked_actors:
            mentions = [
                m for m in mentions if not is_blocked(m.source, config.blocked_actors)
            ]
        elif config.allowed_actors:
            mentions = [
                m for m in mentions if is_allowed(m.source, config.allowed_actors)
            ]

        return self.webmentions_handler.render_webmentions(mentions)
