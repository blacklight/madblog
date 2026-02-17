import os
import re
from argparse import Namespace
from dataclasses import dataclass, field
from typing import List, Optional

import yaml
from webmentions import WebmentionStatus


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
    max_entries_per_feed: int = 10
    enable_webmentions: bool = True
    webmentions_hard_delete: bool = False
    default_webmention_status: WebmentionStatus = WebmentionStatus.CONFIRMED
    debug: bool = False
    basedir = os.path.abspath(os.path.dirname(__file__))
    author: str | None = None
    author_url: str | None = None
    author_photo: str | None = None
    throttle_seconds_on_update: int = 10
    webmentions_email: str | None = None
    smtp_server: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    smtp_enable_starttls_auto: bool = True
    smtp_sender: str | None = None
    view_mode: str = "cards"  # "cards", "list", or "full"

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
        from flask import request

        if not self.enable_webmentions:
            return None

        return (
            f'{self.link.rstrip("/")}/webmentions'
            if re.match(r"^https?://", self.link)
            else f'{request.host_url.rstrip("/")} /webmentions'
        )


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
    if cfg.get("max_entries_per_feed") is not None:
        config.max_entries_per_feed = int(cfg["max_entries_per_feed"])
    if cfg.get("enable_webmentions") is not None:
        config.enable_webmentions = bool(cfg["enable_webmentions"])
    if cfg.get("webmentions_hard_delete") is not None:
        config.webmentions_hard_delete = bool(cfg["webmentions_hard_delete"])
    if cfg.get("default_webmention_status"):
        config.default_webmention_status = WebmentionStatus(
            cfg["default_webmention_status"]
        )
    if cfg.get("debug") is not None:
        config.debug = bool(cfg["debug"])
    if cfg.get("author"):
        config.author = cfg["author"]
    if cfg.get("author_url"):
        config.author_url = cfg["author_url"]
    if cfg.get("author_photo"):
        config.author_photo = cfg["author_photo"]
    if cfg.get("throttle_seconds_on_update"):
        config.throttle_seconds_on_update = int(cfg["throttle_seconds_on_update"])

    if cfg.get("webmentions_email"):
        config.webmentions_email = cfg["webmentions_email"]
    if cfg.get("smtp_server"):
        config.smtp_server = cfg["smtp_server"]
    if cfg.get("smtp_port"):
        config.smtp_port = int(cfg["smtp_port"])
    if cfg.get("smtp_username"):
        config.smtp_username = cfg["smtp_username"]
    if cfg.get("smtp_password"):
        config.smtp_password = cfg["smtp_password"]
    if cfg.get("smtp_starttls") is not None:
        config.smtp_starttls = bool(cfg["smtp_starttls"])
    if cfg.get("smtp_enable_starttls_auto") is not None:
        config.smtp_enable_starttls_auto = bool(cfg["smtp_enable_starttls_auto"])
    if cfg.get("smtp_sender"):
        config.smtp_sender = cfg["smtp_sender"]

    if cfg.get("view_mode"):
        config.view_mode = cfg["view_mode"]
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
    if os.getenv("MADBLOG_MAX_ENTRIES_PER_FEED"):
        config.max_entries_per_feed = int(os.environ["MADBLOG_MAX_ENTRIES_PER_FEED"])
    if os.getenv("MADBLOG_ENABLE_WEBMENTIONS"):
        config.enable_webmentions = os.environ["MADBLOG_ENABLE_WEBMENTIONS"] == "1"
    if os.getenv("MADBLOG_WEBMENTIONS_HARD_DELETE"):
        config.webmentions_hard_delete = (
            os.environ["MADBLOG_WEBMENTIONS_HARD_DELETE"] == "1"
        )
    if os.getenv("MADBLOG_DEFAULT_WEBMENTION_STATUS"):
        config.default_webmention_status = WebmentionStatus(
            os.environ["MADBLOG_DEFAULT_WEBMENTION_STATUS"]
        )
    if os.getenv("MADBLOG_DEBUG"):
        config.debug = os.environ["MADBLOG_DEBUG"] == "1"
    if os.getenv("MADBLOG_VIEW_MODE"):
        config.view_mode = os.environ["MADBLOG_VIEW_MODE"]
    if os.getenv("MADBLOG_CATEGORIES"):
        config.categories = re.split(r"[,\s]+", os.environ["MADBLOG_CATEGORIES"])
    if os.getenv("MADBLOG_AUTHOR"):
        config.author = os.environ["MADBLOG_AUTHOR"]
    if os.getenv("MADBLOG_AUTHOR_URL"):
        config.author_url = os.environ["MADBLOG_AUTHOR_URL"]
    if os.getenv("MADBLOG_AUTHOR_PHOTO"):
        config.author_photo = os.environ["MADBLOG_AUTHOR_PHOTO"]
    if os.getenv("MADBLOG_THROTTLE_SECONDS_ON_UPDATE"):
        config.throttle_seconds_on_update = int(
            os.environ["MADBLOG_THROTTLE_SECONDS_ON_UPDATE"]
        )

    if os.getenv("MADBLOG_WEBMENTIONS_EMAIL"):
        config.webmentions_email = os.environ["MADBLOG_WEBMENTIONS_EMAIL"]
    if os.getenv("MADBLOG_SMTP_SERVER"):
        config.smtp_server = os.environ["MADBLOG_SMTP_SERVER"]
    if os.getenv("MADBLOG_SMTP_PORT"):
        config.smtp_port = int(os.environ["MADBLOG_SMTP_PORT"])
    if os.getenv("MADBLOG_SMTP_USERNAME"):
        config.smtp_username = os.environ["MADBLOG_SMTP_USERNAME"]
    if os.getenv("MADBLOG_SMTP_PASSWORD"):
        config.smtp_password = os.environ["MADBLOG_SMTP_PASSWORD"]
    if os.getenv("MADBLOG_SMTP_STARTTLS"):
        config.smtp_starttls = os.environ["MADBLOG_SMTP_STARTTLS"] == "1"
    if os.getenv("MADBLOG_SMTP_ENABLE_STARTTLS_AUTO"):
        config.smtp_enable_starttls_auto = (
            os.environ["MADBLOG_SMTP_ENABLE_STARTTLS_AUTO"] == "1"
        )
    if os.getenv("MADBLOG_SMTP_SENDER"):
        config.smtp_sender = os.environ["MADBLOG_SMTP_SENDER"]


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
