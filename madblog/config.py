import os
import re
from argparse import Namespace
from dataclasses import dataclass, field
from typing import List, Optional

import yaml


@dataclass
class Config:
    """
    Configuration for the blog
    """

    title: str = "Blog"
    description: str = ""
    link: str = "/"
    home_link: str = "/"
    external_links: List[str] = field(default_factory=list)
    host: str = "0.0.0.0"
    port: int = 8000
    language: str = "en-US"
    logo: str = "/img/icon.png"
    header: bool = True
    content_dir: str = "."
    categories: List[str] = field(default_factory=list)
    short_feed: bool = False
    enable_webmentions: bool = True
    webmentions_hard_delete: bool = False
    debug: bool = False
    basedir = os.path.abspath(os.path.dirname(__file__))
    author: str | None = None
    author_url: str | None = None
    author_photo: str | None = None

    @property
    def templates_dir(self) -> str:
        return os.path.join(self.basedir, "templates")

    @property
    def static_dir(self) -> str:
        return os.path.join(self.basedir, "static")

    @property
    def default_css_dir(self) -> str:
        return os.path.join(self.static_dir, "css")

    @property
    def default_js_dir(self) -> str:
        return os.path.join(self.static_dir, "js")

    @property
    def default_fonts_dir(self) -> str:
        return os.path.join(self.static_dir, "fonts")

    @property
    def default_img_dir(self) -> str:
        return os.path.join(self.static_dir, "img")

    @property
    def webmention_url(self) -> Optional[str]:
        from flask import url_for

        webmention_url = None
        if config.enable_webmentions:
            webmention_url = (
                f'{config.link.rstrip("/")}/webmentions'
                if re.match(r"^https?://", config.link)
                else url_for("webmention_listener_route", _external=True)
            )

        return webmention_url


config = Config()


def _init_config_from_file(config_file: str):
    cfg = {}

    if os.path.isfile(config_file):
        with open(config_file, "r") as f:
            cfg = yaml.safe_load(f) or {}

    if cfg.get("content_dir"):
        config.content_dir = cfg["content_dir"]
    if cfg.get("title"):
        config.title = cfg["title"]
    if cfg.get("description"):
        config.description = cfg["description"]
    if cfg.get("link"):
        config.link = cfg["link"]
    if cfg.get("home_link"):
        config.home_link = cfg["home_link"]
    if cfg.get("external_links"):
        config.external_links = cfg["external_links"]
    if cfg.get("host"):
        config.host = cfg["host"]
    if cfg.get("port"):
        config.port = int(cfg["port"])
    if cfg.get("logo") is not None:
        config.logo = cfg["logo"]
    if cfg.get("language"):
        config.language = cfg["language"]
    if cfg.get("header"):
        config.header = bool(cfg["header"])
    if cfg.get("short_feed"):
        config.short_feed = bool(cfg["short_feed"])
    if cfg.get("enable_webmentions") is not None:
        config.enable_webmentions = bool(cfg["enable_webmentions"])
    if cfg.get("webmentions_hard_delete") is not None:
        config.webmentions_hard_delete = bool(cfg["webmentions_hard_delete"])
    if cfg.get("debug") is not None:
        config.debug = bool(cfg["debug"])
    if cfg.get("author"):
        config.author = cfg["author"]
    if cfg.get("author_url"):
        config.author_url = cfg["author_url"]
    if cfg.get("author_photo"):
        config.author_photo = cfg["author_photo"]

    config.categories = cfg.get("categories", [])


def _init_config_from_env():
    if os.getenv("MADBLOG_TITLE"):
        config.title = os.environ["MADBLOG_TITLE"]
    if os.getenv("MADBLOG_DESCRIPTION"):
        config.description = os.environ["MADBLOG_DESCRIPTION"]
    if os.getenv("MADBLOG_LINK"):
        config.link = os.environ["MADBLOG_LINK"]
    if os.getenv("MADBLOG_HOME_LINK"):
        config.home_link = os.environ["MADBLOG_HOME_LINK"]
    if os.getenv("MADBLOG_EXTERNAL_LINKS"):
        config.external_links = re.split(
            r"[,\s]+", os.environ["MADBLOG_EXTERNAL_LINKS"].strip()
        )
    if os.getenv("MADBLOG_HOST"):
        config.host = os.environ["MADBLOG_HOST"]
    if os.getenv("MADBLOG_PORT"):
        config.port = int(os.environ["MADBLOG_PORT"])
    if os.getenv("MADBLOG_CONTENT_DIR"):
        config.content_dir = os.environ["MADBLOG_CONTENT_DIR"]
    if os.getenv("MADBLOG_LOGO"):
        config.logo = os.environ["MADBLOG_LOGO"]
    if os.getenv("MADBLOG_LANGUAGE"):
        config.language = os.environ["MADBLOG_LANGUAGE"]
    if os.getenv("MADBLOG_HEADER"):
        config.header = os.environ["MADBLOG_HEADER"] == "1"
    if os.getenv("MADBLOG_SHORT_FEED"):
        config.short_feed = os.environ["MADBLOG_SHORT_FEED"] == "1"
    if os.getenv("MADBLOG_ENABLE_WEBMENTIONS"):
        config.enable_webmentions = os.environ["MADBLOG_ENABLE_WEBMENTIONS"] == "1"
    if os.getenv("MADBLOG_WEBMENTIONS_HARD_DELETE"):
        config.webmentions_hard_delete = (
            os.environ["MADBLOG_WEBMENTIONS_HARD_DELETE"] == "1"
        )
    if os.getenv("MADBLOG_DEBUG"):
        config.debug = os.environ["MADBLOG_DEBUG"] == "1"
    if os.getenv("MADBLOG_CATEGORIES"):
        config.categories = re.split(r"[,\s]+", os.environ["MADBLOG_CATEGORIES"])
    if os.getenv("MADBLOG_AUTHOR"):
        config.author = os.environ["MADBLOG_AUTHOR"]
    if os.getenv("MADBLOG_AUTHOR_URL"):
        config.author_url = os.environ["MADBLOG_AUTHOR_URL"]
    if os.getenv("MADBLOG_AUTHOR_PHOTO"):
        config.author_photo = os.environ["MADBLOG_AUTHOR_PHOTO"]


def _init_config_from_cli(args: Optional[Namespace]):
    if not args:
        return

    if args.dir:
        config.content_dir = args.dir
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.debug is not None:
        config.debug = args.debug


def init_config(
    config_file: str = "config.yaml", args: Optional[Namespace] = None
) -> Config:
    config_file = os.path.abspath(os.path.expanduser(config_file))
    _init_config_from_file(config_file)
    _init_config_from_env()
    _init_config_from_cli(args)

    # Normalize/expand paths
    config.content_dir = os.path.abspath(os.path.expanduser(config.content_dir))

    return config


# vim:sw=4:ts=4:et:
