import os
import re
from typing import Optional
from urllib.parse import urljoin

from flask import (
    jsonify,
    request,
    Response,
    send_from_directory as send_from_directory_,
    render_template,
)

from .app import app
from .config import config
from ._sorters import PagesSortByTimeGroupedByFolder


def send_from_directory(
    path: str, file: str, alternative_path: Optional[str] = None, *args, **kwargs
):
    if not os.path.exists(os.path.join(path, file)) and alternative_path:
        path = alternative_path
    return send_from_directory_(path, file, *args, **kwargs)


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


@app.route("/rss", methods=["GET"])
def rss_route():
    short_description = "short" in request.args or config.short_feed
    pages = app.get_pages(
        with_content=not short_description,
        skip_header=True,
        skip_html_head=True,
    )

    return Response(
        """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
    <channel>
        <title>{title}</title>
        <link>{link}</link>
        <description>{description}</description>
        <category>{categories}</category>
        <image>
            <url>{link}/img/icon.png</url>
            <title>{title}</title>
            <link>{link}</link>
        </image>
        <pubDate>{last_pub_date}</pubDate>
        <language>{language}</language>

        {items}
    </channel>
</rss>""".format(
            title=config.title,
            description=config.description,
            link=config.link,
            categories=",".join(config.categories),
            language=config.language,
            last_pub_date=(
                pages[0][1]["published"].strftime("%a, %d %b %Y %H:%M:%S GMT")
                if pages
                else ""
            ),
            items="\n\n".join(
                [
                    (
                        """
            <item>
                <title>{title}</title>
                <link>{base_link}{link}</link>
                <pubDate>{published}</pubDate>
                <description><![CDATA[{content}]]></description>
                <media:content medium="image" url="{image}" width="200" height="150" />
            </item>
                    """
                    ).format(
                        base_link=config.link,
                        title=page.get("title", "[No Title]"),
                        link=page.get("uri", ""),
                        published=(
                            page["published"].strftime("%a, %d %b %Y %H:%M:%S GMT")
                            if "published" in page
                            else ""
                        ),
                        content=(
                            page.get("description", "")
                            if short_description
                            else page.get("content", "")
                        ),
                        image=(
                            urljoin(config.link, page["image"])
                            if page.get("image")
                            and not re.search(r"^https?://", page["image"])
                            else page.get("image", "")
                        ),
                    )
                    for _, page in pages
                ]
            ),
        ),
        mimetype="application/xml",
    )


# vim:sw=4:ts=4:et:
