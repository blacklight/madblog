"""
Guestbook module for Madblog.

Captures and displays:
- Webmentions targeting the home page
- ActivityPub public mentions that are not replies to articles
"""

from ._mixin import GuestbookMixin

__all__ = ["GuestbookMixin"]
