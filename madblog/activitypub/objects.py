import datetime
from typing import Optional
from urllib.parse import urljoin

from ..config import config


def _format_datetime(dt: Optional[datetime.date | datetime.datetime]) -> str:
    if isinstance(dt, datetime.datetime):
        return dt.isoformat() + "Z" if dt.tzinfo is None else dt.isoformat()
    elif isinstance(dt, datetime.date):
        return datetime.datetime(dt.year, dt.month, dt.day).isoformat() + "Z"
    return datetime.datetime.now().isoformat() + "Z"


def article_to_note(page_metadata: dict, content: str = "") -> dict:
    base_url = config.link.rstrip("/")
    actor_id = f"{base_url}/activitypub/actor"
    article_uri = page_metadata.get("uri", "")
    article_url = urljoin(base_url, article_uri)

    note = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": "Note",
        "id": article_url,
        "attributedTo": actor_id,
        "content": content or page_metadata.get("description", ""),
        "published": _format_datetime(page_metadata.get("published")),
        "url": article_url,
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [f"{actor_id}/followers"],
    }

    if page_metadata.get("title"):
        note["name"] = page_metadata["title"]

    if page_metadata.get("description"):
        note["summary"] = page_metadata["description"]

    if page_metadata.get("image"):
        image_url = urljoin(base_url, page_metadata["image"])
        note["attachment"] = [
            {
                "type": "Image",
                "mediaType": "image/jpeg",
                "url": image_url,
            }
        ]

    return note


def create_activity(obj: dict) -> dict:
    base_url = config.link.rstrip("/")
    actor_id = f"{base_url}/activitypub/actor"

    activity = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": "Create",
        "id": f"{obj['id']}/activity",
        "actor": actor_id,
        "object": obj,
        "published": obj.get("published", datetime.datetime.now().isoformat() + "Z"),
        "to": obj.get("to", ["https://www.w3.org/ns/activitystreams#Public"]),
        "cc": obj.get("cc", [f"{actor_id}/followers"]),
    }

    return activity
