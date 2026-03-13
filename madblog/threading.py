"""
Threading model for interleaving reactions (Webmentions, AP interactions)
with author replies.
"""

import datetime
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional


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

    # Create nodes for webmentions
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

    # Create nodes for AP interactions
    for interaction in ap_interactions:
        identity = _get_ap_interaction_identity(interaction)
        if not identity:
            continue

        published = _to_datetime(
            getattr(interaction, "published", None)
            or getattr(interaction, "created_at", None)
        )

        nodes[identity] = ThreadNode(
            item=interaction,
            reaction_type=ReactionType.AP_INTERACTION,
            identity=identity,
            reply_to=_get_ap_interaction_reply_to(interaction),
            published=published,
        )

    # Create nodes for author replies
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

        # When activitypub_link differs from link the AP target URL uses a
        # different origin; register the node under that alias too so that
        # AP interactions can find their parent.
        ap_alias = reply.get("ap_full_url")
        if ap_alias and ap_alias != identity:
            nodes[ap_alias] = node

    # Build the tree by linking children to parents.
    # Deduplicate: aliases point to the same ThreadNode object so we must
    # process each node only once.
    roots: List[ThreadNode] = []
    seen: set[int] = set()

    for node in nodes.values():
        node_id = id(node)
        if node_id in seen:
            continue
        seen.add(node_id)

        parent_id = node.reply_to

        # If reply_to is the article URL, treat as a root
        if parent_id == article_url or not parent_id:
            roots.append(node)
        elif parent_id in nodes:
            # Link to parent node
            nodes[parent_id].children.append(node)
        else:
            # Parent not found (e.g. reply to a deleted reaction) - treat as root
            roots.append(node)

    # Sort roots by published DESC (newest first)
    _EPOCH = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    roots.sort(key=lambda n: n.published or _EPOCH, reverse=True)

    # Sort children by published ASC (oldest first, for natural conversation flow)
    for node in nodes.values():
        node.children.sort(key=lambda n: n.published or _EPOCH)

    return roots


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

        if node.reaction_type == ReactionType.WEBMENTION:
            counts["webmentions"] += 1
            mt = getattr(node.item, "mention_type", None)
            type_val = mt.value if hasattr(mt, "value") else str(mt) if mt else ""
        elif node.reaction_type == ReactionType.AP_INTERACTION:
            it = getattr(node.item, "interaction_type", None)
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
