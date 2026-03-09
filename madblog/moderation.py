"""
Moderation utilities for blocking unwanted actors.

Supports blocking by:
- **Domain**: e.g. ``spammer.example.com``
- **URL**: e.g. ``https://mastodon.social/users/spammer``
- **ActivityPub FQN**: e.g. ``@spammer@mastodon.social`` or
  ``spammer@mastodon.social``
- **Regular expression**: delimited by ``/``, e.g.
  ``/spammer\\.example\\..*/``

Used by both Webmentions and ActivityPub subsystems.
"""

import logging
import re
from functools import lru_cache
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Pattern: optional leading @, then user@domain
_FQN_RE = re.compile(r"^@?([^@\s]+)@([^@\s]+)$")


@lru_cache(maxsize=256)
def _compile_regex(pattern: str) -> re.Pattern | None:
    """Compile a regex pattern string, returning None on error."""
    try:
        return re.compile(pattern)
    except re.error:
        logger.warning("Invalid regex in blocklist: %s", pattern)
        return None


def _extract_domain(identifier: str) -> str | None:
    """Extract the hostname from a URL or return None."""
    try:
        parsed = urlparse(identifier)
        if parsed.hostname:
            return parsed.hostname.lower()
    except Exception:
        pass
    return None


def is_blocked(  # pylint: disable=too-many-return-statements
    identifier: str, blocklist: list[str]
) -> bool:
    """
    Check whether *identifier* matches any entry in *blocklist*.

    :param identifier: The actor identifier to check — a source URL
        (Webmentions) or an actor ID URL (ActivityPub).
    :param blocklist: List of blocking rules (domains, URLs, FQNs, or
        ``/regex/`` patterns).
    :return: ``True`` if the identifier is blocked.
    """
    if not identifier or not blocklist:
        return False

    identifier_lower = identifier.lower()
    identifier_domain = _extract_domain(identifier)

    for entry in blocklist:
        entry = entry.strip()
        if not entry:
            continue

        # Regex pattern: /pattern/
        if entry.startswith("/") and entry.endswith("/") and len(entry) > 2:
            regex = _compile_regex(entry[1:-1])
            if regex and regex.search(identifier):
                return True
            continue

        # FQN pattern: @user@domain or user@domain
        fqn_match = _FQN_RE.match(entry)
        if fqn_match:
            fqn_user = fqn_match.group(1).lower()
            fqn_domain = fqn_match.group(2).lower()
            if identifier_domain == fqn_domain and fqn_user in identifier_lower:
                return True
            continue

        entry_lower = entry.lower()

        # Exact URL match
        if identifier_lower == entry_lower:
            return True

        # Domain match: entry has no scheme and no path separators →
        # treat as a domain name.
        if "/" not in entry and ":" not in entry:
            if identifier_domain == entry_lower:
                return True
            continue

        # Fallback: substring of the identifier (covers partial URLs)
        if entry_lower in identifier_lower:
            return True

    return False
