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
from madblog.templates import TemplateUtils
from madblog.reactions import collect_interaction_counts, count_reactions

from ._render import render_html, resolve_relative_urls

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
    replies_dir: Path

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
                parsed_dt = datetime.datetime.fromisoformat(m.group(2))
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=datetime.timezone.utc)
                metadata[m.group(1)] = parsed_dt
            else:
                metadata[m.group(1)] = m.group(2)

        return metadata

    @staticmethod
    def _infer_title_and_url_from_markdown(handle: IO) -> Tuple[str, str]:
        for line in handle:
            # Skip blank lines, YAML front-matter delimiters, and
            # metadata comment lines so that a heading appearing after
            # them can still be detected.
            if (
                not line.strip()
                or re.match(r"^---\s*$", line)
                or re.match(r"^\[//\]: # \(", line)
            ):
                continue

            if not (m := re.match(r"^#\s+(\[?([^]]+)\]?(\((.*)\))?)\s*$", line)):
                break

            title = (m.group(2) or "").strip()
            url = (m.group(4) or "").strip() if m.group(4) else m.group(4)
            return title, url

        return "", ""

    def _resolve_and_parse_metadata(
        self,
        *,
        base_dir: Path,
        rel_path: str,
        page_key: str,
        uri: str | None = None,
        title_fallback: str | None = None,
    ) -> dict:
        """
        Shared helper: resolve a Markdown file under *base_dir*, guard
        against path traversal, read metadata, infer title and published
        date.

        :param base_dir: Root directory the file must reside under.
        :param rel_path: Path relative to *base_dir* (must end in ``.md``).
        :param page_key: Key passed to ``_parse_metadata_from_markdown``.
        :param uri: If given, overrides the default ``/article/…`` URI.
        :param title_fallback: Last-resort title when heading inference
            also fails.  Defaults to the filename stem.
        """
        md_file = os.path.realpath(os.path.join(base_dir, rel_path))
        if not os.path.isfile(md_file) or not md_file.startswith(str(base_dir)):
            abort(404)

        if not os.access(md_file, os.R_OK):
            abort(403)

        metadata: dict = {"md_file": md_file}
        file_stat = os.stat(md_file)
        metadata["file_mtime"] = file_stat.st_mtime

        with open(md_file, "r") as f:
            metadata.update(self._parse_metadata_from_markdown(f, page_key))

        if uri is not None:
            metadata["uri"] = uri

        metadata["title_inferred"] = not metadata.get("title")
        if not metadata.get("title"):
            with open(md_file, "r") as f:
                metadata["title"], url = self._infer_title_and_url_from_markdown(f)

            if url:
                metadata["external_url"] = url

        if not metadata.get("title"):
            metadata["title"] = (
                title_fallback
                if title_fallback is not None
                else os.path.splitext(os.path.basename(md_file))[0]
            )

        if not metadata.get("published"):
            metadata["published"] = datetime.datetime.fromtimestamp(
                file_stat.st_ctime, tz=datetime.timezone.utc
            )
            metadata["published_inferred"] = True

        return metadata

    def _parse_page_metadata(self, page: str) -> dict:
        """
        Parse the metadata from a Markdown page
        """
        if not page.endswith(".md"):
            page = page + ".md"

        return self._resolve_and_parse_metadata(
            base_dir=self.pages_dir,
            rel_path=page,
            page_key=page,
        )

    def _parse_folder_metadata(self, folder_path: str) -> dict:
        """
        Parse metadata from index.md in the given folder (relative to pages_dir).

        Returns a dict with:
        - Standard metadata keys (title, description, image, etc.)
        - ``has_content``: True if index.md has non-whitespace body content
        - ``md_file``: Absolute path to index.md (if it exists)

        Returns empty dict if no index.md exists.
        """
        index_file = self.pages_dir / folder_path / "index.md"
        if not index_file.is_file():
            return {}

        md_file = os.path.realpath(str(index_file))
        if not md_file.startswith(str(self.pages_dir)):
            return {}

        metadata: dict = {"md_file": md_file}

        with open(md_file, "r") as f:
            metadata.update(
                self._parse_metadata_from_markdown(f, f"{folder_path}/index.md")
            )

        if not metadata.get("title"):
            with open(md_file, "r") as f:
                metadata["title"], _ = self._infer_title_and_url_from_markdown(f)

        with open(md_file, "r") as f:
            content = self._parse_markdown_content(f)
            # Filter out metadata comment lines to detect actual body content
            content_lines = [
                line
                for line in content.split("\n")
                if line.strip()
                and not re.match(r"^\[//\]: # \(", line)
                and not re.match(r"^---\s*$", line)
            ]
            metadata["has_content"] = bool(content_lines)

        return metadata

    def _parse_reply_metadata(self, article_slug: str, reply_slug: str) -> dict:
        """
        Parse the metadata from a reply Markdown file under ``replies_dir``.

        If ``reply-to`` is not set explicitly, it is derived from the
        ``article_slug`` when a corresponding article file exists under
        ``pages_dir``.
        """
        rel_path = os.path.join(article_slug, reply_slug + ".md")
        metadata = self._resolve_and_parse_metadata(
            base_dir=self.replies_dir,
            rel_path=rel_path,
            page_key=rel_path,
            uri=f"/reply/{article_slug}/{reply_slug}",
            title_fallback=reply_slug,
        )

        if "reply-to" not in metadata:
            article_file = self.pages_dir / f"{article_slug}.md"
            if article_file.is_file():
                metadata["reply-to"] = f"{config.link}/article/{article_slug}"

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

        # Fall back to config defaults when article metadata doesn't
        # provide author_url / author_photo explicitly.
        if not author_url:
            author_url = config.author_url

        if author_url and cls._email_regex.match(author_url):
            author_url = "mailto:" + author_url

        if metadata.get("author_photo"):
            if link := metadata["author_photo"].strip():
                if cls._url_regex.match(link):
                    author_photo = link

        if not author_photo:
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
        reactions_tree: list,
    ) -> str:
        """
        Render a Markdown page to HTML using the article template.
        """
        with open(md_file, "r") as f:
            content = self._parse_markdown_content(f)

        tags = parse_metadata_tags(metadata.get("tags", ""))
        author_info = self._parse_author(metadata)
        reactions_counts = count_reactions(reactions_tree)

        page_url = config.link + metadata.get("uri", "")
        reactions_index = getattr(self, "author_reactions_index", None)
        author_likes = (
            reactions_index.get_reactions(page_url) if reactions_index else []
        )

        # Compute per-interaction reaction counts using O(1) indexed lookups
        interaction_counts: dict = {}
        ap_handler = getattr(self, "activitypub_handler", None)
        if ap_handler:
            storage = ap_handler.storage
            ap_link = getattr(config, "activitypub_link", "") or config.link
            interaction_counts = collect_interaction_counts(
                reactions_tree,
                lambda target: list(storage.get_interactions(target_resource=target)),
                blog_url=config.link,
                ap_url=ap_link,
            )

        with contextlib.ExitStack() as stack:
            if not has_app_context():
                stack.enter_context(self._app.app_context())

            return render_template(
                "article.html",
                config=config,
                title=title,
                uri=metadata.get("uri"),
                url=page_url,
                external_url=metadata.get("external_url"),
                image=metadata.get("image"),
                description=metadata.get("description"),
                published_datetime=metadata.get("published"),
                published=metadata["published"].strftime("%b %d, %Y"),
                content=render_html(
                    resolve_relative_urls(content, config.link, metadata.get("uri", ""))
                ),
                tags=tags,
                skip_header=skip_header,
                skip_html_head=skip_html_head,
                like_of=metadata.get("like-of"),
                author_likes=author_likes,
                reactions_tree=reactions_tree,
                reactions_counts=reactions_counts,
                interaction_counts=interaction_counts,
                utils=TemplateUtils(),
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
