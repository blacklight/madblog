from enum import Enum


class WebmentionDirection(str, Enum):
    """
    Enum representing the direction of a Webmention (incoming or outgoing).
    """

    IN = "incoming"
    OUT = "outgoing"
