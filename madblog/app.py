import datetime
import email.utils
import hashlib
import json
import os
import re
import stat
import contextlib
import threading

from pathlib import Path
from typing import IO, List, Optional, Tuple, Type
from urllib.parse import urlparse
from email.utils import formatdate

from flask import (
    Flask,
    Response,
    abort,
    has_app_context,
    has_request_context,
    make_response,
    render_template,
    request,
)
from markdown import markdown
from webmentions import WebmentionDirection, WebmentionsHandler
from webmentions.server.adapters.flask import bind_webmentions

from .activitypub import MarkdownActivityPubMentions
from .autolink import MarkdownAutolink
from .config import config
from .feeds import FeedAuthor, FeedParser
from .latex import MarkdownLatex
from .mermaid import MarkdownMermaid
from .monitor import ChangeType, ContentMonitor
from .notifications import (
    SmtpConfig,
    build_activitypub_email_notifier,
    build_webmention_email_notifier,
)
from .storage.mentions import FileWebmentionsStorage
from .storage.tags import TagIndex
from .tasklist import MarkdownTaskList
from .toc import MarkdownTocMarkers
from .tags import MarkdownTags, parse_metadata_tags
from ._sorters import PagesSorter, PagesSortByTime


class BlogApp(Flask):
    """
    The main application class.
    """

    _title_header_regex = re.compile(r"^#\s*((\[(.*)])|(.*))")
    _author_regex = re.compile(r"^(.+?)\s+<([^>]+)>$")
    _url_regex = re.compile(r"^(https?:\/\/)?[\w\.\-]+\.[a-z]{2,6}\/?")
    _email_regex = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, template_folder=config.templates_dir, **kwargs)
        self.pages_dir = (
            Path(Path(config.content_dir) / "markdown").expanduser().resolve()
        )
        self.img_dir = config.default_img_dir
        self.css_dir = config.default_css_dir
        self.js_dir = config.default_js_dir
        self.fonts_dir = config.default_fonts_dir
        self._feed_parser = FeedParser(config.external_feeds)

        if not os.path.isdir(self.pages_dir):
            # If the `markdown` subfolder does not exist, then the whole
            # `config.content_dir` is treated as the root for Markdown files.
            self.pages_dir = config.content_dir

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

        self._init_webmentions()
        self._init_activitypub()
        self.tag_index = TagIndex(
            content_dir=config.content_dir,
            pages_dir=str(self.pages_dir),
            mentions_dir=str(self.mentions_dir),
        )
        self._register_context_processors()

    def _register_context_processors(self):
        @self.context_processor
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

    def _generate_or_check_key(self, key_path: str) -> str:
        from pubby.crypto import generate_rsa_keypair, export_private_key_pem

        key_path = os.path.abspath(os.path.expanduser(key_path))
        if not os.path.isfile(key_path):
            private_key, _ = generate_rsa_keypair()
            pem = export_private_key_pem(private_key)
            with open(key_path, "w") as f:
                f.write(pem)

            os.chmod(key_path, 0o600)
            self.logger.info("Generated ActivityPub private key at %s", key_path)

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
            from .storage.activitypub import ActivityPubIntegration
        except ImportError:
            self.logger.error(
                "ActivityPub is enabled but pubby is not installed. "
                "Install it with: pip install 'madblog[activitypub]'"
            )
            return

        from . import __version__

        ap_dir = os.path.join(config.content_dir, "activitypub")
        os.makedirs(ap_dir, exist_ok=True)

        # Key management
        key_path = os.path.expanduser(
            config.activitypub_private_key_path
            or os.path.join(ap_dir, "private_key.pem")
        )

        self._generate_or_check_key(key_path)
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
                    "name": "Blog",
                    "value": f'<a href="{config.link}" rel="me">{config.link.lstrip("https://").rstrip("/")}</a>',
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

        bind_activitypub(self, self.activitypub_handler)
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
                self.logger.warning(
                    "Failed to publish actor profile update", exc_info=True
                )

        threading.Thread(target=_ap_startup_tasks, daemon=True).start()

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

    @staticmethod
    def _parse_metadata_from_markdown(handle: IO, page: str) -> dict:
        metadata: dict = {"uri": "/article/" + page[:-3]}
        for line in handle:
            if not line.strip() or re.match(r"(^---\s*$)|(^#\s+.*)", line):
                continue

            m = re.match(r"^\[//\]: # \(([^:]+):\s*(.*)\)\s*$", line)
            if not m:
                continue

            if m.group(1) == "published":
                metadata[m.group(1)] = datetime.datetime.fromisoformat(
                    m.group(2)
                ).date()
            else:
                metadata[m.group(1)] = m.group(2)

        return metadata

    @staticmethod
    def _infer_title_and_url_from_markdown(handle: IO) -> Tuple[str, str]:
        for line in handle:
            if not line:
                continue

            if not (m := re.match(r"^#\s+(\[?([^]]+)\]?(\((.*)\))?)\s*$", line)):
                break

            return m.group(2), m.group(4)

        return "", ""

    def _parse_page_metadata(self, page: str) -> dict:
        """
        Parse the metadata from a Markdown page
        """
        if not page.endswith(".md"):
            page = page + ".md"

        md_file = os.path.realpath(os.path.join(self.pages_dir, page))
        if not os.path.isfile(md_file) or not md_file.startswith(str(self.pages_dir)):
            abort(404)

        if not os.access(md_file, os.R_OK):
            abort(403)

        metadata: dict = {"md_file": md_file}

        # Get file stats for both published date and cache headers
        file_stat = os.stat(md_file)
        metadata["file_mtime"] = file_stat.st_mtime

        with open(md_file, "r") as f:
            metadata.update(self._parse_metadata_from_markdown(f, page))

        metadata["title_inferred"] = not metadata.get("title")
        if not metadata.get("title"):
            with open(md_file, "r") as f:
                metadata["title"], url = self._infer_title_and_url_from_markdown(f)

            if url:
                metadata["external_url"] = url

        if not metadata.get("title"):
            metadata["title"] = os.path.splitext(os.path.basename(md_file))[0]

        if not metadata.get("published"):
            # If the `published` header isn't available in the file,
            # infer it from the file's creation date
            metadata["published"] = datetime.date.fromtimestamp(file_stat.st_ctime)
            metadata["published_inferred"] = True

        return metadata

    @classmethod
    def _parse_author(cls, metadata: dict) -> dict:
        author = None
        author_url = None
        author_photo = None

        if metadata.get("author"):
            if match := cls._author_regex.match(metadata["author"]):
                author = match[1]
                if link := match[2].strip():
                    author_url = link
            else:
                author = metadata["author"]
        else:
            author = config.author
            author_url = config.author_url

        if author_url and cls._email_regex.match(author_url):
            author_url = "mailto:" + author_url

        if metadata.get("author_photo"):
            if link := metadata["author_photo"].strip():
                if cls._url_regex.match(link):
                    author_photo = link
        else:
            author_photo = config.author_photo

        return {
            "author": author,
            "author_url": author_url,
            "author_photo": author_photo,
        }

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

        from pubby._model import AP_CONTEXT

        base_url = config.link or request.host_url.rstrip("/")
        url = base_url.rstrip("/") + metadata.get("uri", "")
        obj, _ = self._ap_integration._build_object(
            md_file,
            url,
            self.activitypub_handler.actor_id,
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

        # Check if the client has a cached version that's still valid
        # Check both If-Modified-Since and If-None-Match headers
        if_modified_since = None
        if_none_match = None
        if has_request_context():
            if_modified_since = request.headers.get("If-Modified-Since")
            if_none_match = request.headers.get("If-None-Match")
        cache_valid = False

        # Check If-Modified-Since
        if if_modified_since and not cache_valid:
            try:
                parsed_date = email.utils.parsedate_tz(if_modified_since)
                if parsed_date:
                    cached_timestamp = email.utils.mktime_tz(parsed_date)  # type: ignore
                    if cached_timestamp is not None and cached_timestamp >= file_mtime:
                        cache_valid = True
            except (ValueError, TypeError, OverflowError):
                # Invalid If-Modified-Since header, ignore it
                pass

        # Check If-None-Match (ETag)
        if if_none_match and not cache_valid:
            # Handle both single ETags and comma-separated lists
            client_etags = [tag.strip() for tag in if_none_match.split(",")]
            if etag in client_etags or "*" in client_etags:
                cache_valid = True

        # Return 304 if cache is valid
        if cache_valid:
            response = make_response("", 304)
            response.headers["Last-Modified"] = last_modified
            response.headers["ETag"] = etag

            # Set Language header for 304 responses too
            article_language = metadata.get("language")
            if article_language:
                response.headers["Language"] = article_language
            elif config.language:
                response.headers["Language"] = config.language

            return response

        prefers_ap = False
        if has_request_context():
            accepts_ap = (
                request.accept_mimetypes["application/activity+json"]
                or request.accept_mimetypes["application/ld+json"]
            )
            prefers_ap = accepts_ap and (
                request.accept_mimetypes["application/activity+json"]
                > request.accept_mimetypes["text/html"]
            )

        if prefers_ap:
            ap_response = self._get_activitypub_page_response(
                md_file=md_file,
                metadata=metadata,
                last_modified=last_modified,
                etag=etag,
            )

            if ap_response:
                return ap_response

        title = title or metadata.get("title") or config.title
        author_info = self._parse_author(metadata)
        mentions = self.webmentions_handler.render_webmentions(
            self.webmentions_handler.retrieve_stored_webmentions(
                config.link + metadata.get("uri", ""),
                direction=WebmentionDirection.IN,
            )
        )

        ap_interactions = ""
        if hasattr(self, "activitypub_handler"):
            interactions = self.activitypub_handler.storage.get_interactions(
                target_resource=config.link + metadata.get("uri", "")
            )
            if interactions:
                ap_interactions = self.activitypub_handler.render_interactions(
                    interactions
                )

        with open(md_file, "r") as f:
            content = self._parse_content(f)

        tags = parse_metadata_tags(metadata.get("tags", ""))

        if as_markdown:
            output = f"# {title}\n\n{content}"
        else:
            with contextlib.ExitStack() as stack:
                if not has_app_context():
                    stack.enter_context(self.app_context())

                output = render_template(
                    "article.html",
                    config=config,
                    title=title,
                    uri=metadata.get("uri"),
                    url=config.link + metadata.get("uri", ""),
                    external_url=metadata.get("external_url"),
                    image=metadata.get("image"),
                    description=metadata.get("description"),
                    published_datetime=metadata.get("published"),
                    published=metadata["published"].strftime("%b %d, %Y"),
                    content=markdown(
                        content,
                        extensions=[
                            "fenced_code",
                            "codehilite",
                            "tables",
                            "toc",
                            "attr_list",
                            "sane_lists",
                            MarkdownAutolink(),
                            MarkdownTaskList(),
                            MarkdownTocMarkers(),
                            MarkdownLatex(),
                            MarkdownMermaid(),
                            MarkdownTags(),
                            MarkdownActivityPubMentions(),
                        ],
                    ),
                    tags=tags,
                    skip_header=skip_header,
                    skip_html_head=skip_html_head,
                    mentions=mentions,
                    ap_interactions=ap_interactions,
                    **author_info,
                )

        response = make_response(output)

        # Set cache headers based on file modification time
        response.headers["Last-Modified"] = last_modified
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

        # Set Language header based on article metadata or global config
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

        return response

    @staticmethod
    def _parse_content(handle: IO) -> str:
        """
        Prepare content for rendering.
        """
        content = ""
        processed_title = False

        for line in handle:
            if line.startswith("# "):
                if not processed_title:
                    processed_title = True
                    continue

            content += line

        return content

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

    def _get_pages_from_feeds(self, *, with_content: bool = False):
        return [
            {
                "uri": entry.link,
                "external_url": entry.link,
                "folder": "",
                "source": urlparse(entry.link).netloc,
                "source_logo": feed.logo,
                "content": entry.content if with_content else "",
                "title": entry.title,
                "description": entry.description,
                "image": entry.enclosure,
                "published": entry.published,
                "author": next(
                    (
                        author
                        for author in (
                            entry.authors
                            or feed.authors
                            or (
                                [
                                    FeedAuthor(
                                        name=config.author,
                                        uri=config.author_url or "",
                                        email="",
                                    )
                                ]
                                if config.author
                                else []
                            )
                        )
                    ),
                    None,
                ),
            }
            for feed in self._feed_parser.parse_feeds().values()
            for entry in feed.entries
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
