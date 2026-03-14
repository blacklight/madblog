"""
Threading model for interleaving reactions (Webmentions, AP interactions)
with author replies, plus a persisted index of author reactions (likes, etc.).
"""

import datetime
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, List, Optional

from madblog.monitor import ChangeType

logger = logging.getLogger(__name__)


class ReactionType(Enum):
    """Type of reaction in a thread."""

    WEBMENTION = "webmention"
    AP_INTERACTION = "ap_interaction"
    AUTHOR_REPLY = "author_reply"


@dataclass
class ThreadNode:
    """A node in a reaction thread tree."""

    item: Any
    reaction_type: ReactionType
    identity: str
    reply_to: Optional[str] = None
    published: Optional[datetime.datetime] = None
    children: List["ThreadNode"] = field(default_factory=list)


def reaction_anchor_id(prefix: str, identity: str) -> str:
    """
    Generate a stable anchor ID from a reaction identity URL.

    :param prefix: Prefix for the anchor (e.g. 'wm', 'ap', 'reply')
    :param identity: The unique identity URL of the reaction
    :return: A stable anchor ID like 'wm-abc123def456'
    """
    digest = hashlib.md5(identity.encode()).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _get_webmention_identity(wm) -> str:
    """Extract the identity URL from a Webmention object."""
    return getattr(wm, "source", "") or ""


def _get_ap_interaction_identity(interaction) -> str:
    """Extract the identity URL from an AP Interaction object."""
    return (
        getattr(interaction, "object_id", None)
        or getattr(interaction, "activity_id", "")
        or ""
    )


def _fediverse_url_aliases(url: str) -> list[str]:
    """
    Return alternative URL forms for the same fediverse resource.

    Mastodon (and compatible software) exposes two URL forms:

    - **Pretty** (web UI): ``https://instance/@user/statuses/ID``
      or ``https://instance/@user/ID``
    - **Canonical** (ActivityPub): ``https://instance/users/user/statuses/ID``

    This helper returns the other form(s) so that nodes can be found
    regardless of which format was used in a ``reply-to`` header.
    """
    aliases: list[str] = []

    # /@user/statuses/ID → /users/user/statuses/ID
    if "/@" in url:
        m = re.match(r"^(https?://[^/]+)/@([^/]+)/statuses/(.+)$", url)
        if m:
            aliases.append(f"{m.group(1)}/users/{m.group(2)}/statuses/{m.group(3)}")
            return aliases
        # /@user/ID (no /statuses/ segment) → /users/user/statuses/ID
        m = re.match(r"^(https?://[^/]+)/@([^/]+)/(\d+)$", url)
        if m:
            aliases.append(f"{m.group(1)}/users/{m.group(2)}/statuses/{m.group(3)}")
            return aliases

    # /users/user/statuses/ID → /@user/statuses/ID and /@user/ID
    m = re.match(r"^(https?://[^/]+)/users/([^/]+)/statuses/(.+)$", url)
    if m:
        aliases.append(f"{m.group(1)}/@{m.group(2)}/statuses/{m.group(3)}")
        aliases.append(f"{m.group(1)}/@{m.group(2)}/{m.group(3)}")

    return aliases


def _get_webmention_reply_to(*_) -> Optional[str]:
    """
    Extract what a Webmention is replying to.

    For now, Webmentions are treated as top-level reactions to the article.
    In the future, this could check wm.in_reply_to if the library provides it.
    """
    return None


def _get_ap_interaction_reply_to(interaction) -> Optional[str]:
    """
    Extract what an AP interaction is replying to.

    For reply and quote interactions the ``target_resource`` field holds the
    URL of the object being replied to (set from ``inReplyTo`` by the inbox
    handler).  For other interaction types (like, boost, mention) we return
    ``None`` so they are treated as top-level reactions.
    """
    interaction_type = getattr(interaction, "interaction_type", None)
    type_val = None

    if interaction_type:
        type_val = (
            interaction_type.value
            if hasattr(interaction_type, "value")
            else str(interaction_type) if interaction_type else ""
        )

    if type_val in ("reply", "quote"):
        return getattr(interaction, "target_resource", None) or None

    return None


def _to_datetime(dt: Any) -> Optional[datetime.datetime]:
    """Convert a date/datetime/string to a timezone-aware datetime for sorting."""
    if dt is None:
        return None
    if isinstance(dt, datetime.datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    if isinstance(dt, datetime.date):
        return datetime.datetime.combine(
            dt, datetime.time.min, tzinfo=datetime.timezone.utc
        )
    if isinstance(dt, str):
        try:
            parsed = datetime.datetime.fromisoformat(dt.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=datetime.timezone.utc)
            return parsed
        except ValueError:
            return None
    return None


def _create_webmention_nodes(webmentions: list, nodes: dict[str, ThreadNode]) -> None:
    """
    Populate *nodes* with :class:`ThreadNode` entries for each Webmention.

    :param webmentions: Raw Webmention objects.
    :param nodes: Shared ``identity → node`` dict (mutated in place).
    """
    for wm in webmentions:
        identity = _get_webmention_identity(wm)
        if not identity:
            continue

        published = _to_datetime(
            getattr(wm, "published", None) or getattr(wm, "created_at", None)
        )

        nodes[identity] = ThreadNode(
            item=wm,
            reaction_type=ReactionType.WEBMENTION,
            identity=identity,
            reply_to=_get_webmention_reply_to(wm),
            published=published,
        )


def _create_ap_interaction_nodes(
    ap_interactions: list, nodes: dict[str, ThreadNode]
) -> None:
    """
    Populate *nodes* with :class:`ThreadNode` entries for each AP interaction.

    Each node is also registered under its fediverse URL aliases (e.g.
    Mastodon ``/@user`` ↔ ``/users/user``) so that ``reply-to`` headers
    using either format resolve correctly.

    :param ap_interactions: Raw AP Interaction objects.
    :param nodes: Shared ``identity → node`` dict (mutated in place).
    """
    for interaction in ap_interactions:
        identity = _get_ap_interaction_identity(interaction)
        if not identity:
            continue

        published = _to_datetime(
            getattr(interaction, "published", None)
            or getattr(interaction, "created_at", None)
        )

        node = nodes[identity] = ThreadNode(
            item=interaction,
            reaction_type=ReactionType.AP_INTERACTION,
            identity=identity,
            reply_to=_get_ap_interaction_reply_to(interaction),
            published=published,
        )

        for alias in _fediverse_url_aliases(identity):
            if alias not in nodes:
                nodes[alias] = node


def _create_author_reply_nodes(
    author_replies: list, nodes: dict[str, ThreadNode]
) -> None:
    """
    Populate *nodes* with :class:`ThreadNode` entries for each author reply.

    When ``activitypub_link`` differs from ``link``, the node is also
    registered under the AP-domain URL so that AP interactions targeting
    that URL can find their parent.

    :param author_replies: Dicts returned by ``_get_article_replies``.
    :param nodes: Shared ``identity → node`` dict (mutated in place).
    """
    for reply in author_replies:
        identity = reply.get("full_url", "")
        if not identity:
            continue

        published = _to_datetime(reply.get("published"))

        node = nodes[identity] = ThreadNode(
            item=reply,
            reaction_type=ReactionType.AUTHOR_REPLY,
            identity=identity,
            reply_to=reply.get("reply_to"),
            published=published,
        )

        ap_alias = reply.get("ap_full_url")
        if ap_alias and ap_alias != identity:
            nodes[ap_alias] = node


def _assemble_tree(nodes: dict[str, ThreadNode], article_url: str) -> List[ThreadNode]:
    """
    Link child nodes to their parents and return the sorted root list.

    Aliases (multiple keys pointing to the same :class:`ThreadNode`) are
    deduplicated so each node is processed exactly once.  Roots are sorted
    by ``published`` descending (newest first); children are sorted ascending
    (oldest first) for natural conversation flow.

    :param nodes: Fully populated ``identity → node`` dict.
    :param article_url: The article URL — nodes replying to it become roots.
    :return: Sorted list of root :class:`ThreadNode` objects.
    """
    roots: List[ThreadNode] = []
    seen: set[int] = set()

    for node in nodes.values():
        node_id = id(node)
        if node_id in seen:
            continue
        seen.add(node_id)

        parent_id = node.reply_to

        if parent_id == article_url or not parent_id:
            roots.append(node)
        elif parent_id in nodes:
            nodes[parent_id].children.append(node)
        else:
            roots.append(node)

    _EPOCH = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    roots.sort(key=lambda n: n.published or _EPOCH, reverse=True)

    for node in nodes.values():
        node.children.sort(key=lambda n: n.published or _EPOCH)

    return roots


def build_thread_tree(
    webmentions: list,
    ap_interactions: list,
    author_replies: list,
    article_url: str,
) -> List[ThreadNode]:
    """
    Build a thread tree from reactions and author replies.

    :param webmentions: List of Webmention objects
    :param ap_interactions: List of AP Interaction objects
    :param author_replies: List of author reply dicts (from _get_article_replies)
    :param article_url: The full URL of the article being reacted to
    :return: List of root ThreadNode objects, sorted by published DESC
    """
    nodes: dict[str, ThreadNode] = {}
    _create_webmention_nodes(webmentions, nodes)
    _create_ap_interaction_nodes(ap_interactions, nodes)
    _create_author_reply_nodes(author_replies, nodes)
    return _assemble_tree(nodes, article_url)


def count_reactions(roots: List[ThreadNode]) -> dict:
    """
    Walk the thread tree and tally reactions by type.

    :param roots: Root nodes returned by :func:`build_thread_tree`.
    :return: Dict with keys ``likes``, ``boosts``, ``replies``,
        ``quotes``, ``mentions``, ``webmentions``, ``author_replies``,
        and ``total``.
    """
    counts: dict[str, int] = {
        "likes": 0,
        "boosts": 0,
        "replies": 0,
        "quotes": 0,
        "mentions": 0,
        "webmentions": 0,
        "author_replies": 0,
        "total": 0,
    }

    stack = list(roots)
    while stack:
        node = stack.pop()
        counts["total"] += 1
        stack.extend(node.children)

        if node.reaction_type == ReactionType.AUTHOR_REPLY:
            counts["author_replies"] += 1
            continue

        type_val = None
        if node.reaction_type == ReactionType.WEBMENTION:
            counts["webmentions"] += 1
            mt = getattr(node.item, "mention_type", None)
            if mt:
                type_val = mt.value if hasattr(mt, "value") else str(mt) if mt else ""
        elif node.reaction_type == ReactionType.AP_INTERACTION:
            it = getattr(node.item, "interaction_type", None)
            if it:
                type_val = it.value if hasattr(it, "value") else str(it) if it else ""
        else:
            continue

        if type_val == "like":
            counts["likes"] += 1
        elif type_val in ("boost", "repost"):
            counts["boosts"] += 1
        elif type_val == "reply":
            counts["replies"] += 1
        elif type_val == "quote":
            counts["quotes"] += 1
        elif type_val == "mention":
            counts["mentions"] += 1

    return counts


def _count_interactions_list(interactions: list) -> dict[str, int]:
    """
    Count interactions by type from a flat list.

    :param interactions: List of Interaction objects.
    :return: Dict with keys ``likes``, ``boosts``, ``replies``,
        ``quotes``, ``mentions``, ``webmentions``, ``author_replies``,
        and ``total``.
    """
    counts: dict[str, int] = {
        "likes": 0,
        "boosts": 0,
        "replies": 0,
        "quotes": 0,
        "mentions": 0,
        "webmentions": 0,
        "author_replies": 0,
        "total": 0,
    }

    for interaction in interactions:
        counts["total"] += 1
        itype = getattr(interaction, "interaction_type", None)
        if not itype:
            continue

        type_val = itype.value if hasattr(itype, "value") else str(itype)

        if type_val == "like":
            counts["likes"] += 1
        elif type_val in ("boost", "repost"):
            counts["boosts"] += 1
        elif type_val == "reply":
            counts["replies"] += 1
        elif type_val == "quote":
            counts["quotes"] += 1
        elif type_val == "mention":
            counts["mentions"] += 1
        elif type_val == "webmention":
            counts["webmentions"] += 1
        elif type_val == "author_reply":
            counts["author_replies"] += 1

    return counts


def collect_interaction_counts(
    roots: List[ThreadNode],
    get_interactions_fn,
    blog_url: str = "",
    ap_url: str = "",
) -> dict[str, dict[str, int]]:
    """
    Collect reaction counts for each node in the thread tree.

    For AP interactions, uses ``object_id`` as the lookup key.
    For webmentions, uses ``source`` URL (translated to AP URL if local).
    For author replies, uses ``ap_full_url`` or ``full_url``.

    Also counts author reply children directly from the tree since
    they are stored locally, not in the AP storage.

    The ``get_interactions_fn`` callback is called once per unique
    key to retrieve reactions targeting that object.

    :param roots: Root nodes returned by :func:`build_thread_tree`.
    :param get_interactions_fn: Callable that takes a ``target_resource``
        string and returns a list of Interaction objects.
    :param blog_url: The blog's main URL (config.link).
    :param ap_url: The blog's ActivityPub URL (activitypub_link).
    :return: Dict mapping identity URL → counts dict (same structure
        as :func:`count_reactions`).
    """
    result: dict[str, dict[str, int]] = {}
    seen: set[str] = set()

    def translate_url(url: str) -> str:
        """Translate blog URL to AP URL if applicable."""
        if blog_url and ap_url and url.startswith(blog_url):
            return ap_url + url[len(blog_url) :]
        return url

    def count_author_reply_children(node: ThreadNode) -> int:
        """Count author reply children in the subtree."""
        count = 0
        for child in node.children:
            if child.reaction_type == ReactionType.AUTHOR_REPLY:
                count += 1
            count += count_author_reply_children(child)
        return count

    stack = list(roots)
    while stack:
        node = stack.pop()
        stack.extend(node.children)

        # Determine the lookup key and display key based on reaction type
        lookup_key: str | None = None
        display_key: str | None = None

        if node.reaction_type == ReactionType.AP_INTERACTION:
            lookup_key = getattr(node.item, "object_id", None)
            display_key = lookup_key
        elif node.reaction_type == ReactionType.WEBMENTION:
            source = getattr(node.item, "source", None)
            if source:
                display_key = source
                lookup_key = translate_url(source)
        elif node.reaction_type == ReactionType.AUTHOR_REPLY:
            if isinstance(node.item, dict):
                # Prefer ap_full_url for lookups, fall back to full_url
                display_key = node.item.get("full_url")
                lookup_key = node.item.get("ap_full_url") or display_key
                if lookup_key:
                    lookup_key = translate_url(lookup_key)

        if not lookup_key or not display_key:
            continue

        if lookup_key in seen:
            continue

        seen.add(lookup_key)
        interactions = get_interactions_fn(lookup_key)

        # Start with AP interaction counts
        counts = (
            _count_interactions_list(interactions)
            if interactions
            else {
                "likes": 0,
                "boosts": 0,
                "replies": 0,
                "quotes": 0,
                "mentions": 0,
                "webmentions": 0,
                "author_replies": 0,
                "total": 0,
            }
        )

        # Add author reply children from the thread tree
        ar_count = count_author_reply_children(node)
        if ar_count:
            counts["author_replies"] += ar_count
            counts["total"] += ar_count

        if counts["total"]:
            result[display_key] = counts

    return result


# ------------------------------------------------------------------
# Author-reactions index (JSON-persisted)
# ------------------------------------------------------------------

_METADATA_RE = re.compile(r"^\[//\]: # \(([^:]+):\s*(.*)\)\s*$")


class AuthorReactionsIndex:
    """
    JSON-persisted reverse index of author reactions.

    Maps ``target_url → [reaction_info]`` so that target pages can
    display an "author liked this" indicator without scanning all reply
    files on every render.

    Only *local* targets (URLs starting with *base_url*) are tracked.
    """

    def __init__(
        self,
        state_dir: Path,
        replies_dir: Path,
        base_url: str,
    ):
        self._state_dir = Path(state_dir)
        self._replies_dir = Path(replies_dir)
        self._base_url = base_url.rstrip("/")
        self._index_file = self._state_dir / "author_reactions_index.json"
        self._index: dict[str, list[dict]] = {}
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """
        Load the index from JSON on disk.

        If the file does not exist (first run or migration), perform a
        one-time full scan of all ``.md`` files under ``replies_dir``
        to build the index, then persist it.
        """
        if self._index_file.exists():
            try:
                with open(self._index_file, "r") as f:
                    self._index = json.load(f)
                return
            except Exception:
                logger.warning("Failed to load author reactions index; rebuilding")

        self._full_scan()
        self.save()

    def save(self) -> None:
        """Persist the in-memory index to JSON."""
        self._state_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._index_file, "w") as f:
                json.dump(self._index, f, indent=2)
        except Exception:
            logger.warning("Failed to save author reactions index")

    # ------------------------------------------------------------------
    # Full scan (first run)
    # ------------------------------------------------------------------

    def _full_scan(self) -> None:
        """Scan all ``.md`` files under ``replies_dir`` to build the index."""
        self._index = {}
        if not self._replies_dir.is_dir():
            return

        for md_file in self._replies_dir.rglob("*.md"):
            self._index_file_metadata(str(md_file))

    # ------------------------------------------------------------------
    # Single-file metadata extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_like_of(filepath: str) -> str | None:
        """
        Read a Markdown file and return the ``like-of`` value, or
        ``None`` if it is not set.
        """
        try:
            with open(filepath, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    # Stop at the first heading (end of metadata block)
                    if line.startswith("# "):
                        break
                    m = _METADATA_RE.match(line)
                    if m and m.group(1) == "like-of":
                        return m.group(2).strip()
        except Exception:
            pass
        return None

    def _is_local_url(self, url: str) -> bool:
        """Check whether *url* is under ``base_url``."""
        return url.startswith(self._base_url + "/")

    def _source_url_for_file(self, filepath: str) -> str:
        """Convert a reply file path to its public ``/reply/…`` URL."""
        rel = os.path.relpath(filepath, self._replies_dir)
        stem = rel.rsplit(".", 1)[0]
        return f"/reply/{stem}"

    def _source_file_for_file(self, filepath: str) -> str:
        """Return the path relative to ``replies_dir``."""
        return os.path.relpath(filepath, self._replies_dir)

    def _index_file_metadata(self, filepath: str) -> None:
        """Parse a single file and add any local ``like-of`` to the index."""
        like_of = self._extract_like_of(filepath)
        if not like_of or not self._is_local_url(like_of):
            return

        source_file = self._source_file_for_file(filepath)
        entry = {
            "type": "like",
            "source_url": self._source_url_for_file(filepath),
            "source_file": source_file,
        }

        entries = self._index.setdefault(like_of, [])
        # Avoid duplicates (same source file)
        for existing in entries:
            if existing.get("source_file") == source_file:
                return
        entries.append(entry)

    def _remove_entries_for_file(self, filepath: str) -> None:
        """Remove all index entries whose source is *filepath*."""
        source_file = self._source_file_for_file(filepath)
        for target_url in list(self._index):
            self._index[target_url] = [
                e
                for e in self._index[target_url]
                if e.get("source_file") != source_file
            ]
            if not self._index[target_url]:
                del self._index[target_url]

    # ------------------------------------------------------------------
    # Monitor callback
    # ------------------------------------------------------------------

    def on_reply_change(
        self, change_type: ChangeType, filepath: str
    ) -> None:  # noqa: F821
        """
        Callback for the replies ``ContentMonitor``.

        On create/edit: re-index the file.  On delete: remove its entries.
        Always flushes to disk.
        """
        with self._lock:
            self._remove_entries_for_file(filepath)
            if change_type.value != "deleted":
                self._index_file_metadata(filepath)
            self.save()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_reactions(self, target_url: str) -> list[dict]:
        """
        Return author reactions targeting *target_url*.

        :param target_url: The full URL of the page to look up.
        :return: List of reaction dicts (each with ``type``,
            ``source_url``, and ``source_file``).
        """
        return self._index.get(target_url, [])
