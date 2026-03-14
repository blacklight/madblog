import datetime
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

from .activitypub import ActivityPubMixin
from .cache import CachedPage, check_cache_validity, generate_etag, get_max_mtime
from .config import config
from .feeds import FeedsMixin
from .guestbook import GuestbookMixin
from .markdown import MarkdownMixin, resolve_relative_urls
from .monitor import ChangeType, ContentMonitor
from .tags import TagIndex
from .templates import TemplateUtils
from .threading import build_thread_tree, count_reactions
from .webmentions import WebmentionsMixin
from ._sorters import PagesSorter, PagesSortByTime


class BlogApp(  # pylint: disable=too-many-ancestors
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
        self._init_webmentions()
        self._init_activitypub()
        self.tag_index = TagIndex(
            content_dir=config.content_dir,
            pages_dir=str(self.pages_dir),
            mentions_dir=str(self.mentions_dir),
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

        self.replies_monitor.start()

    def _get_page_interactions(
        self,
        md_file: str,
        metadata: dict,
    ) -> list:
        """
        Retrieve reactions (Webmentions, AP interactions, author replies)
        for a page and build a threaded tree.

        :return: List of ThreadNode objects (the thread tree roots)
        """
        webmentions = self._get_webmentions(metadata)
        article_slug = self._article_slug_from_metadata(metadata)
        author_replies = self._get_article_replies(article_slug)
        article_url = config.link + metadata.get("uri", "")

        # Also fetch AP interactions targeting author reply URLs so that
        # fediverse replies to author replies appear in the thread.
        # When activitypub_link differs from link the AP target URL and the
        # public full_url use different origins; annotate each reply with
        # the AP variant so the thread tree can register both as aliases.
        reply_ap_urls = set()
        ap_integration = getattr(self, "_ap_integration", None)
        if ap_integration:
            for reply in author_replies:
                permalink = reply.get("permalink", "")
                if permalink:
                    ap_url = ap_integration.base_url + permalink
                    reply_ap_urls.add(ap_url)
                    if ap_url != reply.get("full_url"):
                        reply["ap_full_url"] = ap_url
                    # Also add the content URL variant
                    content_url = reply.get("full_url", "")
                    if content_url:
                        reply_ap_urls.add(content_url)

        ap_interactions = self._get_ap_interactions(
            md_file, extra_target_urls=list(reply_ap_urls)
        )

        # Filter out non-reply interactions targeting author reply URLs.
        # Likes/boosts on replies should only appear on the reply page.
        ap_object_url = None
        if ap_integration:
            ap_object_url = ap_integration.file_to_url(md_file)

        ap_interactions = [
            i
            for i in ap_interactions
            if self._is_article_interaction(
                i,
                article_url=article_url,
                ap_object_url=ap_object_url,
                reply_ap_urls=reply_ap_urls,
            )
        ]

        return build_thread_tree(
            webmentions=webmentions,
            ap_interactions=ap_interactions,
            author_replies=author_replies,
            article_url=article_url,
        )

    @staticmethod
    def _is_article_interaction(
        interaction,
        article_url: str,
        ap_object_url: str | None,
        reply_ap_urls: set[str],
    ) -> bool:
        target = getattr(interaction, "target_resource", None)
        if not target:
            return True

        # Interactions targeting the article itself are always included
        if target in (ap_object_url, article_url):
            return True

        # For interactions targeting reply URLs, only include replies/quotes
        if target in reply_ap_urls:
            itype = getattr(interaction, "interaction_type", None)
            type_val = None
            if itype:
                type_val = (
                    itype.value
                    if hasattr(itype, "value")
                    else str(itype) if itype else ""
                )

            return type_val in ("reply", "quote")

        return True

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

        # Compute article slug for interaction mtime checks
        article_slug = self._article_slug_from_metadata(metadata)

        # Get AP interactions directory if available
        ap_interactions_dir = None
        if hasattr(self, "activitypub_storage"):
            ap_interactions_dir = str(
                config.resolved_state_dir / "activitypub" / "state" / "interactions"
            )

        # Return 304 if client cache is valid (considering both article and interactions)
        cached_page = CachedPage(
            md_file,
            metadata=metadata,
            article_slug=article_slug,
            mentions_dir=(
                str(self.mentions_dir) if hasattr(self, "mentions_dir") else None
            ),
            ap_interactions_dir=ap_interactions_dir,
            replies_dir=str(self.replies_dir),
        )

        if cached_page.is_client_cache_valid():
            return cached_page.make_304_response()

        # Return ActivityPub response if client prefers it
        if self._client_prefers_activitypub():
            ap_response = self._get_activitypub_page_response(
                md_file=md_file,
                metadata=metadata,
                last_modified=cached_page.last_modified,
                etag=cached_page.etag,
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
            reactions_tree = self._get_page_interactions(md_file, metadata)
            output = self._render_page_html(
                md_file=md_file,
                metadata=metadata,
                title=title,
                skip_header=skip_header,
                skip_html_head=skip_html_head,
                reactions_tree=reactions_tree,
            )

        response = make_response(output)
        self._set_page_response_headers(
            response,
            last_modified=cached_page.last_modified,
            etag=cached_page.etag,
            metadata=metadata,
            as_markdown=as_markdown,
        )

        return response

    def get_reply(
        self,
        article_slug: str,
        reply_slug: str,
        *,
        as_markdown: bool = False,
    ) -> Response:
        """
        Get the HTML (or raw Markdown) for an author reply.

        :param article_slug: The slug of the parent article (or ``_guestbook``).
        :param reply_slug: The slug of the reply itself.
        :param as_markdown: Return raw Markdown instead of rendered HTML.
        """
        metadata = self._parse_reply_metadata(article_slug, reply_slug)
        md_file = metadata.pop("md_file")

        # Return 304 if client cache is valid
        cached_page = CachedPage(md_file, metadata=metadata)
        if cached_page.is_client_cache_valid():
            return cached_page.make_304_response()

        # Return ActivityPub response if client prefers it
        if self._client_prefers_activitypub():
            ap_response = self._get_activitypub_reply_response(
                md_file=md_file,
                metadata=metadata,
                last_modified=cached_page.last_modified,
                etag=cached_page.etag,
                article_slug=article_slug,
                reply_slug=reply_slug,
            )
            if ap_response:
                return ap_response

        title = metadata.get("title") or reply_slug
        if as_markdown:
            with open(md_file, "r") as f:
                content = self._parse_markdown_content(f)
            output = f"# {title}\n\n{content}"
        else:
            reactions_tree = self._get_reply_interactions(
                md_file, metadata, article_slug, reply_slug
            )
            output = self._render_reply_html(
                md_file=md_file,
                metadata=metadata,
                title=title,
                article_slug=article_slug,
                reactions_tree=reactions_tree,
            )

        response = make_response(output)
        self._set_page_response_headers(
            response,
            last_modified=cached_page.last_modified,
            etag=cached_page.etag,
            metadata=metadata,
            as_markdown=as_markdown,
        )

        return response

    @staticmethod
    def _article_slug_from_metadata(metadata: dict) -> str:
        """
        Derive the article slug from the metadata URI.

        E.g. ``/article/2025/my-post`` → ``2025/my-post``
        """
        uri = metadata.get("uri", "")
        if uri.startswith("/article/"):
            return uri[len("/article/") :]
        return uri.lstrip("/")

    def _get_article_replies(self, article_slug: str) -> list:
        """
        Scan replies/<article_slug>/ and return a list of parsed reply dicts.

        Each dict contains: slug, title, reply_to, published, content_html,
        permalink, author, author_url, author_photo.
        """
        from .markdown import render_html

        replies_subdir = self.replies_dir / article_slug
        if not replies_subdir.is_dir():
            return []

        replies = []
        for md_path in replies_subdir.glob("*.md"):
            reply_slug = md_path.stem
            try:
                metadata = self._parse_reply_metadata(article_slug, reply_slug)
            except Exception:
                continue

            md_file = metadata.pop("md_file")
            with open(md_file, "r") as f:
                content = self._parse_markdown_content(f)

            author_info = self._parse_author(metadata)
            permalink = f"/reply/{article_slug}/{reply_slug}"

            replies.append(
                {
                    "slug": reply_slug,
                    "title": metadata.get("title", reply_slug),
                    "reply_to": metadata.get("reply-to", ""),
                    "published": metadata.get("published"),
                    "content_html": render_html(
                        resolve_relative_urls(content, config.link, permalink, "/reply")
                    ),
                    "permalink": permalink,
                    "full_url": config.link + permalink,
                    **author_info,
                }
            )

        # Sort by published date ascending (oldest first)
        replies.sort(key=lambda r: r.get("published") or datetime.date.min)
        return replies

    def _get_reply_interactions(
        self, md_file: str, metadata: dict, article_slug: str, reply_slug: str
    ) -> list:
        """
        Retrieve reactions (Webmentions, AP interactions, nested author replies)
        for a reply page and build a threaded tree.

        Only includes reactions that are actual descendants of the current reply,
        not sibling threads.

        :return: List of ThreadNode objects (the thread tree roots)
        """
        reply_url = config.link + metadata.get("uri", "")
        reply_uri = metadata.get("uri", "")

        # Build set of valid parent URLs (the current reply and its AP variant)
        valid_parent_urls = {reply_url}
        ap_integration = getattr(self, "_ap_integration", None)
        if ap_integration:
            ap_url = ap_integration.base_url + reply_uri
            valid_parent_urls.add(ap_url)

        # Get all author replies for the article, excluding the current reply
        all_author_replies = self._get_article_replies(article_slug)
        candidate_replies = {
            r.get("slug"): r for r in all_author_replies if r.get("slug") != reply_slug
        }

        # Iteratively find author replies that are descendants of the current reply.
        # An author reply is a descendant if its reply-to matches a known valid URL.
        descendant_replies = []
        changed = True
        while changed:
            changed = False
            for slug, reply in list(candidate_replies.items()):
                reply_to = reply.get("reply_to", "")
                if reply_to in valid_parent_urls:
                    descendant_replies.append(reply)
                    # Add this reply's URLs to valid_parent_urls
                    if reply.get("full_url"):
                        valid_parent_urls.add(reply["full_url"])
                    if ap_integration:
                        permalink = reply.get("permalink", "")
                        if permalink:
                            nested_ap_url = ap_integration.base_url + permalink
                            valid_parent_urls.add(nested_ap_url)
                            if nested_ap_url != reply.get("full_url"):
                                reply["ap_full_url"] = nested_ap_url
                    del candidate_replies[slug]
                    changed = True

        # Collect AP URLs for descendant replies to fetch their interactions
        extra_target_urls = set()
        if ap_integration:
            # Add AP URL variant for the current reply
            ap_url = ap_integration.base_url + reply_uri
            if ap_url != reply_url:
                extra_target_urls.add(ap_url)

            # Add AP URLs for descendant author replies
            for reply in descendant_replies:
                permalink = reply.get("permalink", "")
                if permalink:
                    nested_ap_url = ap_integration.base_url + permalink
                    extra_target_urls.add(nested_ap_url)
                    content_url = reply.get("full_url", "")
                    if content_url:
                        extra_target_urls.add(content_url)

        # Fetch webmentions and AP interactions
        webmentions = self._get_webmentions(metadata)
        ap_interactions = self._get_ap_interactions(
            md_file, extra_target_urls=list(extra_target_urls)
        )

        # Also add interaction URLs to valid_parent_urls for proper threading
        for interaction in ap_interactions:
            obj_id = getattr(interaction, "object_id", None)
            if obj_id:
                valid_parent_urls.add(obj_id)
            act_id = getattr(interaction, "activity_id", None)
            if act_id:
                valid_parent_urls.add(act_id)

        # Second pass: check if any remaining candidates are descendants via
        # interactions (e.g., author reply to a fediverse reply)
        changed = True
        while changed:
            changed = False
            for slug, reply in list(candidate_replies.items()):
                reply_to = reply.get("reply_to", "")
                if reply_to in valid_parent_urls:
                    descendant_replies.append(reply)
                    if reply.get("full_url"):
                        valid_parent_urls.add(reply["full_url"])
                    if ap_integration:
                        permalink = reply.get("permalink", "")
                        if permalink:
                            nested_ap_url = ap_integration.base_url + permalink
                            valid_parent_urls.add(nested_ap_url)
                            extra_target_urls.add(nested_ap_url)
                            if nested_ap_url != reply.get("full_url"):
                                reply["ap_full_url"] = nested_ap_url
                            content_url = reply.get("full_url", "")
                            if content_url:
                                extra_target_urls.add(content_url)
                    del candidate_replies[slug]
                    changed = True

        # Re-fetch interactions if we found more descendant replies
        if descendant_replies:
            ap_interactions = self._get_ap_interactions(
                md_file, extra_target_urls=list(extra_target_urls)
            )

        return build_thread_tree(
            webmentions=webmentions,
            ap_interactions=ap_interactions,
            author_replies=descendant_replies,
            article_url=reply_url,
        )

    def _render_reply_html(
        self,
        *,
        md_file: str,
        metadata: dict,
        title: str,
        article_slug: str,
        reactions_tree: list,
    ) -> str:
        """
        Render a reply Markdown file to HTML using the reply template.
        """
        from .markdown import render_html

        with open(md_file, "r") as f:
            content = self._parse_markdown_content(f)

        author_info = self._parse_author(metadata)
        reply_to = metadata.get("reply-to", "")
        reactions_counts = count_reactions(reactions_tree)

        with contextlib.ExitStack() as stack:
            if not has_app_context():
                stack.enter_context(self._app.app_context())

            return render_template(
                "reply.html",
                config=config,
                title=title,
                uri=metadata.get("uri"),
                url=config.link + metadata.get("uri", ""),
                image=metadata.get("image"),
                description=metadata.get("description"),
                published_datetime=metadata.get("published"),
                published=metadata["published"].strftime("%b %d, %Y"),
                content=render_html(
                    resolve_relative_urls(
                        content, config.link, metadata.get("uri", ""), "/reply"
                    )
                ),
                reply_to=reply_to,
                article_slug=article_slug,
                reactions_tree=reactions_tree,
                reactions_counts=reactions_counts,
                utils=TemplateUtils(),
                **author_info,
            )

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
        replies_dir = str(self.replies_dir)
        pages = []

        for root, dirs, files in os.walk(pages_dir, followlinks=True):
            # Exclude the replies directory from the home page listing
            dirs[:] = [d for d in dirs if os.path.join(root, d) != replies_dir]

            for f in files:
                if not f.endswith(".md"):
                    continue

                pages.append(
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
                )

        return pages

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
        # Get the pages data first (this includes file_mtime for each local page)
        pages = self.get_pages(
            with_content=with_content,
            skip_header=skip_header,
            skip_html_head=skip_html_head,
            sorter=sorter,
            reverse=reverse,
        )

        # Compute the most recent modification time from pages data and
        # the pages directory itself (to detect added/removed articles)
        most_recent_mtime = get_max_mtime(self.pages_dir)

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
        etag = generate_etag(most_recent_mtime) if most_recent_mtime > 0 else None

        # Check if the client has a cached version that's still valid
        if (
            most_recent_mtime > 0
            and etag
            and check_cache_validity(most_recent_mtime, etag)
        ):
            response = make_response("", 304)
            if last_modified:
                response.headers["Last-Modified"] = last_modified
            response.headers["ETag"] = etag
            response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

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
