class WebmentionException(Exception):
    """
    Base exception for webmention errors.
    """

    def __init__(self, source: str | None, target: str | None, message: str, **_):
        self.source = source
        self.target = target
        self.message = message
        super().__init__(f"Invalid Webmention from '{source}' to '{target}': {message}")


class WebmentionGone(WebmentionException, ValueError):
    """
    Exception for webmentions that no longer exist.
    """

    def __init__(
        self, source: str | None, target: str | None, msg: str | None = None, **_
    ):
        super().__init__(source, target, msg or "Webmention no longer exists")
