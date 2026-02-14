import logging
import datetime
import os
import re
from typing import Optional
from urllib.parse import urljoin

from feedgen.feed import FeedGenerator
from flask import (
    jsonify,
    request,
    Response,
    redirect,
    send_from_directory as send_from_directory_,
    render_template,
)

from .app import app
from .config import config
from ._sorters import PagesSortByTimeGroupedByFolder

logger = logging.getLogger(__name__)


def send_from_directory(
    path: str, file: str, alternative_path: Optional[str] = None, **kwargs
):
    if not os.path.exists(os.path.join(path, file)) and alternative_path:
        path = alternative_path
    return send_from_directory_(path, file, **kwargs)


@app.route("/", methods=["GET"])
def home_route():
    return render_template(
        "index.html",
        pages=app.get_pages(sorter=PagesSortByTimeGroupedByFolder),
        config=config,
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


@app.route("/article/<article>", methods=["GET"])
def article_route(article: str):
    return article_with_path_route("", article)


def _get_absolute_url(url: str) -> str:
    if not url:
        return ""

    if re.search(r"^https?://", url):
        return url

    return urljoin(config.link, url)


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
        return datetime.datetime(dt.year, dt.month, dt.day, tzinfo=datetime.timezone.utc)

    return None


@app.route("/feed", methods=["GET"])
def feed_route():
    feed_type = request.args.get("type", "rss").lower().strip()
    if feed_type not in {"rss", "atom"}:
        return Response("Invalid feed type", status=400, mimetype="text/plain")

    short_description = "short" in request.args or config.short_feed
    pages = app.get_pages(
        with_content=not short_description,
        skip_header=True,
        skip_html_head=True,
    )

    pages = pages[: config.max_entries_per_feed]

    fg = FeedGenerator()
    fg.id(config.link)
    fg.title(config.title)
    fg.link(href=config.link, rel="alternate")
    fg.description(config.description)
    fg.language(config.language)

    for category in config.categories:
        fg.category(term=category)

    icon_url = _get_absolute_url("/img/icon.png")
    if icon_url:
        fg.logo(icon_url)

    self_url = _get_absolute_url(f"/feed?type={feed_type}")
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
            fe.link(href=entry_url)

        fe.title(page.get("title", "[No Title]"))

        published = _to_feed_datetime(page.get("published"))
        if published:
            fe.published(published)
            fe.updated(published)

        if page.get("description"):
            fe.summary(page.get("description", ""))

        if not short_description:
            fe.content(page.get("content", ""), type="html")

        image_url = _get_absolute_url(page.get("image", ""))
        if image_url:
            fe.link(href=image_url, rel="enclosure")

    if feed_type == "atom":
        return Response(fg.atom_str(pretty=True), mimetype="application/atom+xml")

    return Response(fg.rss_str(pretty=True), mimetype="application/rss+xml")


@app.route("/rss", methods=["GET"])
def rss_route():
    """
    This route exists only for backward compatibility.

    It redirects to the /feed route with the appropriate query parameter to generate an RSS feed.
    """
    qs = request.query_string.decode("utf-8")
    if qs:
        return redirect(f"/feed?type=rss&{qs}")
    return redirect("/feed?type=rss")


# vim:sw=4:ts=4:et:
