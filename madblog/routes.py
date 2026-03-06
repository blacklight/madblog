import logging
import datetime
import email.utils
import mimetypes
import os
import re
from typing import Optional
from urllib.parse import urljoin

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
    )


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


# vim:sw=4:ts=4:et:
