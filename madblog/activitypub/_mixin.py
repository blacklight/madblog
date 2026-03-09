import json
import os
import re
import stat
import threading
from urllib.parse import urlparse
from abc import ABC, abstractmethod
from logging import getLogger
from pathlib import Path

from flask import Flask, Response, has_request_context, make_response, request

from ..config import config
from ..monitor import ContentMonitor
from ._notifications import (
    SmtpConfig,
    build_activitypub_email_notifier,
)

logger = getLogger(__name__)


class ActivityPubMixin(ABC):  # pylint: disable=too-few-public-methods
    """
    Mixin that wraps the ActivityPub features for the main application.
    """

    content_monitor: ContentMonitor
    pages_dir: Path

    @property
    @abstractmethod
    def _app(self) -> Flask: ...

    def _register_ap_context_processors(self):
        @self._app.context_processor
        def inject_followers_count():
            if not config.enable_activitypub:
                return {"followers_count": 0}
            if not hasattr(self, "activitypub_storage"):
                return {"followers_count": 0}
            try:
                return {
                    "followers_count": len(self.activitypub_storage.get_followers())
                }
            except Exception:
                return {"followers_count": 0}

        @self._app.context_processor
        def inject_activitypub_handle():
            if not config.enable_activitypub:
                return {"activitypub_handle": None}

            domain = config.activitypub_domain
            if not domain:
                base_url = config.activitypub_link or config.link
                parsed = urlparse(base_url)
                domain = parsed.hostname

            if not domain:
                return {"activitypub_handle": None}

            return {"activitypub_handle": f"@{config.activitypub_username}@{domain}"}

        logger.debug(
            "Registered ActivityPub context processors: %s",
            [
                inject_followers_count,
                inject_activitypub_handle,
            ],
        )

    def _generate_or_check_ap_key(self, key_path: str) -> str:
        from pubby.crypto import generate_rsa_keypair, export_private_key_pem

        key_path = os.path.abspath(os.path.expanduser(key_path))
        if not os.path.isfile(key_path):
            private_key, _ = generate_rsa_keypair()
            pem = export_private_key_pem(private_key)
            with open(key_path, "w") as f:
                f.write(pem)

            os.chmod(key_path, 0o600)
            logger.info("Generated ActivityPub private key at %s", key_path)

        # Check permissions: must not be readable by group/others
        st = os.stat(key_path)
        if st.st_mode & (stat.S_IRGRP | stat.S_IROTH):
            raise RuntimeError(
                f"ActivityPub private key file {key_path} is readable "
                "by group or others. Fix permissions with: "
                f"chmod 600 {key_path}"
            )

        return key_path

    def _init_activitypub(self):
        if not config.enable_activitypub:
            return

        try:
            from pubby import ActivityPubHandler
            from pubby.storage.adapters.file import FileActivityPubStorage
            from pubby.server.adapters.flask import bind_activitypub
            from ._integration import ActivityPubIntegration
        except ImportError:
            logger.error(
                "ActivityPub is enabled but pubby is not installed. "
                "Install it with: pip install 'madblog[activitypub]'"
            )
            return

        from madblog import __version__

        ap_dir = os.path.join(config.content_dir, "activitypub")
        os.makedirs(ap_dir, exist_ok=True)

        # Key management
        key_path = os.path.expanduser(
            config.activitypub_private_key_path
            or os.path.join(ap_dir, "private_key.pem")
        )

        self._generate_or_check_ap_key(key_path)
        self.activitypub_storage = FileActivityPubStorage(data_dir=ap_dir)

        on_interaction = None
        if (
            config.author_email
            and config.smtp_server
            and config.activitypub_email_notifications
        ):
            on_interaction = build_activitypub_email_notifier(
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

        # Build profile metadata links (Mastodon "verified" fields)
        actor_attachment = []
        if config.link:
            actor_attachment.append(
                {
                    "type": "PropertyValue",
                    "name": config.activitypub_profile_field_name,
                    "value": (
                        f'<a href="{config.link}" rel="me">'
                        + re.sub(r"^(https?://)(.*)/*$", r"\2", config.link)
                        + "</a>"
                    ),
                }
            )

        if config.activitypub_profile_fields:
            for name, value in config.activitypub_profile_fields.items():
                value_str = str(value)
                if re.match(r"^https?://", value_str):
                    actor_attachment.append(
                        {
                            "type": "PropertyValue",
                            "name": str(name),
                            "value": (
                                f'<a href="{value_str}" rel="me">'
                                + re.sub(r"^(https?://)(.*)/*$", r"\2", value_str)
                                + "</a>"
                            ),
                        }
                    )
                else:
                    actor_attachment.append(
                        {
                            "type": "PropertyValue",
                            "name": str(name),
                            "value": value_str,
                        }
                    )

        ap_base_url = (config.activitypub_link or config.link).rstrip("/")

        # Create the ActivityPub handler
        self.activitypub_handler = ActivityPubHandler(
            storage=self.activitypub_storage,
            actor_config={
                "base_url": ap_base_url,
                "username": config.activitypub_username,
                "name": (config.activitypub_name or config.author or config.title),
                "summary": (config.activitypub_summary or config.description),
                "icon_url": (config.activitypub_icon_url or config.author_photo or ""),
                "manually_approves_followers": (
                    config.activitypub_manually_approves_followers
                ),
                "attachment": actor_attachment,
                "url": f'{config.link.rstrip("/")}/@{config.activitypub_username}',
            },
            private_key_path=key_path,
            webfinger_domain=config.activitypub_domain,
            on_interaction_received=on_interaction,
            auto_approve_quotes=config.activitypub_auto_approve_quotes,
            software_name="madblog",
            software_version=__version__,
        )

        app: Flask = self  # type: ignore
        bind_activitypub(app, self.activitypub_handler)
        self._ap_integration = ActivityPubIntegration(
            handler=self.activitypub_handler,
            pages_dir=str(self.pages_dir),
            base_url=ap_base_url,
            content_base_url=config.link,  # Images served at actual blog URL
        )
        self.content_monitor.register(self._ap_integration.on_content_change)

        def _ap_startup_tasks():
            self._ap_integration.sync_on_startup()

            # Push the current actor profile to all followers so remote
            # instances pick up attachment/field changes (e.g. verified links).
            try:
                self.activitypub_handler.publish_actor_update()
            except Exception:
                logger.warning("Failed to publish actor profile update", exc_info=True)

        threading.Thread(target=_ap_startup_tasks, daemon=True).start()

    def _client_prefers_activitypub(self) -> bool:
        """
        Check if the client prefers ActivityPub format over HTML.
        """
        if not has_request_context():
            return False

        accepts_ap = (
            request.accept_mimetypes["application/activity+json"]
            or request.accept_mimetypes["application/ld+json"]
        )

        return bool(
            accepts_ap
            and (
                request.accept_mimetypes["application/activity+json"]
                > request.accept_mimetypes["text/html"]
            )
        )

    def _get_activitypub_page_response(
        self,
        *,
        md_file: str,
        metadata: dict,
        last_modified: str,
        etag: str,
    ) -> Response | None:
        if not (
            hasattr(self, "activitypub_handler") and hasattr(self, "_ap_integration")
        ):
            return None

        accepts_ap = (
            request.accept_mimetypes["application/activity+json"]
            or request.accept_mimetypes["application/ld+json"]
        )
        if not accepts_ap:
            return None

        ap_url = self._ap_integration.file_to_url(md_file)

        # When the AP domain differs from the blog domain and the request
        # arrived at the blog domain, redirect AP clients to the canonical
        # AP-domain URL.  Mastodon follows redirects during URL resolution,
        # so the remote instance will fetch the object at its canonical ``id``
        # and pass the origin check.
        ap_link = (config.activitypub_link or "").rstrip("/")
        blog_link = (config.link or "").rstrip("/")
        if ap_link and ap_link != blog_link:
            ap_host = urlparse(ap_link).hostname
            request_host = request.host.split(":")[0]
            if request_host != ap_host:
                from flask import redirect

                return redirect(ap_url, code=302)  # type: ignore

        from pubby._model import AP_CONTEXT

        base_url = config.link or request.host_url.rstrip("/")
        public_url = base_url.rstrip("/") + metadata.get("uri", "")
        obj, _ = self._ap_integration.build_object(
            md_file,
            ap_url,
            self.activitypub_handler.actor_id,
            public_url=public_url,
        )
        doc = obj.to_dict()
        doc["@context"] = AP_CONTEXT

        response = make_response(json.dumps(doc, ensure_ascii=False))
        response.mimetype = "application/activity+json"
        response.headers["Last-Modified"] = last_modified
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

        article_language = metadata.get("language")
        if article_language:
            response.headers["Language"] = article_language
        elif config.language:
            response.headers["Language"] = config.language

        return response

    def _get_rendered_ap_interactions(self, md_file: str) -> str:
        """
        Retrieve ActivityPub interactions for a given page.

        :return: Tuple of (webmentions_html, ap_interactions_html)
        """
        ap_interactions = ""
        ap_integration = getattr(self, "_ap_integration", None)
        if not ap_integration:
            return ap_interactions

        ap_object_url = ap_integration.file_to_url(md_file)
        interactions = self.activitypub_handler.storage.get_interactions(
            target_resource=ap_object_url
        )

        if interactions:
            ap_interactions = self.activitypub_handler.render_interactions(interactions)

        return ap_interactions
