"""
Visibility model for author posts.

Defines visibility levels and resolution logic for articles and replies.
"""

from enum import Enum
from typing import Any

from madblog.config import config


class Visibility(str, Enum):
    """
    Visibility levels for posts.

    - PUBLIC: Visible on blog index, federated publicly.
    - UNLISTED: Not on index, listed on /unlisted, federated as unlisted.
    - FOLLOWERS: Not listed anywhere, federated to followers only.
    - DIRECT: Not listed anywhere, federated to mentioned actors only.
    - DRAFT: Not listed anywhere, not federated, accessible via direct URL.
    """

    PUBLIC = "public"
    UNLISTED = "unlisted"
    FOLLOWERS = "followers"
    DIRECT = "direct"
    DRAFT = "draft"

    @classmethod
    def from_str(cls, value: str) -> "Visibility":
        """
        Parse a visibility string, case-insensitive.

        :raises ValueError: If the value is not a valid visibility.
        """
        normalized = value.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"Invalid visibility: {value!r}")


def resolve_visibility(
    metadata: dict[str, Any],
    *,
    is_unlisted_reply: bool = False,
    default: Visibility | None = None,
) -> Visibility:
    """
    Resolve the effective visibility for a post.

    Resolution order:
    1. Explicit ``visibility`` in metadata
    2. Special case: unlisted replies (root replies without reply-to/like-of)
    3. Global ``default_visibility`` from config
    4. Fall back to PUBLIC

    :param metadata: Post metadata dict (may contain ``visibility`` key).
    :param is_unlisted_reply: True if this is a root reply without reply-to/like-of.
    :param default: Override for default visibility (uses config if None).
    :return: Resolved Visibility enum value.
    """
    # 1. Explicit visibility in metadata
    vis_str = metadata.get("visibility")
    if vis_str:
        try:
            return Visibility.from_str(vis_str)
        except ValueError:
            pass  # Invalid value, fall through to defaults

    # 2. Special case: unlisted replies default to UNLISTED
    if is_unlisted_reply:
        return Visibility.UNLISTED

    # 3. Config default or provided default
    if default is not None:
        return default

    try:
        return Visibility.from_str(config.default_visibility)
    except ValueError:
        pass  # Invalid config value, fall through

    # 4. Ultimate fallback
    return Visibility.PUBLIC
