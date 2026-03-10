import logging
import datetime
import email.utils
import mimetypes
import os
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from feedgen.feed import FeedGenerator
from flask import (
    Request,
    jsonify,
    request,
    Response,
    send_from_directory as send_from_directory_,
)

from .app import app
from .config import config
from .feeds import FeedAuthor
from ._sorters import PagesSortByTimeGroupedByFolder

logger = logging.getLogger(__name__)
_author_with_email_regex = re.compile(
    r"(.*)\s+<([\w\.\-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)>"
)
_author_with_url_regex = re.compile(r"(.*)\s+<(https?:\/\/[\w\.\-]+\.[a-z]{2,6}\/?)>")


def send_from_directory(
    path: str, file: str, alternative_path: Optional[str] = None, **kwargs
):
    if not os.path.exists(os.path.join(path, file)) and alternative_path:
        path = alternative_path
    return send_from_directory_(path, file, **kwargs)


def _get_followers_count() -> int:
    """Get the number of ActivityPub followers, or 0 if AP is disabled."""
    if not config.enable_activitypub:
        return 0
    if not hasattr(app, "activitypub_storage"):
        return 0
    try:
        return len(app.activitypub_storage.get_followers())
    except Exception:
        return 0


@app.route("/", methods=["GET"])
def home_route():
    view_mode = request.args.get("view", config.view_mode)
    if view_mode not in ("cards", "list", "full"):
        view_mode = config.view_mode

    return app.get_pages_response(
        sorter=PagesSortByTimeGroupedByFolder,
        with_content=(view_mode == "full"),
        skip_header=True,
        skip_html_head=True,
        template_name="index.html",
        view_mode=view_mode,
        followers_count=_get_followers_count(),
    )


@app.route("/@<username>", methods=["GET"])
def profile_redirect(username: str):
    """Redirect /@username to the homepage (actor profile URL)."""
    from flask import redirect

    if config.enable_activitypub and username == config.activitypub_username:
        return redirect("/", code=302)
    return Response("Not found", status=404, mimetype="text/plain")


@app.route("/img/<img>", methods=["GET"])
def img_route(img: str):
    return send_from_directory(app.img_dir, img, config.default_img_dir)


@app.route("/favicon.ico", methods=["GET"])
def favicon_route():
    return img_route("favicon.ico")


@app.route("/js/<file>", methods=["GET"])
def js_route(file: str):
    return send_from_directory(app.js_dir, file, config.default_js_dir)


@app.route("/pwabuilder-sw.js", methods=["GET"])
def pwa_builder_route():
    return send_from_directory(app.js_dir, "pwabuilder-sw.js", config.default_js_dir)


@app.route("/pwabuilder-sw-register.js", methods=["GET"])
def pwa_builder_register_route():
    return send_from_directory(
        app.js_dir, "pwabuilder-sw-register.js", config.default_js_dir
    )


@app.route("/css/<style>", methods=["GET"])
def css_route(style: str):
    return send_from_directory(app.css_dir, style, config.default_css_dir)


@app.route("/fonts/<file>", methods=["GET"])
def fonts_route(file: str):
    return send_from_directory(app.fonts_dir, file, config.default_fonts_dir)


@app.route("/manifest.json", methods=["GET"])
def manifest_route():
    # If there is a manifest.json in the content directory, use it
    manifest_file = os.path.join(config.content_dir, "manifest.json")
    if os.path.isfile(manifest_file):
        return send_from_directory(config.content_dir, "manifest.json")

    # Otherwise, generate a default manifest.json
    return jsonify(
        {
            "name": config.title,
            "short_name": config.title,
            "icons": [
                {"src": "/img/icon-48.png", "sizes": "48x48", "type": "image/png"},
                {"src": "/img/icon-72.png", "sizes": "72x72", "type": "image/png"},
                {"src": "/img/icon-96.png", "sizes": "96x96", "type": "image/png"},
                {"src": "/img/icon-144.png", "sizes": "144x144", "type": "image/png"},
                {"src": "/img/icon-168.png", "sizes": "168x168", "type": "image/png"},
                {"src": "/img/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/img/icon-256.png", "sizes": "256x256", "type": "image/png"},
                {"src": "/img/icon-512.png", "sizes": "512x512", "type": "image/png"},
            ],
            "gcm_sender_id": "",
            "gcm_user_visible_only": True,
            "start_url": "/",
            "permissions": ["gcm"],
            "scope": "",
            "orientation": "portrait",
            "display": "standalone",
            "theme_color": "#000000",
            "background_color": "#ffffff",
        }
    )


@app.route("/article/<path:path>/<article>", methods=["GET"])
def article_with_path_route(path: str, article: str):
    return app.get_page(os.path.join(path, article))


@app.route("/article/<path:path>/<article>.md", methods=["GET"])
def raw_article_with_path_route(path: str, article: str):
    return app.get_page(os.path.join(path, article), as_markdown=True)


@app.route("/article/<article>", methods=["GET"])
def article_route(article: str):
    return article_with_path_route("", article)


@app.route("/article/<article>.md", methods=["GET"])
def raw_article_route(article: str):
    return raw_article_with_path_route("", article)


def _get_absolute_url(url: str) -> str:
    if not url:
        return ""

    if re.search(r"^https?://", url):
        return url

    return urljoin(config.link or request.host, url)


def _to_feed_datetime(dt: object) -> Optional[datetime.datetime]:
    if not dt:
        return None

    if isinstance(dt, datetime.datetime):
        return (
            dt.replace(tzinfo=datetime.timezone.utc)
            if dt.tzinfo is None
            else dt.astimezone(datetime.timezone.utc)
        )

    if isinstance(dt, datetime.date):
        return datetime.datetime(
            dt.year, dt.month, dt.day, tzinfo=datetime.timezone.utc
        )

    return None


def _to_feed_text(obj: object) -> str:
    if obj is None:
        return ""

    if isinstance(obj, Response):
        return obj.get_data(as_text=True)

    return str(obj)


def _parse_author_info(author: str | FeedAuthor | None, author_url: str | None) -> dict:
    ret = {}
    if isinstance(author, FeedAuthor):
        return {
            "name": author.name,
            "email": author.email,
            "uri": author.uri,
        }

    if author_url:
        if author_url.startswith("mailto:"):
            ret["email"] = author_url[len("mailto:") :]
        else:
            ret["uri"] = author_url

    if author:
        if author.startswith("mailto:"):
            ret["email"] = author[len("mailto:") :]
        elif m := _author_with_email_regex.match(author):
            ret["name"] = m[1]
            ret["email"] = m[2]
        elif m := _author_with_url_regex.match(author):
            ret["name"] = m[1]
            ret["uri"] = m[2]
        else:
            ret["name"] = author

    return ret


def _get_feed(request: Request, feed_type: Optional[str] = None):
    if not feed_type:
        feed_type = request.args.get("type", "rss")

    feed_type = feed_type.lower().strip()
    if feed_type not in {"rss", "atom"}:
        return Response("Invalid feed type", status=400, mimetype="text/plain")

    limit = request.args.get("limit") or config.max_entries_per_feed
    if limit:
        limit = int(limit)

    short_description = "short" in request.args or config.short_feed

    # Get pages data first (includes file_mtime for cache headers)
    pages = app.get_pages(
        with_content=not short_description,
        skip_header=True,
        skip_html_head=True,
    )

    pages = pages[:limit]

    most_recent_mtime = 0.0
    for _, page_data in pages:
        # Only consider local files (those with file_mtime), not external feeds
        if "file_mtime" in page_data:
            most_recent_mtime = max(most_recent_mtime, page_data["file_mtime"])

    # Format the most recent modification time for HTTP headers
    last_modified = (
        email.utils.formatdate(most_recent_mtime, usegmt=True)
        if most_recent_mtime > 0
        else None
    )

    # Generate ETag based on most recent modification time
    etag = app._generate_etag(most_recent_mtime) if most_recent_mtime > 0 else None

    # Check if the client has a cached version that's still valid
    # Check both If-Modified-Since and If-None-Match headers
    cache_valid = False

    if last_modified and most_recent_mtime > 0:
        if_modified_since = request.headers.get("If-Modified-Since")
        if_none_match = request.headers.get("If-None-Match")

        # Check If-Modified-Since
        if if_modified_since and not cache_valid:
            try:
                cached_timestamp = email.utils.mktime_tz(
                    email.utils.parsedate_tz(if_modified_since)  # type: ignore
                )
                if (
                    cached_timestamp is not None
                    and cached_timestamp >= most_recent_mtime
                ):
                    cache_valid = True
            except (ValueError, TypeError, OverflowError):
                # Invalid If-Modified-Since header, ignore it
                pass

        # Check If-None-Match (ETag)
        if if_none_match and etag and not cache_valid:
            client_etags = [tag.strip() for tag in if_none_match.split(",")]
            if etag in client_etags or "*" in client_etags:
                cache_valid = True

        # Return 304 if cache is valid
        if cache_valid:
            from flask import make_response

            response = make_response("", 304)
            response.headers["Last-Modified"] = last_modified
            if etag:
                response.headers["ETag"] = etag

            # Set Language header for 304 responses too
            if config.language:
                response.headers["Language"] = config.language

            return response

    fg = FeedGenerator()
    fg.id(config.link)
    fg.title(config.title)
    fg.link(href=config.link, rel="alternate")
    fg.description(config.description)
    fg.language(config.language)

    fg.author(
        **_parse_author_info(author=config.author, author_url=config.author_url),
    )

    for category in config.categories:
        fg.category(term=category)

    icon_url = _get_absolute_url(config.logo or "/img/icon.png")
    if icon_url:
        fg.logo(icon_url)

    self_url = _get_absolute_url(f"/feed.{feed_type}")
    fg.link(href=self_url, rel="self")

    if pages:
        updated = _to_feed_datetime(pages[0][1].get("published"))
        if updated:
            fg.updated(updated)

    for _, page in pages:
        uri = page.get("uri", "")
        entry_url = _get_absolute_url(uri)

        fe = fg.add_entry()
        if entry_url:
            fe.id(entry_url)
            fe.link(href=entry_url, rel="alternate")

        fe.title(_to_feed_text(page.get("title", "[No Title]")))

        published = _to_feed_datetime(page.get("published"))
        if published:
            fe.published(published)
            fe.updated(published)

        if page.get("description"):
            fe.summary(_to_feed_text(page.get("description", "")))

        if not short_description:
            fe.content(_to_feed_text(page.get("content", "")), type="html")

        fe.author(
            **_parse_author_info(
                author=page.get("author"), author_url=page.get("author_url")
            ),
        )

        image_url = _get_absolute_url(page.get("image", ""))
        if image_url:
            mime_type, _ = mimetypes.guess_type(image_url)
            if mime_type:
                fe.enclosure(image_url, 0, mime_type)

    # Create response with appropriate content type
    response = (
        Response(fg.atom_str(pretty=True), mimetype="application/atom+xml")
        if feed_type == "atom"
        else Response(fg.rss_str(pretty=True), mimetype="application/rss+xml")
    )

    # Add cache headers
    if last_modified:
        response.headers["Last-Modified"] = last_modified
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

    if etag:
        response.headers["ETag"] = etag

    # Set Language header from global config for feeds
    if config.language:
        response.headers["Language"] = config.language

    return response


@app.route("/feed.<type>", methods=["GET"])
def feed_route(type: str):
    return _get_feed(request, type)


@app.route("/rss", methods=["GET"])
def rss_route():
    """
    This route exists only for backward compatibility.

    It redirects to the /feed route with the appropriate query parameter to generate an RSS feed.
    """
    return _get_feed(request, "rss")


@app.route("/tags", methods=["GET"])
def tags_route():
    from flask import make_response, render_template

    tags = app.tag_index.get_all_tags()
    response = make_response(render_template("tags.html", tags=tags, config=config))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/tags/<tag>", methods=["GET"])
def tag_posts_route(tag: str):
    from flask import make_response, render_template

    from .tags import normalize_tag as _normalize_tag

    canonical = _normalize_tag(tag)
    posts = app.tag_index.get_posts_for_tag(canonical)
    response = make_response(
        render_template(
            "tag_posts.html",
            tag=canonical,
            posts=posts,
            config=config,
        )
    )
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Mastodon-compatible API — Madblog-specific endpoints
# ---------------------------------------------------------------------------


@app.route("/api/v1/tags/<tag>", methods=["GET"])
def mastodon_tag_route(tag: str):
    """Return a Mastodon Tag entity with usage history from the TagIndex."""
    from .tags import normalize_tag as _normalize_tag

    canonical = _normalize_tag(tag)
    posts = app.tag_index.get_posts_for_tag(canonical)

    if not posts:
        return jsonify({"error": "Record not found"}), 404

    # Build per-day usage history (last 7 days)
    from collections import Counter

    today = datetime.date.today()
    day_counts: Counter = Counter()
    for post in posts:
        pub = post.get("published", "")
        if not pub:
            continue
        try:
            pub_date = datetime.date.fromisoformat(str(pub)[:10])
        except (ValueError, TypeError):
            continue
        day_counts[pub_date] += 1

    history = []
    for i in range(7):
        day = today - datetime.timedelta(days=i)
        count = day_counts.get(day, 0)
        history.append(
            {
                "day": str(
                    int(
                        datetime.datetime.combine(
                            day, datetime.time.min, tzinfo=datetime.timezone.utc
                        ).timestamp()
                    )
                ),
                "uses": str(count),
                "accounts": str(min(count, 1)),
            }
        )

    base_url = (config.link or "").rstrip("/")
    return jsonify(
        {
            "name": canonical,
            "url": f"{base_url}/tags/{canonical}",
            "history": history,
            "following": False,
        }
    )


@app.route("/api/v2/search", methods=["GET"])
def mastodon_search_route():
    """Mastodon-compatible search endpoint (read-only, local data only)."""
    q = (request.args.get("q") or "").strip()
    search_type = request.args.get("type", "")
    limit = min(int(request.args.get("limit", 20)), 40)

    if not q:
        return jsonify({"accounts": [], "statuses": [], "hashtags": []})

    accounts = []
    statuses = []
    hashtags = []

    q_lower = q.lower()

    # -- accounts --
    if not search_type or search_type == "accounts":
        if config.enable_activitypub and hasattr(app, "activitypub_handler"):
            from pubby.server.mastodon import actor_to_account

            username = config.activitypub_username.lower()
            name = (
                config.activitypub_name or config.author or config.title or ""
            ).lower()
            if q_lower in username or q_lower in name:
                accounts.append(actor_to_account(app.activitypub_handler))

    # -- hashtags --
    if not search_type or search_type == "hashtags":
        from .tags import normalize_tag as _normalize_tag

        all_tags = app.tag_index.get_all_tags()
        prefix = _normalize_tag(q)
        for tag_name, _count in all_tags:
            if tag_name.startswith(prefix):
                base_url = (config.link or "").rstrip("/")
                hashtags.append(
                    {
                        "name": tag_name,
                        "url": f"{base_url}/tags/{tag_name}",
                        "history": [],
                    }
                )
            if len(hashtags) >= limit:
                break

    # -- statuses --
    if not search_type or search_type == "statuses":
        if config.enable_activitypub and hasattr(app, "activitypub_handler"):
            from pubby.server.mastodon import activity_to_status, actor_to_account

            handler = app.activitypub_handler
            account = actor_to_account(handler)
            activities = handler.storage.get_activities(limit=10000, offset=0)
            for act in activities:
                obj = act.get("object", {})
                if isinstance(obj, dict):
                    content = (obj.get("content") or "").lower()
                    name = (obj.get("name") or "").lower()
                    if q_lower in content or q_lower in name:
                        statuses.append(
                            activity_to_status(act, handler, account=account)
                        )
                if len(statuses) >= limit:
                    break

    return jsonify(
        {
            "accounts": accounts[:limit],
            "statuses": statuses[:limit],
            "hashtags": hashtags[:limit],
        }
    )


@app.route("/guestbook", methods=["GET"])
def guestbook_route():
    from flask import make_response, render_template

    if not config.enable_guestbook:
        return Response("Guestbook is not enabled", status=404, mimetype="text/plain")

    webmentions_html = ""
    ap_interactions_html = ""

    if config.enable_webmentions:
        webmentions_html = app.get_rendered_guestbook_webmentions()

    if config.enable_activitypub:
        ap_interactions_html = app.get_rendered_guestbook_ap_interactions()

    response = make_response(
        render_template(
            "guestbook.html",
            config=config,
            webmentions=webmentions_html,
            ap_interactions=ap_interactions_html,
        )
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/followers", methods=["GET"])
def followers_route():
    from flask import make_response, render_template

    if not config.enable_activitypub:
        return Response("ActivityPub is not enabled", status=404, mimetype="text/plain")

    followers = []
    if hasattr(app, "activitypub_storage"):
        try:
            raw_followers = app.activitypub_storage.get_followers()
            for f in raw_followers:
                actor_data = f.actor_data or {}
                followers.append(
                    {
                        "actor_id": f.actor_id,
                        "name": actor_data.get("name")
                        or actor_data.get("preferredUsername")
                        or f.actor_id,
                        "username": actor_data.get("preferredUsername", ""),
                        "url": actor_data.get("url") or f.actor_id,
                        "host": urlparse(actor_data.get("url") or f.actor_id).netloc,
                        "icon": (
                            actor_data.get("icon", {}).get("url")
                            if isinstance(actor_data.get("icon"), dict)
                            else actor_data.get("icon")
                        ),
                        "summary": actor_data.get("summary", ""),
                        "followed_at": f.followed_at,
                    }
                )
            followers.sort(key=lambda x: x.get("followed_at") or "", reverse=True)
        except Exception:
            logger.exception("Failed to get followers")

    response = make_response(
        render_template(
            "followers.html",
            followers=followers,
            config=config,
        )
    )
    response.headers["Cache-Control"] = "no-store"
    return response


# vim:sw=4:ts=4:et:
