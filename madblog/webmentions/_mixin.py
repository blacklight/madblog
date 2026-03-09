from abc import ABC, abstractmethod
from pathlib import Path

from flask import Flask
from markupsafe import Markup
from webmentions import WebmentionDirection, WebmentionsHandler
from webmentions.server.adapters.flask import bind_webmentions

from madblog.config import config
from madblog.monitor import ContentMonitor

from ._notifications import SmtpConfig, build_webmention_email_notifier
from ._storage import FileWebmentionsStorage


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

        self.mentions_dir = (
            Path(Path(config.content_dir) / "mentions").expanduser().resolve()
        )

        self.webmentions_storage = FileWebmentionsStorage(
            content_dir=self.pages_dir,
            mentions_dir=self.mentions_dir,
            base_url=config.link,
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

        if config.enable_webmentions:
            bind_webmentions(self._app, self.webmentions_handler)
            self.content_monitor.register(self.webmentions_storage.on_content_change)
            self.webmentions_storage.sync_on_startup()

    def _get_rendered_webmentions(self, metadata: dict) -> Markup:
        """
        Retrieve a Markup object with rendered Webmentions for the given page
        metadata.
        """
        return self.webmentions_handler.render_webmentions(
            self.webmentions_handler.retrieve_stored_webmentions(
                config.link + metadata.get("uri", ""),
                direction=WebmentionDirection.IN,
            )
        )
