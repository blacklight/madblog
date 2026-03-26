"""
Replies mixin for Madblog.

Provides methods to:
- Retrieve and parse author replies
- Build interaction trees for articles and replies
- Render reply pages
"""

import contextlib
import datetime
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import IO, Callable

from flask import Flask, has_app_context, render_template

from madblog.config import config
from madblog.markdown import render_html, resolve_relative_urls
from madblog.templates import TemplateUtils
from madblog.reactions import (
    build_thread_tree,
    collect_author_likes_map,
    collect_interaction_counts,
    count_reactions,
    _fediverse_url_aliases,
)
from madblog.visibility import Visibility, resolve_visibility


class RepliesMixin(ABC):  # pylint: disable=too-few-public-methods
    """
    Mixin that provides author reply and interaction threading functionality.

    Expects the following to be provided by the concrete class or other mixins:
    - replies_dir: Path to the replies directory
    - _parse_reply_metadata(article_slug, reply_slug) -> dict (from MarkdownMixin)
    - _parse_markdown_content(f) -> str (from MarkdownMixin)
    - _parse_author(metadata) -> dict (from MarkdownMixin)
    - _get_webmentions(metadata) -> list (from WebmentionsMixin)
    - _get_ap_interactions(md_file, extra_target_urls) -> list (from ActivityPubMixin)
    """

    replies_dir: Path
    pages_dir: Path

    _get_ap_interactions: Callable[..., list]
    _get_webmentions: Callable[[dict], list]
    _parse_author: Callable[[dict], dict]
    _parse_markdown_content: Callable[[IO], str]
    _parse_page_metadata: Callable[[str], dict]
    _parse_reply_metadata: Callable[[str | None, str], dict]

    @property
    @abstractmethod
    def _app(self) -> Flask: ...

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

    def _get_article_replies(self, article_slug: str | None) -> list:
        """
        Scan replies/<article_slug>/ and return a list of parsed reply dicts.

        When *article_slug* is ``None``, scans root-level ``.md`` files in
        the replies directory (used for top-level / unlisted replies).

        Each dict contains: slug, title, reply_to, published, content_html,
        permalink, author, author_url, author_photo.

        Standalone likes (files with ``like-of`` but no ``reply-to`` and no
        content) are excluded — they are handled separately by the
        :class:`AuthorReactionsIndex`.

        Replies with visibility ``followers``, ``direct``, or ``draft`` are
        excluded from the reactions display.
        """

        replies_subdir = (
            self.replies_dir / article_slug if article_slug else self.replies_dir
        )

        if not replies_subdir.is_dir():
            return []

        replies = []
        for md_path in replies_subdir.glob("*.md"):
            reply_slug = md_path.stem
            try:
                metadata = self._parse_reply_metadata(article_slug, reply_slug)
            except Exception:
                continue

            # Skip replies with restricted visibility
            visibility = resolve_visibility(metadata)
            if visibility in (
                Visibility.FOLLOWERS,
                Visibility.DIRECT,
                Visibility.DRAFT,
            ):
                continue

            md_file = metadata.pop("md_file")
            with open(md_file, "r") as f:
                content = self._parse_markdown_content(f)

            # Skip standalone likes (like-of present, no body content).
            # Note: reply-to may be auto-derived by _parse_reply_metadata,
            # so we only check like-of + no body content.
            # Metadata comment lines are excluded when detecting real content.
            like_of = metadata.get("like-of")
            body_lines = [
                line
                for line in content.split("\n")
                if line.strip() and not re.match(r"^\[//]: # \(", line)
            ]
            if like_of and not body_lines:
                continue

            author_info = self._parse_author(metadata)
            permalink = (
                f"/reply/{article_slug}/{reply_slug}"
                if article_slug
                else f"/reply/{reply_slug}"
            )

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

    def _build_unlisted_post_dict(
        self,
        *,
        slug: str,
        metadata: dict,
        content: str,
        permalink: str,
        is_article: bool,
    ) -> dict:
        """
        Build a standardized unlisted post dict.

        :param slug: The post slug
        :param metadata: Parsed metadata dict
        :param content: Raw markdown content
        :param permalink: URL path (e.g., "/reply/foo" or "/article/foo")
        :param is_article: True for articles, False for replies
        :return: Post dict with all standard fields
        """
        base_path = "/article" if is_article else "/reply"
        author_info = self._parse_author(metadata)

        return {
            "slug": slug,
            "title": metadata.get("title", slug),
            "published": metadata.get("published"),
            "content_html": render_html(
                resolve_relative_urls(content, config.link, permalink, base_path)
            ),
            "permalink": permalink,
            "full_url": config.link + permalink,
            "uri": permalink,
            "description": metadata.get("description"),
            "image": metadata.get("image"),
            "is_article": is_article,
            **author_info,
        }

    def get_unlisted_posts(self) -> list:
        """
        Get all unlisted posts from both replies/ and pages_dir.

        Returns a list of parsed post dicts including:
        - Root-level replies without ``reply-to`` or ``like-of`` metadata
          (backward compatibility: these default to unlisted visibility)
        - Articles from pages_dir with explicit ``visibility: unlisted``

        Each dict contains: slug, title, published, content_html, permalink,
        full_url, author, author_url, author_photo, is_article (bool).
        """
        posts = []

        # 1. Scan replies/ root for unlisted posts (backward compatible)
        if self.replies_dir.is_dir():
            for md_path in self.replies_dir.glob("*.md"):
                reply_slug = md_path.stem
                try:
                    metadata = self._parse_reply_metadata(None, reply_slug)
                except Exception:
                    continue

                md_file = metadata.pop("md_file")
                with open(md_file, "r") as f:
                    content = self._parse_markdown_content(f)

                # Skip if it has reply-to or like-of (reactions/replies)
                is_unlisted_reply = not (
                    metadata.get("reply-to") or metadata.get("like-of")
                )
                if not is_unlisted_reply:
                    continue

                # Skip if no content
                body_lines = [
                    line
                    for line in content.split("\n")
                    if line.strip() and not re.match(r"^\[//]: # \(", line)
                ]
                if not body_lines:
                    continue

                # Check visibility - unlisted replies default to UNLISTED
                visibility = resolve_visibility(metadata, is_unlisted_reply=True)
                if visibility != Visibility.UNLISTED:
                    continue

                posts.append(
                    self._build_unlisted_post_dict(
                        slug=reply_slug,
                        metadata=metadata,
                        content=content,
                        permalink=f"/reply/{reply_slug}",
                        is_article=False,
                    )
                )

        # 2. Scan pages_dir for articles with visibility: unlisted
        posts.extend(self._get_unlisted_articles())

        # Sort by published date descending (newest first)
        posts.sort(key=lambda p: p.get("published") or datetime.date.min, reverse=True)
        return posts

    def get_ap_replies(self) -> list:
        """
        Get root-level AP replies with ``public`` or ``unlisted`` visibility.

        These are reply files in ``replies/`` that have ``reply-to`` metadata
        (i.e. they are federated replies to external posts) but are not
        anchored to any blog article page.

        Standalone likes (``like-of`` present, no body content) are excluded.

        Each dict contains: slug, title, published, content_html, permalink,
        full_url, reply_to, author, author_url, author_photo, is_article
        (always ``False``).
        """
        posts = []
        if not self.replies_dir.is_dir():
            return posts

        for md_path in self.replies_dir.glob("*.md"):
            reply_slug = md_path.stem
            try:
                metadata = self._parse_reply_metadata(None, reply_slug)
            except Exception:
                continue

            # Only include replies that have reply-to
            if not metadata.get("reply-to"):
                continue

            # Skip standalone likes (like-of present, no reply-to, no content)
            # Note: we already checked reply-to is present, so this handles
            # the case where both like-of and reply-to are set but no content.
            md_file = metadata.pop("md_file")
            with open(md_file, "r") as f:
                content = self._parse_markdown_content(f)

            body_lines = [
                line
                for line in content.split("\n")
                if line.strip() and not re.match(r"^\[//]: # \(", line)
            ]

            if metadata.get("like-of") and not body_lines:
                continue

            # Skip if no content at all
            if not body_lines:
                continue

            # Check visibility - only include public or unlisted
            visibility = resolve_visibility(metadata)
            if visibility not in (Visibility.PUBLIC, Visibility.UNLISTED):
                continue

            post = self._build_unlisted_post_dict(
                slug=reply_slug,
                metadata=metadata,
                content=content,
                permalink=f"/reply/{reply_slug}",
                is_article=False,
            )
            post["reply_to"] = metadata.get("reply-to", "")
            posts.append(post)

        # Sort by published date descending (newest first)
        posts.sort(key=lambda p: p.get("published") or datetime.date.min, reverse=True)
        return posts

    def _get_unlisted_articles(self) -> list:
        """
        Scan pages_dir for articles with visibility: unlisted.

        Returns a list of article dicts formatted like unlisted posts.
        """
        posts = []
        pages_dir = getattr(self, "pages_dir", None)
        if not pages_dir or not pages_dir.is_dir():
            return posts

        replies_dir_str = str(self.replies_dir) if self.replies_dir else ""

        # Walk through pages_dir recursively
        for md_path in pages_dir.rglob("*.md"):
            # Skip files under replies_dir
            if replies_dir_str and str(md_path).startswith(replies_dir_str):
                continue

            # Skip index.md files
            if md_path.name == "index.md":
                continue

            rel_path = str(md_path.relative_to(pages_dir))
            try:
                metadata = self._parse_page_metadata(rel_path)
            except Exception:
                continue

            # Check visibility
            visibility = resolve_visibility(metadata)
            if visibility != Visibility.UNLISTED:
                continue

            md_file = metadata.pop("md_file")
            with open(md_file, "r") as f:
                content = self._parse_markdown_content(f)

            slug = rel_path.rsplit(".", 1)[0]
            posts.append(
                self._build_unlisted_post_dict(
                    slug=slug,
                    metadata=metadata,
                    content=content,
                    permalink=f"/article/{slug}",
                    is_article=True,
                )
            )

        return posts

    @staticmethod
    def _annotate_replies_with_ap_urls(replies: list, ap_base_url: str) -> set[str]:
        """
        Annotate author replies with their ActivityPub URLs and return the set
        of all AP URLs (for use as extra target URLs when fetching interactions).

        :param replies: List of reply dicts to annotate in-place
        :param ap_base_url: The ActivityPub base URL
        :return: Set of all AP URLs for the replies
        """
        ap_urls = set()
        for reply in replies:
            permalink = reply.get("permalink", "")
            if permalink:
                ap_url = ap_base_url + permalink
                ap_urls.add(ap_url)
                if ap_url != reply.get("full_url"):
                    reply["ap_full_url"] = ap_url
                # Also add the content URL variant
                content_url = reply.get("full_url", "")
                if content_url:
                    ap_urls.add(content_url)
        return ap_urls

    @staticmethod
    def _is_article_interaction(
        interaction,
        article_url: str,
        ap_object_url: str | None,
        reply_ap_urls: set[str],
    ) -> bool:
        """
        Check if an interaction should be shown on the article page.

        Interactions targeting the article itself are always included.
        For interactions targeting author reply URLs, only replies and quotes
        are included (likes/boosts on replies appear only on the reply page).
        """
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

    @staticmethod
    def _collect_reply_object_ids(interactions: list) -> set[str]:
        """
        Collect ``object_id`` values from reply/quote interactions.

        These can be used as extra target URLs for a subsequent fetch so
        that nested fediverse replies (reply-to-reply) are also retrieved.
        """
        ids: set[str] = set()
        for interaction in interactions:
            itype = getattr(interaction, "interaction_type", None)
            type_val = None
            if itype:
                type_val = (
                    itype.value
                    if hasattr(itype, "value")
                    else str(itype) if itype else ""
                )
            if type_val not in ("reply", "quote"):
                continue

            obj_id = getattr(interaction, "object_id", None)
            if obj_id:
                ids.add(obj_id)
        return ids

    def _follow_reply_chains(self, md_file: str, ap_interactions: list) -> list:
        """
        Iteratively follow fediverse reply chains.

        Collects ``object_id`` values from reply/quote interactions already
        fetched and queries the storage for interactions targeting those IDs.
        Repeats until no new interactions are discovered (bounded to 10
        iterations).

        :param md_file: The Markdown file (forwarded to ``_get_ap_interactions``).
        :param ap_interactions: Initial list of AP interactions (extended
            **in-place** with newly discovered interactions).
        :return: The same *ap_interactions* list, extended with any new items.
        """
        # Track target_resources already queried (to avoid re-querying)
        queried_targets: set[str] = set()
        # Track object_ids already in our result set (to avoid duplicates)
        seen_object_ids: set[str] = set()
        for i in ap_interactions:
            obj_id = getattr(i, "object_id", None)
            if obj_id:
                seen_object_ids.add(obj_id)

        _MAX_DEPTH = 10
        for _ in range(_MAX_DEPTH):
            new_target_ids = self._collect_reply_object_ids(ap_interactions)
            new_target_ids -= queried_targets

            if not new_target_ids:
                break

            queried_targets.update(new_target_ids)
            new_interactions = self._get_ap_interactions(
                md_file, extra_target_urls=list(new_target_ids)
            )

            # Keep only genuinely new interactions
            fresh = []
            for i in new_interactions:
                obj_id = getattr(i, "object_id", None)
                if obj_id and obj_id not in seen_object_ids:
                    seen_object_ids.add(obj_id)
                    fresh.append(i)

            if not fresh:
                break

            ap_interactions.extend(fresh)

        return ap_interactions

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
        ap_integration = getattr(self, "_ap_integration", None)
        reply_ap_urls: set[str] = set()
        if ap_integration:
            reply_ap_urls = self._annotate_replies_with_ap_urls(
                author_replies, ap_integration.base_url
            )

        ap_interactions = self._get_ap_interactions(
            md_file, extra_target_urls=list(reply_ap_urls)
        )

        # Follow nested fediverse reply chains
        self._follow_reply_chains(md_file, ap_interactions)

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
    def _find_descendant_replies(
        candidate_replies: dict[str, dict],
        valid_parent_urls: set[str],
        ap_base_url: str | None,
    ) -> list[dict]:
        """
        Find author replies that are descendants of a given set of parent URLs.

        This iteratively finds replies whose reply-to matches a known valid URL,
        then adds their URLs to the valid set and continues until no more
        descendants are found.

        :param candidate_replies: Dict mapping slug -> reply dict
        :param valid_parent_urls: Set of URLs that are valid parents (modified in-place)
        :param ap_base_url: ActivityPub base URL (or None if AP is disabled)
        :return: List of descendant reply dicts
        """
        descendant_replies = []
        changed = True

        while changed:
            changed = False
            for slug, reply in list(candidate_replies.items()):
                reply_to = reply.get("reply_to", "")
                if reply_to not in valid_parent_urls:
                    continue

                descendant_replies.append(reply)

                # Add this reply's URLs to valid_parent_urls
                if reply.get("full_url"):
                    valid_parent_urls.add(reply["full_url"])

                if not ap_base_url:
                    del candidate_replies[slug]
                    changed = True
                    continue

                permalink = reply.get("permalink", "")
                if not permalink:
                    del candidate_replies[slug]
                    changed = True
                    continue

                nested_ap_url = ap_base_url + permalink
                valid_parent_urls.add(nested_ap_url)
                if nested_ap_url != reply.get("full_url"):
                    reply["ap_full_url"] = nested_ap_url

                del candidate_replies[slug]
                changed = True

        return descendant_replies

    @staticmethod
    def _collect_reply_ap_urls(replies: list[dict], ap_base_url: str) -> set[str]:
        """
        Collect ActivityPub URLs for a list of author replies.

        :param replies: List of reply dicts with 'permalink' and 'full_url' keys
        :param ap_base_url: ActivityPub base URL
        :return: Set of AP URLs for the replies
        """
        urls = set()
        for reply in replies:
            permalink = reply.get("permalink", "")
            if not permalink:
                continue

            urls.add(ap_base_url + permalink)
            content_url = reply.get("full_url", "")
            if content_url:
                urls.add(content_url)

        return urls

    @staticmethod
    def _add_interaction_urls(interactions: list, url_set: set[str]) -> None:
        """
        Add object_id and activity_id from interactions to a URL set,
        together with their fediverse URL aliases.

        :param interactions: List of AP interaction objects
        :param url_set: Set to add URLs to (modified in-place)
        """
        for interaction in interactions:
            for attr in ("object_id", "activity_id"):
                url = getattr(interaction, attr, None)
                if url:
                    url_set.add(url)
                    url_set.update(_fediverse_url_aliases(url))

    def _get_reply_interactions(
        self, md_file: str, metadata: dict, article_slug: str | None, reply_slug: str
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
        ap_integration = getattr(self, "_ap_integration", None)
        ap_base_url = ap_integration.base_url if ap_integration else None

        # Build set of valid parent URLs (the current reply and its AP variant)
        valid_parent_urls = {reply_url}
        if ap_base_url:
            valid_parent_urls.add(ap_base_url + reply_uri)

        # Get candidate replies (all except current)
        all_author_replies = self._get_article_replies(article_slug)
        candidate_replies = {
            r.get("slug"): r for r in all_author_replies if r.get("slug") != reply_slug
        }

        # First pass: find direct descendant replies
        descendant_replies = self._find_descendant_replies(
            candidate_replies, valid_parent_urls, ap_base_url
        )

        # Build extra target URLs for fetching interactions
        extra_target_urls = self._build_extra_target_urls(
            reply_url, reply_uri, descendant_replies, ap_base_url
        )

        # Fetch webmentions and AP interactions
        webmentions = self._get_webmentions(metadata)
        ap_interactions = self._get_ap_interactions(
            md_file, extra_target_urls=list(extra_target_urls)
        )

        # Iteratively discover deeper levels of the thread:
        # author reply → fediverse reaction → author reply → …
        # Each iteration adds interaction URLs to valid_parent_urls,
        # finds new descendant author replies, fetches their AP
        # interactions, and repeats until convergence (max 10).
        _MAX_INTERLEAVE = 10
        for _ in range(_MAX_INTERLEAVE):
            self._add_interaction_urls(ap_interactions, valid_parent_urls)

            more_descendants = self._find_descendant_replies(
                candidate_replies, valid_parent_urls, ap_base_url
            )

            if not more_descendants:
                break

            descendant_replies.extend(more_descendants)

            if not ap_base_url:
                continue

            extra_target_urls.update(
                self._collect_reply_ap_urls(more_descendants, ap_base_url)
            )
            ap_interactions = self._get_ap_interactions(
                md_file, extra_target_urls=list(extra_target_urls)
            )

        # Follow nested fediverse reply chains
        self._follow_reply_chains(md_file, ap_interactions)

        return build_thread_tree(
            webmentions=webmentions,
            ap_interactions=ap_interactions,
            author_replies=descendant_replies,
            article_url=reply_url,
        )

    def _build_extra_target_urls(
        self,
        reply_url: str,
        reply_uri: str,
        descendant_replies: list,
        ap_base_url: str | None,
    ) -> set[str]:
        """
        Build the set of extra target URLs for fetching AP interactions.

        Includes the AP URL variant for the current reply plus URLs for all
        descendant author replies.
        """
        if not ap_base_url:
            return set()

        extra_urls = self._collect_reply_ap_urls(descendant_replies, ap_base_url)

        # Add AP URL variant for the current reply if it differs
        ap_url = ap_base_url + reply_uri
        if ap_url != reply_url:
            extra_urls.add(ap_url)

        return extra_urls

    def _render_reply_html(
        self,
        *,
        md_file: str,
        metadata: dict,
        title: str,
        article_slug: str | None,
        reactions_tree: list,
    ) -> str:
        """
        Render a reply Markdown file to HTML using the reply template.
        """
        from madblog.markdown import render_html

        with open(md_file, "r") as f:
            content = self._parse_markdown_content(f)

        author_info = self._parse_author(metadata)
        reply_to = metadata.get("reply-to", "")
        reactions_counts = count_reactions(reactions_tree)

        reply_url = config.link + metadata.get("uri", "")
        reactions_index = getattr(self, "author_reactions_index", None)
        author_likes = (
            reactions_index.get_reactions(reply_url) if reactions_index else []
        )

        # Per-interaction author likes (e.g. author liked a fediverse reply)
        author_likes_map: dict = {}
        if reactions_index:
            author_likes_map = collect_author_likes_map(
                reactions_tree, reactions_index.get_reactions
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
                "reply.html",
                config=config,
                title=title,
                uri=metadata.get("uri"),
                url=reply_url,
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
                like_of=metadata.get("like-of"),
                author_likes=author_likes,
                author_likes_map=author_likes_map,
                article_slug=article_slug,
                reactions_tree=reactions_tree,
                reactions_counts=reactions_counts,
                interaction_counts=interaction_counts,
                utils=TemplateUtils(),
                **author_info,
            )
