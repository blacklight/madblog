import fcntl
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
from pubby import ActivityPubHandler
from pubby._model import AP_CONTEXT
from pubby.storage.adapters.file import FileActivityPubStorage
from pubby.server.adapters.flask import bind_activitypub
from pubby.server.adapters.flask_mastodon import bind_mastodon_api

from ..config import config
from ..moderation import (
    ModerationCache,
    is_allowed,
    is_blocked,
    validate_moderation_config,
)
from ..monitor import ContentMonitor
from ._integration import ActivityPubIntegration
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
            Path(key_path).parent.mkdir(parents=True, exist_ok=True)
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

        from madblog import __version__

        ap_state_dir = config.resolved_state_dir / "activitypub" / "state"
        ap_state_dir.mkdir(parents=True, exist_ok=True)

        # Key management (key stored at activitypub/ level, not inside state/)
        default_key_path = config.resolved_state_dir / "activitypub" / "private_key.pem"
        key_path = os.path.expanduser(
            config.activitypub_private_key_path or str(default_key_path)
        )

        self._generate_or_check_ap_key(key_path)
        self.activitypub_storage = FileActivityPubStorage(data_dir=str(ap_state_dir))

        on_interaction = None
        if (
            config.author_email
            and config.smtp_server
            and config.activitypub_email_notifications
        ):
            ap_base_url = (config.activitypub_link or config.link).rstrip("/")
            on_interaction = build_activitypub_email_notifier(
                recipient=config.author_email,
                blog_base_url=config.link,
                ap_base_url=ap_base_url,
                actor_url=config.activitypub_actor_url,
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
                        + config.link
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
                                + value_str
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

        # Build list of local base URLs for interaction filtering
        local_base_urls = [ap_base_url]
        if config.link and config.link.rstrip("/") != ap_base_url:
            local_base_urls.append(config.link.rstrip("/"))

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
            store_local_only=True,
            local_base_urls=local_base_urls,
            software_name="madblog",
            software_version=__version__,
            async_delivery=True,
        )

        self._install_activitypub_moderation()

        app: Flask = self  # type: ignore
        bind_activitypub(app, self.activitypub_handler)

        # Content negotiation for /ap/actor: serve the home page when
        # the client prefers HTML (e.g. a browser following the actor link).
        # This must be registered as a before_request handler because pubby's
        # route always returns JSON.
        # Instead of redirecting, we serve the actual page content so that
        # Mastodon can find rel="me" links for profile verification. A JavaScript
        # redirect is injected to send human users to the canonical home page.
        @app.before_request
        def _actor_html_redirect():
            if request.path == "/ap/actor" and request.method == "GET":
                if not self._ap_accept_quality():
                    # Client does not want ActivityPub JSON; serve home page
                    # with JS redirect instead of HTTP redirect.
                    from .._sorters import PagesSortByTimeGroupedByFolder

                    view_mode = request.args.get("view", config.view_mode)
                    if view_mode not in ("cards", "list", "full"):
                        view_mode = config.view_mode

                    return app.get_pages_response(  # type: ignore
                        sorter=PagesSortByTimeGroupedByFolder,
                        with_content=(view_mode == "full"),
                        skip_header=True,
                        skip_html_head=True,
                        template_name="index.html",
                        view_mode=view_mode,
                        followers_count=len(self.activitypub_storage.get_followers()),
                        meta_redirect_to="/",
                    )
            return None

        bind_mastodon_api(
            app,
            self.activitypub_handler,
            title=config.title,
            description=config.description,
            contact_email=config.author_email or "",
            software_name="madblog",
            software_version=__version__,
        )
        self._ap_integration = ActivityPubIntegration(
            handler=self.activitypub_handler,
            pages_dir=str(self.pages_dir),
            base_url=ap_base_url,
            content_base_url=config.link,  # Images served at actual blog URL
            replies_dir=getattr(self, "replies_dir", None),
        )
        self.content_monitor.register(self._ap_integration.on_content_change)

        def _ap_startup_tasks():
            # Use a file lock to prevent multiple workers from syncing simultaneously
            lock_file = self._ap_integration.workdir / ".startup_sync.lock"
            try:
                with open(lock_file, "w") as f:
                    try:
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        logger.debug(
                            "Another worker is running startup sync, skipping"
                        )
                        return

                    try:
                        self._ap_integration.sync_on_startup()
                        self._ap_integration.sync_replies_on_startup()

                        # Push the current actor profile to all followers so remote
                        # instances pick up attachment/field changes.
                        try:
                            self.activitypub_handler.publish_actor_update()
                        except Exception:
                            logger.warning(
                                "Failed to publish actor profile update", exc_info=True
                            )
                    finally:
                        fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                logger.warning("Startup sync failed", exc_info=True)

        self._ap_startup_thread = threading.Thread(
            target=_ap_startup_tasks, daemon=True
        )
        self._ap_startup_thread.start()

    @staticmethod
    def _ap_accept_quality() -> float:
        """
        Return the highest quality value for ActivityPub-compatible
        mimetypes in the current request's ``Accept`` header.

        Werkzeug's ``MIMEAccept`` treats parameterised media types
        (e.g. ``application/ld+json; profile="…"``) as distinct from
        their bare counterparts, so a simple key lookup may miss them.
        This helper strips parameters before comparing.
        """
        ap_types = {"application/activity+json", "application/ld+json"}
        best: float = 0
        for mimetype, quality in request.accept_mimetypes:
            base = mimetype.split(";", 1)[0].strip()
            if base in ap_types and quality > best:
                best = quality
        return best

    def _client_prefers_activitypub(self) -> bool:
        """
        Check if the client prefers ActivityPub format over HTML.
        """
        if not has_request_context():
            return False

        ap_quality = self._ap_accept_quality()
        return bool(ap_quality and ap_quality > request.accept_mimetypes["text/html"])

    def _get_activitypub_object_response(
        self,
        *,
        ap_url: str,
        public_url: str,
        build_fn,
        metadata: dict,
        last_modified: str,
        etag: str,
    ) -> Response | None:
        """
        Shared helper: return an AP JSON response (or split-domain redirect)
        for any content object (article or reply).

        :param ap_url: Canonical AP-domain object ``id``.
        :param public_url: Human-facing URL stored in the AP ``url`` field.
        :param build_fn: Callable ``(md_file, ap_url, actor_id, public_url)``
            that returns ``(Object, activity_type)``.
        """
        if not (
            hasattr(self, "activitypub_handler") and hasattr(self, "_ap_integration")
        ):
            return None

        if not self._ap_accept_quality():
            return None

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

        obj, _ = build_fn(ap_url, public_url)
        doc = obj.to_dict()
        doc["@context"] = AP_CONTEXT

        response = make_response(json.dumps(doc, ensure_ascii=False))
        response.mimetype = "application/activity+json"
        response.headers["Last-Modified"] = last_modified
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

        language = metadata.get("language")
        if language:
            response.headers["Language"] = language
        elif config.language:
            response.headers["Language"] = config.language

        return response

    def _get_activitypub_page_response(
        self,
        *,
        md_file: str,
        metadata: dict,
        last_modified: str,
        etag: str,
    ) -> Response | None:
        base_url = config.link or request.host_url.rstrip("/")
        return self._get_activitypub_object_response(
            ap_url=self._ap_integration.file_to_url(md_file),
            public_url=base_url.rstrip("/") + metadata.get("uri", ""),
            build_fn=lambda ap_url, public_url: self._ap_integration.build_object(
                md_file,
                ap_url,
                self.activitypub_handler.actor_id,
                public_url=public_url,
            ),
            metadata=metadata,
            last_modified=last_modified,
            etag=etag,
        )

    def _get_activitypub_reply_response(
        self,
        *,
        md_file: str,
        metadata: dict,
        last_modified: str,
        etag: str,
        article_slug: str | None,
        reply_slug: str,
    ) -> Response | None:
        """
        Return an AP JSON response (or redirect) for an author reply.

        For standalone likes (``like-of`` present, no ``reply-to``, no
        content beyond heading), the response is a ``Like`` activity
        rather than a ``Note`` object.
        """
        if not (
            hasattr(self, "activitypub_handler") and hasattr(self, "_ap_integration")
        ):
            return None

        if not self._ap_accept_quality():
            return None

        like_of = metadata.get("like-of")
        has_reply_to = "reply-to" in metadata
        has_content = bool(
            self._ap_integration._clean_content(  # pylint: disable=protected-access
                md_file
            ).strip()
        )

        if like_of and not has_reply_to and not has_content:
            # Standalone like: return the Like activity JSON
            return self._get_activitypub_like_response(
                md_file=md_file,
                like_of=like_of,
                metadata=metadata,
                last_modified=last_modified,
                etag=etag,
            )

        base_url = (config.link or request.host_url.rstrip("/")).rstrip("/")

        # Handle unlisted posts (article_slug=None)
        public_url = (
            f"{base_url}/reply/{reply_slug}"
            if article_slug is None
            else f"{base_url}/reply/{article_slug}/{reply_slug}"
        )

        return self._get_activitypub_object_response(
            ap_url=self._ap_integration.reply_file_to_url(md_file),
            public_url=public_url,
            build_fn=lambda ap_url, canonical_url: self._ap_integration.build_reply_object(
                md_file,
                ap_url,
                self.activitypub_handler.actor_id,
                public_url=canonical_url,
            ),
            metadata=metadata,
            last_modified=last_modified,
            etag=etag,
        )

    def _get_activitypub_like_response(
        self,
        *,
        md_file: str,
        like_of: str,
        metadata: dict,
        last_modified: str,
        etag: str,
    ) -> Response | None:
        """
        Return a Like activity JSON response for a standalone like.

        If the Like was previously published and its activity ID is
        stored, use that ID.  Otherwise build a fresh Like activity dict.
        """
        # Split-domain redirect check
        ap_link = (config.activitypub_link or "").rstrip("/")
        blog_link = (config.link or "").rstrip("/")
        if ap_link and ap_link != blog_link:
            ap_host = urlparse(ap_link).hostname
            request_host = request.host.split(":")[0]
            if request_host != ap_host:
                from flask import redirect

                ap_url = self._ap_integration.reply_file_to_url(md_file)
                return redirect(ap_url, code=302)  # type: ignore

        # Try to retrieve the stored Like activity ID
        stored_like_id = (
            self._ap_integration._get_reply_like_id(  # pylint: disable=protected-access
                md_file
            )
        )

        actor_id = self.activitypub_handler.actor_id

        if stored_like_id:
            # Reconstruct a minimal Like activity from stored data
            doc = {
                "@context": AP_CONTEXT,
                "id": stored_like_id,
                "type": "Like",
                "actor": actor_id,
                "object": like_of,
                "to": ["https://www.w3.org/ns/activitystreams#Public"],
                "cc": [self.activitypub_handler.followers_url],
            }
        else:
            # Build a fresh Like activity (not yet published)
            doc = self.activitypub_handler.outbox.build_like_activity(like_of)

        response = make_response(json.dumps(doc, ensure_ascii=False))
        response.mimetype = "application/activity+json"
        response.headers["Last-Modified"] = last_modified
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

        language = metadata.get("language")
        if language:
            response.headers["Language"] = language
        elif config.language:
            response.headers["Language"] = config.language

        return response

    def _install_activitypub_moderation(self):
        """
        Install moderation hooks for ActivityPub:

        1. Validate that blocklist and allowlist are not both configured.
        2. Wrap the inbox processor so that activities from non-permitted
           actors are silently dropped.
        3. Wrap ``storage.get_followers()`` so that non-permitted followers
           are excluded from fan-out delivery and public counts.
        4. Run a one-time startup reconciliation that marks newly
           blocked followers (and restores previously blocked ones
           whose matching rule was removed).

        The moderation lists are held in a :class:`ModerationCache` with a
        5-minute TTL so that fan-out delivery does not hit the
        filesystem on every publish.
        """
        validate_moderation_config()
        self._blocklist_cache = ModerationCache()

        # --- 1. Wrap inbox ---
        original_inbox = self.activitypub_handler.process_inbox_activity

        def _filtered_process(activity_data: dict, *args, **kwargs):
            actor = activity_data.get("actor", "")
            if actor and not self._blocklist_cache.is_permitted(actor):
                logger.info("Rejected ActivityPub activity from %s", actor)
                return None
            return original_inbox(activity_data, *args, **kwargs)

        self.activitypub_handler.process_inbox_activity = _filtered_process

        # --- 2. Wrap get_followers ---
        original_get_followers = self.activitypub_storage.get_followers

        def _filtered_get_followers() -> list:
            followers = original_get_followers()
            return [
                f for f in followers if self._blocklist_cache.is_permitted(f.actor_id)
            ]

        self.activitypub_storage.get_followers = _filtered_get_followers

        # --- 3. Startup reconciliation ---
        self._reconcile_blocked_followers()

    def _reconcile_blocked_followers(self):
        """
        Synchronise the ``"blocked"`` flag stored in each follower's
        JSON file with the current moderation configuration.

        **Blocklist mode** (``blocked_actors`` configured):
        - Followers that match the blocklist are marked ``"blocked": true``.
        - Followers previously marked blocked whose matching rule has
          been removed are restored (``"blocked"`` key is deleted).

        **Allowlist mode** (``allowed_actors`` configured):
        - Followers that do NOT match the allowlist are marked
          ``"blocked": true``.
        - Followers previously marked blocked who now match the allowlist
          are restored.
        """
        storage = self.activitypub_storage
        followers_dir = storage.data_dir / "followers"
        if not followers_dir.is_dir():
            return

        blocklist = list(config.blocked_actors)
        allowlist = list(config.allowed_actors)

        for fpath in storage.list_json_files(followers_dir):
            data = storage.read_json(fpath)
            if data is None:
                continue

            actor_id = data.get("actor_id", "")
            is_currently_marked = data.get("blocked", False)

            # Determine if the actor should be blocked
            if allowlist:
                # Allowlist mode: block those NOT matching the allowlist
                should_be_blocked = not is_allowed(actor_id, allowlist)
            elif blocklist:
                # Blocklist mode: block those matching the blocklist
                should_be_blocked = is_blocked(actor_id, blocklist)
            else:
                # No moderation configured
                should_be_blocked = False

            if should_be_blocked and not is_currently_marked:
                data["blocked"] = True
                storage.write_json(fpath, data)
                logger.info("Marked follower %s as blocked", actor_id)
            elif not should_be_blocked and is_currently_marked:
                data.pop("blocked", None)
                storage.write_json(fpath, data)
                logger.info("Restored previously blocked follower %s", actor_id)

    def _filter_ap_interactions(self, interactions: list) -> list:
        """Apply blocklist/allowlist filtering to AP interactions."""
        mod_cache = getattr(self, "_blocklist_cache", None)
        if mod_cache:
            return [
                i for i in interactions if mod_cache.is_permitted(i.source_actor_id)
            ]
        if config.blocked_actors:
            return [
                i
                for i in interactions
                if not is_blocked(i.source_actor_id, config.blocked_actors)
            ]
        if config.allowed_actors:
            return [
                i
                for i in interactions
                if is_allowed(i.source_actor_id, config.allowed_actors)
            ]
        return list(interactions)

    def _get_ap_interactions(
        self, md_file: str, extra_target_urls: list[str] | None = None
    ) -> list:
        """
        Retrieve raw ActivityPub Interaction objects for a given page.

        :param md_file: The Markdown file for the article.
        :param extra_target_urls: Additional AP object URLs to fetch
            interactions for (e.g. author reply URLs).
        """
        ap_integration = getattr(self, "_ap_integration", None)
        if not ap_integration:
            return []

        storage = self.activitypub_handler.storage
        ap_object_url = ap_integration.file_to_url(md_file)
        interactions = list(storage.get_interactions(target_resource=ap_object_url))

        for url in extra_target_urls or []:
            interactions.extend(storage.get_interactions(target_resource=url))

        return self._filter_ap_interactions(interactions)

    def _get_rendered_ap_interactions(self, md_file: str) -> str:
        """
        Retrieve rendered ActivityPub interactions for a given page.
        """
        interactions = self._get_ap_interactions(md_file)
        if interactions:
            return self.activitypub_handler.render_interactions(interactions)
        return ""
