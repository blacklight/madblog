import contextlib
import hashlib
import json
import os

from pathlib import Path
from urllib.parse import quote, urlparse
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

from .activitypub import ActivityPubMixin
from .cache import (
    CachedPage,
    check_cache_validity,
    compute_pages_mtime,
    generate_etag,
    make_304_response,
    set_cache_headers,
)
from .config import config
from .feeds import FeedsMixin
from .guestbook import GuestbookMixin
from .markdown import MarkdownMixin
from .monitor import ChangeType, ContentMonitor
from .reactions import AuthorReactionsIndex
from .replies import RepliesMixin
from .tags import TagIndex
from .webmentions import WebmentionsMixin
from ._sorters import PagesSorter, PagesSortByTime


class BlogApp(  # pylint: disable=too-many-ancestors
    RepliesMixin,
    ActivityPubMixin,
    FeedsMixin,
    GuestbookMixin,
    MarkdownMixin,
    WebmentionsMixin,
    Flask,
):
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

        self.replies_dir = Path(config.content_dir).expanduser().resolve() / "replies"

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

        self._register_template_filters()
        self._register_ap_context_processors()
        self._register_replies_context_processors()
        self._init_webmentions()
        self._init_activitypub()
        self.tag_index = TagIndex(
            content_dir=config.content_dir,
            pages_dir=str(self.pages_dir),
            mentions_dir=str(self.mentions_dir),
        )
        self.author_reactions_index = AuthorReactionsIndex(
            state_dir=config.resolved_state_dir,
            replies_dir=self.replies_dir,
            base_url=config.link,
        )
        self.replies_monitor: Optional[ContentMonitor] = None

    @property
    def _app(self) -> Flask:
        return self

    def _register_template_filters(self):
        """Register custom Jinja2 template filters."""

        @self.template_filter("hash_id")
        def hash_id_filter(value: str) -> str:
            """Generate a short hash ID from a string for use in anchor IDs."""
            return hashlib.md5(str(value).encode()).hexdigest()[:12]

        @self.template_filter("fromjson")
        def fromjson_filter(value: object) -> object:
            """Parse a JSON string into a Python object."""
            if value is None:
                return None
            if isinstance(value, (dict, list)):
                return value
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return None
            return None

        @self.template_filter("safe_url")
        def safe_url_filter(url: object) -> str | None:
            """Validate and return a safe URL (http/https only)."""
            if not url or not isinstance(url, str):
                return None
            url = url.strip()
            if not url:
                return None
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return None
            if not parsed.netloc:
                return None
            return url

    def _register_replies_context_processors(self):
        """Register context processors for replies-related template variables."""

        @self.context_processor
        def inject_unlisted_count():
            try:
                return {"unlisted_count": len(self.get_unlisted_posts())}
            except Exception:
                return {"unlisted_count": 0}

    def _on_content_change_tags(self, _: ChangeType, filepath: str) -> None:
        """Bridge: forward content changes to the tag indexer."""
        self.tag_index.reindex_file(filepath)

    def start(self) -> None:
        from . import __version__

        self.logger.info(
            """
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
⚡ version: %s
              """,
            __version__,
        )

        self.tag_index.build()
        self.content_monitor.register(self._on_content_change_tags)
        self.content_monitor.start()

        # Sync outgoing webmentions for new/modified content
        if config.enable_webmentions:
            self.webmentions_storage.sync_on_startup()

        # Load the author-reactions index (likes targeting local pages)
        self.author_reactions_index.load()

        # Start replies monitor for federation
        self._start_replies_monitor()

    def stop(self) -> None:
        self.content_monitor.stop()
        if self.replies_monitor:
            self.replies_monitor.stop()
            self.replies_monitor = None

    def _start_replies_monitor(self) -> None:
        """
        Create and start a ContentMonitor for the replies directory.

        Registers callbacks for ActivityPub and Webmentions federation.
        The directory is created if it doesn't exist so that replies
        created after startup are immediately picked up.
        """
        self.replies_dir.mkdir(parents=True, exist_ok=True)

        self.replies_monitor = ContentMonitor(
            root_dir=str(self.replies_dir),
            throttle_seconds=config.throttle_seconds_on_update,
        )

        # Register ActivityPub callback for reply federation
        if config.enable_activitypub and hasattr(self, "_ap_integration"):
            self.replies_monitor.register(self._ap_integration.on_reply_change)

        # Register Webmentions callback for outgoing mentions from replies
        if config.enable_webmentions:
            self.replies_monitor.register(self.webmentions_storage.on_reply_change)

        # Register author-reactions index callback
        self.replies_monitor.register(self.author_reactions_index.on_reply_change)

        self.replies_monitor.start()

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

    def _build_cached_page_for_article(
        self, md_file: str, metadata: dict
    ) -> CachedPage:
        """
        Build a CachedPage for an article, including interaction directories.
        """
        article_slug = self._article_slug_from_metadata(metadata)
        ap_interactions_dir = None
        if hasattr(self, "activitypub_storage"):
            ap_interactions_dir = str(
                config.resolved_state_dir / "activitypub" / "state" / "interactions"
            )

        return CachedPage(
            md_file,
            metadata=metadata,
            article_slug=article_slug,
            mentions_dir=(
                str(self.mentions_dir) if hasattr(self, "mentions_dir") else None
            ),
            ap_interactions_dir=ap_interactions_dir,
            replies_dir=str(self.replies_dir),
        )

    def _render_markdown_output(self, md_file: str, title: str) -> str:
        """Render raw markdown output with title."""
        with open(md_file, "r") as f:
            content = self._parse_markdown_content(f)
        return f"# {title}\n\n{content}"

    def _make_content_response(
        self,
        *,
        md_file: str,
        metadata: dict,
        cached_page: CachedPage,
        title: str,
        as_markdown: bool,
        render_html_fn,
        get_ap_response_fn,
    ) -> Response:
        """
        Shared flow for rendering page/reply content responses.

        Handles cache validation, ActivityPub negotiation, and rendering.
        """
        if cached_page.is_client_cache_valid():
            return cached_page.make_304_response()

        if self._client_prefers_activitypub():
            ap_response = get_ap_response_fn(
                last_modified=cached_page.last_modified,
                etag=cached_page.etag,
            )
            if ap_response:
                return ap_response

        response = make_response(
            self._render_markdown_output(md_file, title)
            if as_markdown
            else render_html_fn()
        )

        self._set_page_response_headers(
            response,
            last_modified=cached_page.last_modified,
            etag=cached_page.etag,
            metadata=metadata,
            as_markdown=as_markdown,
        )
        return response

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
        cached_page = self._build_cached_page_for_article(md_file, metadata)
        title = title or metadata.get("title") or config.title

        def render_html():
            reactions_tree = self._get_page_interactions(md_file, metadata)
            return self._render_page_html(
                md_file=md_file,
                metadata=metadata,
                title=title,
                skip_header=skip_header,
                skip_html_head=skip_html_head,
                reactions_tree=reactions_tree,
            )

        def get_ap_response(*, last_modified, etag):
            return self._get_activitypub_page_response(
                md_file=md_file,
                metadata=metadata,
                last_modified=last_modified,
                etag=etag,
            )

        return self._make_content_response(
            md_file=md_file,
            metadata=metadata,
            cached_page=cached_page,
            title=title,
            as_markdown=as_markdown,
            render_html_fn=render_html,
            get_ap_response_fn=get_ap_response,
        )

    def get_reply(
        self,
        article_slug: str | None,
        reply_slug: str,
        *,
        as_markdown: bool = False,
    ) -> Response:
        """
        Get the HTML (or raw Markdown) for an author reply.

        :param article_slug: The slug of the parent article (or ``_guestbook``),
            or ``None`` for top-level unlisted posts.
        :param reply_slug: The slug of the reply itself.
        :param as_markdown: Return raw Markdown instead of rendered HTML.
        """
        metadata = self._parse_reply_metadata(article_slug, reply_slug)
        md_file = metadata.pop("md_file")
        cached_page = CachedPage(md_file, metadata=metadata)
        title = metadata.get("title") or reply_slug

        def render_html():
            reactions_tree = self._get_reply_interactions(
                md_file, metadata, article_slug, reply_slug
            )
            return self._render_reply_html(
                md_file=md_file,
                metadata=metadata,
                title=title,
                article_slug=article_slug,
                reactions_tree=reactions_tree,
            )

        def get_ap_response(*, last_modified, etag):
            return self._get_activitypub_reply_response(
                md_file=md_file,
                metadata=metadata,
                last_modified=last_modified,
                etag=etag,
                article_slug=article_slug,
                reply_slug=reply_slug,
            )

        return self._make_content_response(
            md_file=md_file,
            metadata=metadata,
            cached_page=cached_page,
            title=title,
            as_markdown=as_markdown,
            render_html_fn=render_html,
            get_ap_response_fn=get_ap_response,
        )

    def _get_page_content(self, page: str, **kwargs) -> str:
        """Return the HTML content of a page as a string (not a Response)."""
        result = self.get_page(page, **kwargs)
        if isinstance(result, Response):
            return result.get_data(as_text=True)
        return str(result) if result else ""

    def _is_hidden_folder(self, name: str) -> bool:
        """Check if a folder name indicates it should be hidden."""
        return name.startswith(".") or name.startswith("_")

    def _get_folders_in_dir(self, folder: str = "") -> List[dict]:
        """
        Return visible subfolders in the given folder path.

        - Excludes hidden folders (starting with . or _)
        - Excludes empty folders (no articles, no visible subfolders)
        - Parses index.md for folder metadata if present
        """
        target_dir = self.pages_dir / folder if folder else self.pages_dir
        target_dir_resolved = Path(os.path.realpath(str(target_dir)))

        if not target_dir_resolved.is_dir():
            return []

        if not str(target_dir_resolved).startswith(str(self.pages_dir)):
            return []

        folders = []
        replies_dir = str(self.replies_dir)

        for entry in sorted(target_dir_resolved.iterdir()):
            if not entry.is_dir():
                continue

            name = entry.name
            if self._is_hidden_folder(name):
                continue

            if str(entry) == replies_dir:
                continue

            rel_path = os.path.join(folder, name) if folder else name
            if self._is_folder_empty(rel_path):
                continue

            folder_meta = self._parse_folder_metadata(rel_path)
            folders.append(
                {
                    "name": name,
                    "path": rel_path,
                    "uri": f"/~{rel_path}/",
                    "title": folder_meta.get("title") or name,
                    "description": folder_meta.get("description"),
                    "image": folder_meta.get("image"),
                    "has_custom_index": folder_meta.get("has_content", False),
                }
            )

        return folders

    def _is_folder_empty(self, folder: str) -> bool:
        """
        Check if a folder has no visible articles and no visible subfolders.
        """
        target_dir = self.pages_dir / folder
        if not target_dir.is_dir():
            return True

        replies_dir = str(self.replies_dir)

        for entry in target_dir.iterdir():
            if entry.is_file() and entry.suffix == ".md" and entry.name != "index.md":
                return False

            if entry.is_dir():
                if self._is_hidden_folder(entry.name):
                    continue
                if str(entry) == replies_dir:
                    continue
                if not self._is_folder_empty(os.path.join(folder, entry.name)):
                    return False

        return True

    def _build_page_entry(
        self,
        *,
        rel_path: str,
        rel_folder: str,
        full_path: str,
        with_content: bool,
        skip_header: bool,
        skip_html_head: bool,
    ) -> dict:
        """Build a page entry dict for a single Markdown file."""
        return {
            "path": rel_path,
            "folder": rel_folder,
            "content": (
                self._get_page_content(
                    full_path,
                    skip_header=skip_header,
                    skip_html_head=skip_html_head,
                )
                if with_content
                else ""
            ),
            **self._parse_page_metadata(rel_path),
        }

    def _get_pages_recursive(
        self,
        start_dir: str,
        pages_dir_str: str,
        *,
        with_content: bool,
        skip_header: bool,
        skip_html_head: bool,
    ) -> list:
        """Get pages recursively using os.walk."""
        replies_dir = str(self.replies_dir)
        pages = []

        for root, dirs, files in os.walk(start_dir, followlinks=True):
            dirs[:] = [d for d in dirs if os.path.join(root, d) != replies_dir]

            for f in files:
                if not f.endswith(".md"):
                    continue

                rel_path = os.path.join(root[len(pages_dir_str) + 1 :], f)
                rel_folder = root[len(pages_dir_str) + 1 :]

                pages.append(
                    self._build_page_entry(
                        rel_path=rel_path,
                        rel_folder=rel_folder,
                        full_path=os.path.join(root, f),
                        with_content=with_content,
                        skip_header=skip_header,
                        skip_html_head=skip_html_head,
                    )
                )

        return pages

    def _get_pages_non_recursive(
        self,
        start_dir: str,
        folder: str,
        *,
        with_content: bool,
        skip_header: bool,
        skip_html_head: bool,
    ) -> list:
        """Get pages from direct children only (non-recursive)."""
        try:
            entries = os.listdir(start_dir)
        except OSError:
            return []

        pages = []
        for f in entries:
            full_path = os.path.join(start_dir, f)
            if not os.path.isfile(full_path):
                continue
            if not f.endswith(".md"):
                continue
            if f == "index.md":
                continue

            rel_path = os.path.join(folder, f) if folder else f
            pages.append(
                self._build_page_entry(
                    rel_path=rel_path,
                    rel_folder=folder,
                    full_path=full_path,
                    with_content=with_content,
                    skip_header=skip_header,
                    skip_html_head=skip_html_head,
                )
            )

        return pages

    def _get_pages_from_files(
        self,
        *,
        folder: str = "",
        recursive: bool = True,
        with_content: bool = False,
        skip_header: bool = False,
        skip_html_head: bool = False,
    ):
        """
        Get pages from Markdown files.

        :param folder: Restrict to this folder (relative to pages_dir)
        :param recursive: If False, only list direct children of folder
        :param with_content: Include rendered HTML content
        :param skip_header: Skip header in rendered content
        :param skip_html_head: Skip HTML head in rendered content
        """
        pages_dir_str = str(self.pages_dir).rstrip("/")

        if folder:
            start_dir = os.path.join(pages_dir_str, folder)
            start_dir_resolved = os.path.realpath(start_dir)
            if not start_dir_resolved.startswith(pages_dir_str):
                return []
            if not os.path.isdir(start_dir_resolved):
                return []
        else:
            start_dir = pages_dir_str

        if recursive:
            return self._get_pages_recursive(
                start_dir,
                pages_dir_str,
                with_content=with_content,
                skip_header=skip_header,
                skip_html_head=skip_html_head,
            )

        return self._get_pages_non_recursive(
            start_dir,
            folder,
            with_content=with_content,
            skip_header=skip_header,
            skip_html_head=skip_html_head,
        )

    def get_pages(
        self,
        *,
        folder: str = "",
        recursive: bool = True,
        with_content: bool = False,
        skip_header: bool = False,
        skip_html_head: bool = False,
        sorter: Type[PagesSorter] = PagesSortByTime,
        reverse: bool = True,
        include_external_feeds: bool = True,
    ) -> List[Tuple[int, dict]]:
        local_pages = self._get_pages_from_files(
            folder=folder,
            recursive=recursive,
            with_content=with_content,
            skip_header=skip_header,
            skip_html_head=skip_html_head,
        )

        remote_pages = []
        if (
            include_external_feeds
            and not folder
            and not config.external_feeds_as_folders
        ):
            remote_pages = self._get_pages_from_feeds(with_content=with_content)

        pages = local_pages + remote_pages
        pages.sort(key=sorter(pages), reverse=reverse)
        return list(enumerate(pages))

    def _build_folder_context(self, folder: str, recursive: bool) -> dict:
        """
        Build template context for folder navigation.

        Returns dict with folders, breadcrumbs, parent_folder, and folder metadata.
        """
        if recursive:
            return {
                "folders": [],
                "external_feeds": [],
                "breadcrumbs": [],
                "parent_folder": None,
                "current_folder": folder,
                "folder_title": None,
                "folder_description": None,
            }

        folder_metadata = self._parse_folder_metadata(folder) if folder else {}
        folders = self._get_folders_in_dir(folder)

        # Get external feeds as separate section at root level
        external_feeds = []
        if not folder and config.external_feeds_as_folders:
            external_feeds = self._get_external_feed_folders()

        return {
            "folders": folders,
            "external_feeds": external_feeds,
            "breadcrumbs": self._build_breadcrumbs(folder) if folder else [],
            "parent_folder": self._get_parent_folder(folder) if folder else None,
            "current_folder": folder,
            "folder_title": folder_metadata.get("title"),
            "folder_description": folder_metadata.get("description"),
        }

    def get_pages_response(
        self,
        *,
        folder: str = "",
        recursive: bool = True,
        with_content: bool = False,
        skip_header: bool = False,
        skip_html_head: bool = False,
        sorter: Type[PagesSorter] = PagesSortByTime,
        reverse: bool = True,
        template_name: str = "index.html",
        view_mode: str = "cards",
        meta_redirect_to: str | None = None,
        include_external_feeds: bool = True,
        override_pages: list | None = None,
        **extra_context,
    ) -> Response:
        """
        Get a Response for the pages list with proper cache headers.

        :param folder: Restrict to this folder (relative to pages_dir)
        :param recursive: If False, only list direct children of folder
        :param with_content: Include full content for each page
        :param skip_header: Skip header in rendered content
        :param skip_html_head: Skip HTML head in rendered content
        :param sorter: Sorter class to use for page ordering
        :param reverse: Reverse sort order
        :param template_name: Template name to render
        :param view_mode: View mode for the template
        :param meta_redirect_to: If set, inject a meta refresh tag to redirect
            to this URL. This is used for profile URLs (/@username, /ap/actor)
            where the page content must be served (for rel="me" verification)
            but human users should be redirected to the canonical home page.
        :param include_external_feeds: Include external feeds in page list
        :param override_pages: If set, use these pages instead of fetching
        """
        if override_pages is not None:
            pages = override_pages
        else:
            pages = self.get_pages(
                folder=folder,
                recursive=recursive,
                with_content=with_content,
                skip_header=skip_header,
                skip_html_head=skip_html_head,
                sorter=sorter,
                reverse=reverse,
                include_external_feeds=include_external_feeds and (not folder),
            )

        most_recent_mtime = compute_pages_mtime(pages, self.pages_dir)
        last_modified = (
            formatdate(most_recent_mtime, usegmt=True)
            if most_recent_mtime > 0
            else None
        )
        etag = generate_etag(most_recent_mtime) if most_recent_mtime > 0 else None

        if (
            most_recent_mtime > 0
            and etag
            and check_cache_validity(most_recent_mtime, etag)
        ):
            return make_304_response(last_modified, etag)

        folder_ctx = self._build_folder_context(folder, recursive)
        # Merge contexts, with extra_context taking precedence
        template_ctx = {**folder_ctx, **extra_context}

        with contextlib.ExitStack() as stack:
            if not has_app_context():
                stack.enter_context(self.app_context())

            html = render_template(
                template_name,
                pages=pages,
                config=config,
                view_mode=view_mode,
                **template_ctx,
            )

        if meta_redirect_to:
            meta_refresh = (
                f'<meta http-equiv="refresh" content="0; url={meta_redirect_to}" />'
            )
            html = html.replace("</head>", f"{meta_refresh}</head>", 1)

        response = make_response(html)
        set_cache_headers(response, last_modified, etag)
        return response

    def _build_breadcrumbs(self, folder: str) -> List[dict]:
        """
        Build breadcrumb navigation for a folder path.

        Returns list of dicts with 'name', 'uri', and 'title' keys.
        """
        if not folder:
            return []

        parts = folder.split(os.sep)
        breadcrumbs = [{"name": "Home", "uri": "/", "title": config.title or "Home"}]

        accumulated = ""
        for part in parts:
            accumulated = os.path.join(accumulated, part) if accumulated else part
            folder_meta = self._parse_folder_metadata(accumulated)
            breadcrumbs.append(
                {
                    "name": part,
                    "uri": f"/~{accumulated}/",
                    "title": folder_meta.get("title") or part,
                }
            )

        return breadcrumbs

    def _get_parent_folder(self, folder: str) -> Optional[dict]:
        """
        Get parent folder info for navigation.

        Returns dict with 'name' and 'uri', or None if at root.
        """
        if not folder:
            return None

        parent = os.path.dirname(folder)
        if not parent:
            return {"name": "Home", "uri": "/", "title": config.title or "Home"}

        parent_meta = self._parse_folder_metadata(parent)
        return {
            "name": os.path.basename(parent),
            "uri": f"/~{parent}/",
            "title": parent_meta.get("title") or os.path.basename(parent),
        }

    def get_folder_index(
        self,
        folder: str,
        *,
        view_mode: str = "cards",
        followers_count: int = 0,
    ) -> Response:
        """
        Render folder index page or custom index.md content.

        If the folder has an index.md with content, it is rendered as a page.
        Otherwise, a listing of subfolders and articles is rendered.
        """
        from flask import abort

        folder = folder.strip("/")

        folder_dir = self.pages_dir / folder
        folder_dir_resolved = Path(os.path.realpath(str(folder_dir)))

        if not folder_dir_resolved.is_dir():
            abort(404)

        if not str(folder_dir_resolved).startswith(str(self.pages_dir)):
            abort(404)

        folder_meta = self._parse_folder_metadata(folder)

        if folder_meta.get("has_content"):
            return self.get_page(
                f"{folder}/index",
                skip_header=False,
                skip_html_head=False,
            )

        return self.get_pages_response(
            folder=folder,
            recursive=False,
            with_content=(view_mode == "full"),
            skip_header=True,
            skip_html_head=True,
            template_name="index.html",
            view_mode=view_mode,
            followers_count=followers_count,
        )

    def get_external_feed_index(
        self,
        feed_url: str,
        *,
        view_mode: str = "cards",
        followers_count: int = 0,
    ) -> Response:
        """
        Render an external feed as an index page.

        Shows all entries from the specified external feed URL.
        """
        from flask import abort

        feed_meta = self._get_feed_metadata(feed_url)
        if not feed_meta:
            abort(404)

        # Use canonical feed URL from metadata
        canonical_url = feed_meta.get("feed_url", feed_url)

        pages = self._get_pages_from_single_feed(
            feed_url, with_content=(view_mode == "full")
        )
        pages.sort(key=lambda p: p.get("published") or "", reverse=True)
        pages = list(enumerate(pages))

        return self.get_pages_response(
            folder="",
            recursive=True,
            include_external_feeds=False,
            with_content=(view_mode == "full"),
            skip_header=True,
            skip_html_head=True,
            template_name="index.html",
            view_mode=view_mode,
            followers_count=followers_count,
            # Override pages with feed-specific pages
            override_pages=pages,
            # Pass feed metadata for the template
            feed_title=feed_meta.get("title"),
            feed_description=feed_meta.get("description"),
            feed_url=canonical_url,
            feed_image=feed_meta.get("image"),
            breadcrumbs=[
                {"name": "Home", "uri": "/", "title": config.title or "Home"},
                {
                    "name": feed_meta.get("title"),
                    "uri": f"/+{quote(canonical_url, safe='')}/",
                },
            ],
            parent_folder={"name": "Home", "uri": "/", "title": config.title or "Home"},
        )


app = BlogApp(__name__)

from .routes import *

# vim:sw=4:ts=4:et:
