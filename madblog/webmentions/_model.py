from dataclasses import dataclass
from enum import Enum


class WebmentionDirection(str, Enum):
    """
    Enum representing the direction of a Webmention
    (incoming or outgoing).
    """

    IN = "incoming"
    OUT = "outgoing"


class WebmentionType(str, Enum):
    """
    Enum representing the type of a Webmention.

    Note that this list is not exhaustive, and the
    Webmention recommendation itself does not provide
    any static list.

    This is however a lis of commonly supported types
    in Microformats.
    """

    UNKNOWN = "unknown"
    MENTION = "mention"
    REPLY = "reply"
    LIKE = "like"
    REPOST = "repost"
    BOOKMARK = "bookmark"
    RSVP = "rsvp"
    FOLLOW = "follow"

    @classmethod
    def from_raw(cls, raw: str | None) -> "WebmentionType":
        if not raw:
            return cls.UNKNOWN

        normalized = raw.strip().lower()
        aliases = {
            "in-reply-to": cls.REPLY,
            "reply": cls.REPLY,
            "like-of": cls.LIKE,
            "like": cls.LIKE,
            "repost-of": cls.REPOST,
            "repost": cls.REPOST,
            "bookmark-of": cls.BOOKMARK,
            "bookmark": cls.BOOKMARK,
            "rsvp": cls.RSVP,
            "follow-of": cls.FOLLOW,
            "follow": cls.FOLLOW,
            "mention": cls.MENTION,
        }

        return aliases.get(normalized, cls.UNKNOWN)


@dataclass
class Webmention:
    """
    Data class representing a Webmention.
    """

    source: str
    target: str
    direction: WebmentionDirection
    title: str | None = None
    excerpt: str | None = None
    content: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    author_photo: str | None = None
    published: str | None = None
    mention_type: WebmentionType = WebmentionType.UNKNOWN
    mention_type_raw: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __hash__(self):
        """
        :return: A hash value based on the source, target, and direction.
        """
        return hash((self.source, self.target, self.direction))
