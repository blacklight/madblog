import contextlib
import datetime
import os
import re
from abc import ABC, abstractmethod
from logging import getLogger
from pathlib import Path
from typing import IO, Sequence, Tuple

from flask import Flask, abort, has_app_context, render_template
from markdown import Extension

from madblog.config import config
from madblog.tags import parse_metadata_tags

from ._render import render_html

logger = getLogger(__name__)


class MarkdownMixin(ABC):  # pylint: disable=too-few-public-methods
    """
    Provides the Markdown parsing and rendering interface to the main app.
    """

    _title_header_regex = re.compile(r"^#\s*((\[(.*)])|(.*))")
    _author_regex = re.compile(r"^(.+?)\s+<([^>]+)>$")
    _url_regex = re.compile(r"^(https?:\/\/)?[\w\.\-]+\.[a-z]{2,6}\/?")
    _email_regex = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
    _md_extensions: Sequence[str | Extension]
    pages_dir: Path

    @property
    @abstractmethod
    def _app(self) -> Flask: ...

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

    def _render_page_html(
        self,
        *,
        md_file: str,
        metadata: dict,
        title: str,
        skip_header: bool,
        skip_html_head: bool,
        mentions: str,
        ap_interactions: str,
    ) -> str:
        """
        Render a Markdown page to HTML using the article template.
        """
        with open(md_file, "r") as f:
            content = self._parse_markdown_content(f)

        tags = parse_metadata_tags(metadata.get("tags", ""))
        author_info = self._parse_author(metadata)

        with contextlib.ExitStack() as stack:
            if not has_app_context():
                stack.enter_context(self._app.app_context())

            return render_template(
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
                content=render_html(content),
                tags=tags,
                skip_header=skip_header,
                skip_html_head=skip_html_head,
                mentions=mentions,
                ap_interactions=ap_interactions,
                **author_info,
            )

    @staticmethod
    def _parse_markdown_content(handle: IO) -> str:
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
