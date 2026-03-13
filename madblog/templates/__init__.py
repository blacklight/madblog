from urllib.parse import urlparse

from pubby.render._renderer import TemplateUtils as PubbyTemplateUtils


class TemplateUtils:
    """
    Jinja2 template utils
    """

    ap = PubbyTemplateUtils()

    @staticmethod
    def hostname(url: str) -> str | None:
        return urlparse(url).hostname
