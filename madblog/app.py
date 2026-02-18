import datetime
import os
import re
from pathlib import Path
from typing import IO, List, Optional, Tuple, Type

from flask import Flask, Response, abort, make_response, render_template
from markdown import markdown
from webmentions import WebmentionDirection, WebmentionsHandler
from webmentions.storage.adapters.file import FileSystemMonitor
from webmentions.server.adapters.flask import bind_webmentions

from .config import config
from .latex import MarkdownLatex
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
            if not line:
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

        md_file = os.path.join(self.pages_dir, page)
        if not os.path.isfile(md_file):
            abort(404)

        metadata = {}
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
            metadata["published"] = datetime.date.fromtimestamp(
                os.stat(md_file).st_ctime
            )
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
        title: Optional[str] = None,
        skip_header: bool = False,
        skip_html_head: bool = False,
    ) -> Response:
        """
        Get the HTML for a Markdown page
        """
        if not page.endswith(".md"):
            page = page + ".md"

        metadata = self._parse_page_metadata(page)
        title = title or metadata.get("title") or config.title
        author_info = self._parse_author(metadata)
        mentions = self.webmentions_handler.render_webmentions(
            self.webmentions_handler.retrieve_stored_webmentions(
                config.link + metadata.get("uri", ""),
                direction=WebmentionDirection.IN,
            )
        )

        with open(os.path.join(self.pages_dir, page), "r") as f:
            content = self._parse_content(f)

        html = render_template(
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
                extensions=["fenced_code", "codehilite", "tables", MarkdownLatex()],
            ),
            skip_header=skip_header,
            skip_html_head=skip_html_head,
            mentions=mentions,
            **author_info,
        )

        response = make_response(html)
        if config.webmention_url:
            response.headers["Link"] = f'<{config.webmention_url}>; rel="webmention"'

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

    def get_pages(
        self,
        *,
        with_content: bool = False,
        skip_header: bool = False,
        skip_html_head: bool = False,
        sorter: Type[PagesSorter] = PagesSortByTime,
        reverse: bool = True,
    ) -> List[Tuple[int, dict]]:
        pages_dir = getattr(app, "pages_dir", "")
        assert pages_dir  # for mypy
        pages_dir = str(pages_dir).rstrip("/")
        pages = [
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

        sorter_func = sorter(pages)
        pages.sort(key=sorter_func, reverse=reverse)
        return list(enumerate(pages))


app = BlogApp(__name__)

from .routes import *

# vim:sw=4:ts=4:et:
