import datetime
import email.utils
import os
import re

from pathlib import Path
from typing import IO, List, Optional, Tuple, Type
from urllib.parse import urlparse
from email.utils import formatdate

from flask import Flask, Response, abort, make_response, render_template, request
from markdown import markdown
from webmentions import WebmentionDirection, WebmentionsHandler
from webmentions.storage.adapters.file import FileSystemMonitor
from webmentions.server.adapters.flask import bind_webmentions

from .config import config
from .feeds import FeedAuthor, FeedParser
from .autolink import MarkdownAutolink
from .latex import MarkdownLatex
from .mermaid import MarkdownMermaid
from .tasklist import MarkdownTaskList
from .toc import MarkdownTocMarkers
from .notifications import SmtpConfig, build_webmention_email_notifier
from .storage.mentions import FileWebmentionsStorage
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

        self.filesystem_monitor = FileSystemMonitor(
            root_dir=str(self.pages_dir),
            handler=self.webmentions_handler,
            file_to_url_mapper=self._file_to_url,
            throttle_seconds=config.throttle_seconds_on_update,
        )

        if config.enable_webmentions:
            bind_webmentions(self, self.webmentions_handler)

    def _file_to_url(self, f: str) -> str:
        # Return the path relative to self.pages_dir and strip the extension
        f = os.path.relpath(f, self.pages_dir).rsplit(".", 1)[0]
        return f"{config.link}/article/{f}"

    def start(self) -> None:
        if config.enable_webmentions:
            self.filesystem_monitor.start()

    def stop(self) -> None:
        if config.enable_webmentions:
            self.filesystem_monitor.stop()

    @staticmethod
    def _parse_metadata_from_markdown(handle: IO, page: str) -> dict:
        metadata: dict = {"uri": "/article/" + page[:-3]}
        for line in handle:
            if not line.strip() or re.match(r"(^---\s*$)|(^#\s+.*)", line):
                continue

            if not (m := re.match(r"^\[//]: # \(([^:]+):\s*(.*)\)\s*$", line)):
                break

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

        # Check if the client has a cached version that's still valid
        if_modified_since = request.headers.get("If-Modified-Since")
        if if_modified_since:
            try:
                parsed_date = email.utils.parsedate_tz(if_modified_since)
                if not parsed_date:
                    # Invalid If-Modified-Since header, ignore it
                    pass

                cached_timestamp = email.utils.mktime_tz(parsed_date)  # type: ignore
                if cached_timestamp is not None and cached_timestamp >= file_mtime:
                    # Client's cached version is still valid
                    response = make_response("", 304)
                    response.headers["Last-Modified"] = last_modified
                    return response
            except (ValueError, TypeError, OverflowError):
                # Invalid If-Modified-Since header, ignore it
                pass

        title = title or metadata.get("title") or config.title
        author_info = self._parse_author(metadata)
        mentions = self.webmentions_handler.render_webmentions(
            self.webmentions_handler.retrieve_stored_webmentions(
                config.link + metadata.get("uri", ""),
                direction=WebmentionDirection.IN,
            )
        )

        with open(md_file, "r") as f:
            content = self._parse_content(f)

        output = (
            f"# {title}\n\n{content}"
            if as_markdown
            else render_template(
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
                    ],
                ),
                skip_header=skip_header,
                skip_html_head=skip_html_head,
                mentions=mentions,
                **author_info,
            )
        )

        response = make_response(output)

        # Set cache headers based on file modification time
        response.headers["Last-Modified"] = last_modified
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

        if config.webmention_url:
            response.headers["Link"] = f'<{config.webmention_url}>; rel="webmention"'
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
        pages_dir = getattr(app, "pages_dir", "")
        assert pages_dir  # for mypy
        pages_dir = str(pages_dir).rstrip("/")
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

        # Check if the client has a cached version that's still valid
        if last_modified:
            if_modified_since = request.headers.get("If-Modified-Since")
            if if_modified_since:
                try:
                    cached_timestamp = email.utils.mktime_tz(
                        email.utils.parsedate_tz(if_modified_since)  # type: ignore
                    )
                    if (
                        cached_timestamp is not None
                        and cached_timestamp >= most_recent_mtime
                    ):
                        # Client's cached version is still valid
                        response = make_response("", 304)
                        response.headers["Last-Modified"] = last_modified
                        return response
                except (ValueError, TypeError, OverflowError):
                    # Invalid If-Modified-Since header, ignore it
                    pass

        # Render the template
        output = render_template(
            template_name,
            pages=pages,
            config=config,
            view_mode=view_mode,
        )

        # Create response with cache headers
        response = make_response(output)

        if last_modified:
            response.headers["Last-Modified"] = last_modified
            response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

        return response


app = BlogApp(__name__)

from .routes import *

# vim:sw=4:ts=4:et:
