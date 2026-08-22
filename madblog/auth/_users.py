"""
User store for the auth subsystem.

Discovers users under ``<state_dir>/auth/users/``, validates usernames,
and verifies passwords via bcrypt.
"""

import re
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path

import bcrypt
import yaml

from ._secrets import (
    _ensure_directory,
    load_password_hash,
    write_password_hash,
)

logger = getLogger(__name__)

_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")

RESERVED_NAMES = frozenset(
    {
        "about",
        "ap",
        "article",
        "css",
        "fonts",
        "guestbook",
        "img",
        "js",
        "login",
        "logout",
        "reply",
        "tags",
        "unlisted",
        "webmentions",
    }
)


def validate_username(username: str) -> str:
    """
    Validate and normalise a username.

    :raises ValueError: if the name is invalid or reserved.
    """
    username = username.lower().strip()
    if not _USERNAME_RE.match(username):
        raise ValueError(
            f"Invalid username {username!r}: must match {_USERNAME_RE.pattern}"
        )
    if username in RESERVED_NAMES:
        raise ValueError(
            f"Username {username!r} is reserved (conflicts with an existing route)"
        )
    return username


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    profile: dict = field(default_factory=dict)
    user_dir: Path = field(default_factory=lambda: Path("."))


class UserStore:
    """
    Manages user accounts stored under ``<auth_dir>/users/``.
    """

    def __init__(self, auth_dir: Path, default_username: str) -> None:
        self._auth_dir = auth_dir
        self._users_dir = auth_dir / "users"
        self._default_username = validate_username(default_username)

    @property
    def default_username(self) -> str:
        return self._default_username

    def _user_dir(self, username: str) -> Path:
        return self._users_dir / username

    def get(self, username: str) -> "User | None":
        """
        Return a User object if the user directory exists, else None.
        """
        if not username:
            return None
        username = username.lower().strip()
        user_dir = self._user_dir(username)
        if not user_dir.is_dir():
            return None

        profile = self._load_profile(user_dir)
        display_name = profile.get("display_name", username)
        return User(
            username=username,
            display_name=display_name,
            profile=profile,
            user_dir=user_dir,
        )

    def verify(self, username: str, plaintext: str) -> bool:
        """
        Verify a password against the stored hash for *username*.
        """
        username = username.lower().strip()
        user_dir = self._user_dir(username)
        stored_hash = load_password_hash(user_dir)
        if stored_hash is None:
            return False
        try:
            return bcrypt.checkpw(plaintext.encode(), stored_hash)
        except (ValueError, TypeError) as exc:
            logger.warning("bcrypt error for user %s: %s", username, exc)
            return False

    def set_password(self, username: str, plaintext: str) -> None:
        """
        Set the password for *username*, creating the user directory if needed.
        """
        username = validate_username(username)
        user_dir = self._user_dir(username)
        _ensure_directory(user_dir)
        write_password_hash(user_dir, plaintext)

    def is_auth_enabled(self) -> bool:
        """
        Return True if at least one user has a password hash on disk.
        """
        if not self._users_dir.is_dir():
            return False
        for user_path in self._users_dir.iterdir():
            if user_path.is_dir() and (user_path / "password.hash").exists():
                return True
        return False

    @staticmethod
    def _load_profile(user_dir: Path) -> dict:
        profile_path = user_dir / "profile.yaml"
        if not profile_path.exists():
            return {}
        try:
            with open(profile_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            logger.warning("Failed to load profile from %s", profile_path, exc_info=True)
            return {}
