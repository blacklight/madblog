import email.utils
import hashlib
import os
import contextlib

from pathlib import Path
from typing import List, Optional, Tuple, Type
from email.utils import formatdate

from flask import (
    Flask,
    Response,
    has_app_context,
    has_request_context,
    make_response,
    render_template,
    request,
)
from webmentions import WebmentionDirection, WebmentionsHandler
from webmentions.server.adapters.flask import bind_webmentions

from .activitypub import ActivityPubMixin
from .config import config
from .feeds import FeedsMixin
from .markdown import MarkdownMixin
from .monitor import ChangeType, ContentMonitor
from .notifications import SmtpConfig, build_webmention_email_notifier
from .storage.mentions import FileWebmentionsStorage
from .tags import TagIndex
from ._sorters import PagesSorter, PagesSortByTime


class BlogApp(ActivityPubMixin, FeedsMixin, MarkdownMixin, Flask):
    """
    The main application class.
    """

    def __init__(self, *args, **kwargs):
        Flask.__init__(self, *args, template_folder=config.templates_dir, **kwargs)
        FeedsMixin.__init__(self, *args, **kwargs)

        self.pages_dir = (
            Path(Path(config.content_dir) / "markdown").expanduser().resolve()
        )
        self.img_dir = config.default_img_dir
        self.css_dir = config.default_css_dir
        self.js_dir = config.default_js_dir
        self.fonts_dir = config.default_fonts_dir

        if not os.path.isdir(self.pages_dir):
            # If the `markdown` subfolder does not exist, then the whole
            # `config.content_dir` is treated as the root for Markdown files.
            self.pages_dir = Path(config.content_dir).expanduser().resolve()

        img_dir = os.path.join(config.content_dir, "img")
        if os.path.isdir(img_dir):
            self.img_dir = os.path.abspath(img_dir)
        else:
            self.img_dir = config.content_dir

        css_dir = os.path.join(config.content_dir, "css")
        if os.path.isdir(css_dir):
            self.css_dir = os.path.abspath(css_dir)

        js_dir = os.path.join(config.content_dir, "js")
        if os.path.isdir(js_dir):
            self.js_dir = os.path.abspath(js_dir)

        fonts_dir = os.path.join(config.content_dir, "fonts")
        if os.path.isdir(fonts_dir):
            self.fonts_dir = os.path.abspath(fonts_dir)

        templates_dir = os.path.join(config.content_dir, "templates")
        if os.path.isdir(templates_dir):
            self.template_folder = os.path.abspath(templates_dir)

        self._register_ap_context_processors()
        self._init_webmentions()
        self._init_activitypub()
        self.tag_index = TagIndex(
            content_dir=config.content_dir,
            pages_dir=str(self.pages_dir),
            mentions_dir=str(self.mentions_dir),
        )

    @property
    def _app(self) -> Flask:
        return self

    def _init_webmentions(self):
        from . import __version__

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
            bind_webmentions(self, self.webmentions_handler)
            self.content_monitor.register(self.webmentions_storage.on_content_change)
            self.webmentions_storage.sync_on_startup()

    def _on_content_change_tags(self, _: ChangeType, filepath: str) -> None:
        """Bridge: forward content changes to the tag indexer."""
        self.tag_index.reindex_file(filepath)

    def start(self) -> None:
        from . import __version__

        self.logger.info(
            f"""
╭──────────────────────────────────────────────────────────────────╮
│                                                                  │
│   ███╗   ███╗ █████╗ ██████╗ ██████╗ ██╗      ██████╗  ██████╗   │
│   ████╗ ████║██╔══██╗██╔══██╗██╔══██╗██║     ██╔═══██╗██╔════╝   │
│   ██╔████╔██║███████║██║  ██║██████╔╝██║     ██║   ██║██║  ███╗  │
│   ██║╚██╔╝██║██╔══██║██║  ██║██╔══██╗██║     ██║   ██║██║   ██║  │
│   ██║ ╚═╝ ██║██║  ██║██████╔╝██████╔╝███████╗╚██████╔╝╚██████╔╝  │
│   ╚═╝     ╚═╝╚═╝  ╚═╝╚═════╝ ╚═════╝ ╚══════╝ ╚═════╝  ╚═════╝   │
│                                                                  │
╰──────────────────────────────────────────────────────────────────╯
⚡ version: {__version__}
              """
        )

        self.tag_index.build()
        self.content_monitor.register(self._on_content_change_tags)
        self.content_monitor.start()

    def stop(self) -> None:
        self.content_monitor.stop()

    @staticmethod
    def _generate_etag(mtime: float) -> str:
        """
        Generate an ETag based on modification time.

        :param mtime: File modification timestamp
        :return: ETag string (quoted)
        """
        # Use hash of timestamp for more compact ETag
        etag_hash = hashlib.md5(str(mtime).encode()).hexdigest()[:16]
        return f'"{etag_hash}"'

    def _check_cache_validity(self, file_mtime: float, etag: str) -> bool:
        """
        Check if the client's cached version is still valid.

        :param file_mtime: File modification timestamp
        :param etag: ETag for the current file version
        :return: True if the client's cache is valid (304 should be returned)
        """
        if not has_request_context():
            return False

        if_modified_since = request.headers.get("If-Modified-Since")
        if_none_match = request.headers.get("If-None-Match")

        # Check If-Modified-Since
        if if_modified_since:
            try:
                parsed_date = email.utils.parsedate_tz(if_modified_since)
                if parsed_date:
                    cached_timestamp = email.utils.mktime_tz(parsed_date)  # type: ignore
                    if cached_timestamp is not None and cached_timestamp >= file_mtime:
                        return True
            except (ValueError, TypeError, OverflowError):
                pass

        # Check If-None-Match (ETag)
        if if_none_match:
            client_etags = [tag.strip() for tag in if_none_match.split(",")]
            if etag in client_etags or "*" in client_etags:
                return True

        return False

    def _make_304_response(
        self,
        last_modified: str,
        etag: str,
        metadata: dict,
    ) -> Response:
        """
        Create a 304 Not Modified response with appropriate headers.
        """
        response = make_response("", 304)
        response.headers["Last-Modified"] = last_modified
        response.headers["ETag"] = etag

        article_language = metadata.get("language")
        if article_language:
            response.headers["Language"] = article_language
        elif config.language:
            response.headers["Language"] = config.language

        return response

    def _get_page_interactions(
        self,
        md_file: str,
        metadata: dict,
    ) -> Tuple[str, str]:
        """
        Retrieve webmentions and ActivityPub interactions for a page.

        :return: Tuple of (webmentions_html, ap_interactions_html)
        """
        mentions = self.webmentions_handler.render_webmentions(
            self.webmentions_handler.retrieve_stored_webmentions(
                config.link + metadata.get("uri", ""),
                direction=WebmentionDirection.IN,
            )
        )

        ap_interactions = ""
        if hasattr(self, "_ap_integration"):
            ap_object_url = self._ap_integration._file_to_url(md_file)
            interactions = self.activitypub_handler.storage.get_interactions(
                target_resource=ap_object_url
            )
            if interactions:
                ap_interactions = self.activitypub_handler.render_interactions(
                    interactions
                )

        return mentions, ap_interactions

    def _set_page_response_headers(
        self,
        response: Response,
        *,
        last_modified: str,
        etag: str,
        metadata: dict,
        as_markdown: bool = False,
    ) -> None:
        """
        Set cache, language, and Link headers on a page response.
        """
        response.headers["Last-Modified"] = last_modified
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

        article_language = metadata.get("language")
        if article_language:
            response.headers["Language"] = article_language
        elif config.language:
            response.headers["Language"] = config.language

        if config.webmention_url:
            response.headers.add(
                "Link",
                f'<{config.webmention_url}>; rel="webmention"',
            )

        if hasattr(self, "activitypub_handler"):
            if has_request_context():
                base_url = config.link or request.host_url.rstrip("/")
            else:
                base_url = config.link or ""

            page_url = base_url + metadata.get("uri", "")
            response.headers.add(
                "Link",
                f'<{page_url}>; rel="alternate"; type="application/activity+json"',
            )

        if as_markdown:
            response.mimetype = "text/markdown"

    def get_page(
        self,
        page: str,
        *,
        title: Optional[str] = None,
        as_markdown: bool = False,
        skip_header: bool = False,
        skip_html_head: bool = False,
    ) -> Response:
        """
        Get the HTML for a Markdown page

        :param page: The identifier/slug of the page to get
        :param title: The title of the page to get (overrides the title in the
            Markdown file metadata)
        :param as_markdown: Return the page content as Markdown, without rendering
            it as HTML (default: False)
        :param skip_header: Don't render the header (default: False)
        :param skip_html_head: Don't render the HTML head (default: False)
        """
        if not page.endswith(".md"):
            page = page + ".md"

        metadata = self._parse_page_metadata(page)
        md_file = metadata.pop("md_file")

        # Get file modification time for cache headers
        file_stat = os.stat(md_file)
        file_mtime = file_stat.st_mtime
        last_modified = formatdate(file_mtime, usegmt=True)
        etag = self._generate_etag(file_mtime)

        # Return 304 if client cache is valid
        if self._check_cache_validity(file_mtime, etag):
            return self._make_304_response(last_modified, etag, metadata)

        # Return ActivityPub response if client prefers it
        if self._client_prefers_activitypub():
            ap_response = self._get_activitypub_page_response(
                md_file=md_file,
                metadata=metadata,
                last_modified=last_modified,
                etag=etag,
            )
            if ap_response:
                return ap_response

        # Render content
        title = title or metadata.get("title") or config.title
        if as_markdown:
            with open(md_file, "r") as f:
                content = self._parse_markdown_content(f)
            output = f"# {title}\n\n{content}"
        else:
            mentions, ap_interactions = self._get_page_interactions(md_file, metadata)
            output = self._render_page_html(
                md_file=md_file,
                metadata=metadata,
                title=title,
                skip_header=skip_header,
                skip_html_head=skip_html_head,
                mentions=mentions,
                ap_interactions=ap_interactions,
            )

        response = make_response(output)
        self._set_page_response_headers(
            response,
            last_modified=last_modified,
            etag=etag,
            metadata=metadata,
            as_markdown=as_markdown,
        )

        return response

    def _get_page_content(self, page: str, **kwargs) -> str:
        """Return the HTML content of a page as a string (not a Response)."""
        result = self.get_page(page, **kwargs)
        if isinstance(result, Response):
            return result.get_data(as_text=True)
        return str(result) if result else ""

    def _get_pages_from_files(
        self,
        *,
        with_content: bool = False,
        skip_header: bool = False,
        skip_html_head: bool = False,
    ):
        pages_dir = str(self.pages_dir).rstrip("/")
        return [
            {
                "path": os.path.join(root[len(pages_dir) + 1 :], f),
                "folder": root[len(pages_dir) + 1 :],
                "content": (
                    self._get_page_content(
                        os.path.join(root, f),
                        skip_header=skip_header,
                        skip_html_head=skip_html_head,
                    )
                    if with_content
                    else ""
                ),
                **self._parse_page_metadata(
                    os.path.join(root[len(pages_dir) + 1 :], f)
                ),
            }
            for root, _, files in os.walk(pages_dir, followlinks=True)
            for f in files
            if f.endswith(".md")
        ]

    def get_pages(
        self,
        *,
        with_content: bool = False,
        skip_header: bool = False,
        skip_html_head: bool = False,
        sorter: Type[PagesSorter] = PagesSortByTime,
        reverse: bool = True,
    ) -> List[Tuple[int, dict]]:
        local_pages = self._get_pages_from_files(
            with_content=with_content,
            skip_header=skip_header,
            skip_html_head=skip_html_head,
        )

        remote_pages = self._get_pages_from_feeds(with_content=with_content)
        pages = local_pages + remote_pages
        pages.sort(key=sorter(pages), reverse=reverse)
        return list(enumerate(pages))

    def get_pages_response(
        self,
        *,
        with_content: bool = False,
        skip_header: bool = False,
        skip_html_head: bool = False,
        sorter: Type[PagesSorter] = PagesSortByTime,
        reverse: bool = True,
        template_name: str = "index.html",
        view_mode: str = "cards",
        **extra_context,
    ) -> Response:
        """
        Get a Response for the pages list with proper cache headers.

        :param with_content: Include full content for each page
        :param skip_header: Skip header in rendered content
        :param skip_html_head: Skip HTML head in rendered content
        :param sorter: Sorter class to use for page ordering
        :param reverse: Reverse sort order
        :param template_name: Template name to render
        :param view_mode: View mode for the template
        """
        # Get the most recent modification time from the pages data
        most_recent_mtime = 0.0

        # Get the pages data first (this includes file_mtime for each local page)
        pages = self.get_pages(
            with_content=with_content,
            skip_header=skip_header,
            skip_html_head=skip_html_head,
            sorter=sorter,
            reverse=reverse,
        )

        # Find the most recent modification time from the pages data
        for _, page_data in pages:
            # Only consider local files (those with file_mtime), not external feeds
            if "file_mtime" in page_data:
                most_recent_mtime = max(most_recent_mtime, page_data["file_mtime"])

        # Format the most recent modification time for HTTP headers
        last_modified = (
            formatdate(most_recent_mtime, usegmt=True)
            if most_recent_mtime > 0
            else None
        )

        # Generate ETag based on most recent modification time
        etag = self._generate_etag(most_recent_mtime) if most_recent_mtime > 0 else None

        # Check if the client has a cached version that's still valid
        # Check both If-Modified-Since and If-None-Match headers
        cache_valid = False

        if last_modified and most_recent_mtime > 0 and has_request_context():
            if_modified_since = request.headers.get("If-Modified-Since")
            if_none_match = request.headers.get("If-None-Match")

            # Check If-Modified-Since
            if if_modified_since and not cache_valid:
                try:
                    cached_timestamp = email.utils.mktime_tz(
                        email.utils.parsedate_tz(if_modified_since)  # type: ignore
                    )
                    if (
                        cached_timestamp is not None
                        and cached_timestamp >= most_recent_mtime
                    ):
                        cache_valid = True
                except (ValueError, TypeError, OverflowError):
                    # Invalid If-Modified-Since header, ignore it
                    pass

            # Check If-None-Match (ETag)
            if if_none_match and etag and not cache_valid:
                client_etags = [tag.strip() for tag in if_none_match.split(",")]
                if etag in client_etags or "*" in client_etags:
                    cache_valid = True

            # Return 304 if cache is valid
            if cache_valid:
                response = make_response("", 304)
                if last_modified:
                    response.headers["Last-Modified"] = last_modified
                if etag:
                    response.headers["ETag"] = etag
                response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

                # Add Language header
                if config.language:
                    response.headers["Language"] = config.language

                return response

        with contextlib.ExitStack() as stack:
            if not has_app_context():
                stack.enter_context(self.app_context())

            response = make_response(
                render_template(
                    template_name,
                    pages=pages,
                    config=config,
                    view_mode=view_mode,
                    **extra_context,
                )
            )

        # Create response with cache headers
        if last_modified:
            response.headers["Last-Modified"] = last_modified
            response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

        if etag:
            response.headers["ETag"] = etag

        # Set Language header from global config for home page
        if config.language:
            response.headers["Language"] = config.language

        return response


app = BlogApp(__name__)

from .routes import *

# vim:sw=4:ts=4:et:
