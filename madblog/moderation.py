"""
Moderation utilities for blocking or allowing actors.

Supports matching by:
- **Domain**: e.g. ``spammer.example.com``
- **URL**: e.g. ``https://mastodon.social/users/spammer``
- **ActivityPub FQN**: e.g. ``@spammer@mastodon.social`` or
  ``spammer@mastodon.social``
- **Regular expression**: delimited by ``/``, e.g.
  ``/spammer\\.example\\..*/``

Used by both Webmentions and ActivityPub subsystems.

**Blocklist vs Allowlist**:
- Blocklist mode (``blocked_actors``): actors matching patterns are rejected.
- Allowlist mode (``allowed_actors``): only actors matching patterns are
  permitted; all others are rejected.
- The two modes are **mutually exclusive**.
"""


class ModerationConfigError(ValueError):
    """Raised when blocklist and allowlist are both configured."""


import logging
import re
import time
from functools import lru_cache
from urllib.parse import urlparse

from madblog.config import config

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


def is_allowed(identifier: str, allowlist: list[str]) -> bool:
    """
    Check whether *identifier* matches any entry in *allowlist*.

    When an allowlist is active, only actors matching at least one
    pattern are permitted to interact.

    :param identifier: The actor identifier to check.
    :param allowlist: List of allow rules (domains, URLs, FQNs, or
        ``/regex/`` patterns).
    :return: ``True`` if the identifier is allowed (matches a pattern).
    """
    if not allowlist:
        # No allowlist configured → everyone is allowed
        return True
    if not identifier:
        return False
    return is_blocked(identifier, allowlist)  # Reuse matching logic


def validate_moderation_config() -> None:
    """
    Validate that blocklist and allowlist are not both configured.

    :raises ModerationConfigError: If both are non-empty.
    """
    if config.blocked_actors and config.allowed_actors:
        raise ModerationConfigError(
            "blocked_actors and allowed_actors are mutually exclusive. "
            "Configure only one of them."
        )


def is_actor_permitted(identifier: str) -> bool:
    """
    Check whether an actor is permitted to interact.

    This is a convenience function that checks both blocklist and allowlist
    modes based on the current configuration.

    :param identifier: The actor identifier to check.
    :return: ``True`` if the actor is permitted.
    """
    if config.allowed_actors:
        return is_allowed(identifier, config.allowed_actors)
    if config.blocked_actors:
        return not is_blocked(identifier, config.blocked_actors)
    return True


class ModerationCache:
    """
    TTL-based cache for the moderation lists (blocklist or allowlist).

    Avoids re-reading ``config.blocked_actors``/``config.allowed_actors``
    on every call (e.g. during fan-out delivery) while still picking up
    changes within a bounded window.

    :param ttl_seconds: How long a cached snapshot stays valid (default
        300 s = 5 min).
    """

    def __init__(self, ttl_seconds: float = 300):
        self._ttl = ttl_seconds
        self._blocklist: list[str] = []
        self._allowlist: list[str] = []
        self._expires_at: float = 0

    def _refresh(self) -> None:
        """Reload lists from config if TTL expired."""
        now = time.monotonic()
        if now >= self._expires_at:
            self._blocklist = list(config.blocked_actors)
            self._allowlist = list(config.allowed_actors)
            self._expires_at = now + self._ttl

    def get(self) -> list[str]:
        """Return the current blocklist, refreshing if the TTL expired."""
        self._refresh()
        return self._blocklist

    def get_allowlist(self) -> list[str]:
        """Return the current allowlist, refreshing if the TTL expired."""
        self._refresh()
        return self._allowlist

    def is_permitted(self, identifier: str) -> bool:
        """
        Check whether an actor is permitted based on cached lists.

        :param identifier: The actor identifier to check.
        :return: ``True`` if the actor is permitted.
        """
        self._refresh()
        if self._allowlist:
            return is_allowed(identifier, self._allowlist)
        if self._blocklist:
            return not is_blocked(identifier, self._blocklist)
        return True

    def invalidate(self) -> None:
        """Force the next access to reload."""
        self._expires_at = 0


# Backwards compatibility alias
BlocklistCache = ModerationCache
