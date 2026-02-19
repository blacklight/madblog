from typing import Optional
from urllib.parse import urljoin

from ..config import config


def get_actor(username: Optional[str] = None) -> dict:
    base_url = config.link.rstrip("/")
    actor_username = username or config.author or "blog"
    actor_id = f"{base_url}/activitypub/actor"
    actor = {
        "@context": [
            "https://www.w3.org/ns/activitystreams",
            "https://w3id.org/security/v1",
        ],
        "type": "Person",
        "id": actor_id,
        "preferredUsername": actor_username,
        "name": config.title,
        "summary": config.description,
        "inbox": f"{base_url}/activitypub/inbox",
        "outbox": f"{base_url}/activitypub/outbox",
        "followers": f"{base_url}/activitypub/followers",
        "following": f"{base_url}/activitypub/following",
        "url": base_url,
        "manuallyApprovesFollowers": False,
        "discoverable": True,
        "published": "2024-01-01T00:00:00Z",
    }

    if config.logo:
        icon_url = urljoin(base_url, config.logo)
        actor["icon"] = {
            "type": "Image",
            "mediaType": "image/png",
            "url": icon_url,
        }
        actor["image"] = {
            "type": "Image",
            "mediaType": "image/png",
            "url": icon_url,
        }

    if config.author_photo:
        photo_url = urljoin(base_url, config.author_photo)
        actor["icon"] = {
            "type": "Image",
            "mediaType": "image/png",
            "url": photo_url,
        }

    return actor
