from typing import Optional

from ..config import config


def get_webfinger_response(resource: str) -> Optional[dict]:
    base_url = config.link.rstrip("/")
    author = config.author or "blog"
    expected_resources = {
        f"acct:{author}@{base_url.split('://')[-1]}",
        f"{base_url}/activitypub/actor",
    }

    if resource not in expected_resources:
        return None

    return {
        "subject": f"acct:{author}@{base_url.split('://')[-1]}",
        "aliases": [
            f"{base_url}/activitypub/actor",
            base_url,
        ],
        "links": [
            {
                "rel": "self",
                "type": "application/activity+json",
                "href": f"{base_url}/activitypub/actor",
            },
            {
                "rel": "http://webfinger.net/rel/profile-page",
                "type": "text/html",
                "href": base_url,
            },
        ],
    }
