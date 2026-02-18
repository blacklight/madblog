from dataclasses import dataclass, field
from datetime import datetime


def _parse_link(data: dict) -> str:
    return (
        data.get("link")
        or next(
            iter(
                [
                    link
                    for link in data.get("links", [])
                    if link.get("rel") == "alternate"
                    and link.get("type") == "text/html"
                ]
            ),
            None,
        )
        or data.get("id", "")
    )


def _parse_links(data: dict) -> list["FeedLink"]:
    return [
        FeedLink(href=link["href"], rel=link["rel"], type=link["type"])
        for link in data.get("links", [])
    ]


def _parse_authors(data: dict) -> list["FeedAuthor"]:
    return [
        author
        for a in data.get(
            "authors",
            ([data["author_detail"]] if data.get("author_detail") else []),
        )
        if (author := FeedAuthor.build(a))
    ]


def _parse_dt(data: str | datetime | None) -> datetime | None:
    if not data:
        return None
    if isinstance(data, datetime):
        return data

    import email.utils
    import re
    from datetime import timezone

    # Normalize common timezone abbreviations to numeric offsets
    _tz_abbr = {
        "GMT": "+0000",
        "UTC": "+0000",
        "EST": "-0500",
        "EDT": "-0400",
        "CST": "-0600",
        "CDT": "-0500",
        "MST": "-0700",
        "MDT": "-0600",
        "PST": "-0800",
        "PDT": "-0700",
    }

    # 1. Try ISO 8601 first (covers most Atom feeds)
    try:
        return datetime.fromisoformat(data)
    except ValueError:
        pass

    # 2. Try email.utils.parsedate_to_datetime (handles RFC 2822 / RSS dates
    #    including timezone abbreviations like GMT)
    try:
        return email.utils.parsedate_to_datetime(data)
    except (ValueError, TypeError):
        pass

    # 3. Replace known tz abbreviations and retry strptime
    normalized = data.strip()
    for abbr, offset in _tz_abbr.items():
        if normalized.endswith(abbr):
            normalized = normalized[: -len(abbr)].rstrip() + " " + offset
            break

    _formats = [
        "%a, %d %b %Y %H:%M:%S %z",  # RFC 822
        "%d %b %Y %H:%M:%S %z",  # without weekday
        "%Y-%m-%dT%H:%M:%S%z",  # ISO without separators in tz
        "%Y-%m-%d %H:%M:%S",  # naive datetime
        "%Y-%m-%d",  # date only
    ]

    for fmt in _formats:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue

    # 4. Last resort: strip any trailing non-numeric tz and parse as UTC
    stripped = re.sub(r"\s+[A-Z]{1,5}$", "", data.strip())
    for fmt in _formats:
        try:
            dt = datetime.strptime(stripped, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


@dataclass
class FeedLink:
    """
    A link to a feed
    """

    href: str
    rel: str
    type: str


@dataclass
class FeedAuthor:
    """
    A feed author
    """

    name: str
    email: str
    uri: str

    @classmethod
    def build(cls, data: dict):
        ret = cls(
            name=data.get("name", ""),
            email=data.get("email", ""),
            uri=data.get("href", ""),
        )

        if not (ret.name or ret.email or ret.uri):
            return None

        return ret


@dataclass
class FeedEntry:
    """
    Feed entry model
    """

    title: str
    link: str
    content: str = ""
    description: str | None = None
    published: datetime | None = None
    authors: list[FeedAuthor] = field(default_factory=list)
    enclosure: str | None = None
    links: list[FeedLink] = field(default_factory=list)
    updated: datetime | None = None
    feed: Feed | None = None

    @classmethod
    def build(cls, data: dict):
        return cls(
            title=data.get("title", ""),
            link=_parse_link(data),
            content=next(
                iter(
                    [
                        item
                        for item in (data.get("content") or [{}])
                        if (item.get("type") or "") == "text/html"
                    ]
                ),
                {},
            ).get("value", ""),
            description=(
                data.get("summary") or data.get("summary_detail", {}).get("value")
            ),
            published=_parse_dt(data.get("published")),
            authors=_parse_authors(data),
            enclosure=next(
                iter(
                    [
                        href
                        for link in data.get("links", [])
                        if link.get("rel") == "enclosure" and (href := link.get("href"))
                    ]
                ),
                None,
            ),
            links=_parse_links(data),
            updated=_parse_dt(data.get("updated")),
        )


@dataclass
class Feed:
    """
    Feed model
    """

    title: str
    link: str
    href: str
    description: str | None = None
    language: str | None = None
    logo: str | None = None
    links: list[FeedLink] = field(default_factory=list)
    authors: list[FeedAuthor] = field(default_factory=list)
    entries: list[FeedEntry] = field(default_factory=list)
    updated: datetime | None = None
    last_fetched: datetime | None = None

    @classmethod
    def build(cls, data: dict):
        feed = data.get("feed", {})
        feed_obj = cls(
            title=feed.get("title", ""),
            link=_parse_link(data),
            href=data.get("href", ""),
            description=(
                feed.get("subtitle")
                or feed.get("description")
                or feed.get("subtitle_detail", {}).get("value")
            ),
            language=feed.get("language"),
            logo=feed.get("logo"),
            links=_parse_links(data),
            authors=_parse_authors(feed),
            entries=[FeedEntry.build(entry) for entry in data.get("entries", [])],
            updated=_parse_dt(feed.get("updated")),
        )

        for entry in feed_obj.entries:
            entry.feed = feed_obj

        return feed_obj
