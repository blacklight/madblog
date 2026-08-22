"""
Secrets management for the auth subsystem.

Handles the Flask secret_key and per-user password hashes, enforcing
strict file permissions (0600 for files, 0700 for directories).
"""

import os
import stat
from logging import getLogger
from pathlib import Path

import bcrypt

logger = getLogger(__name__)

_REQUIRED_DIR_MODE = 0o700
_REQUIRED_FILE_MODE = 0o600


class InsecurePermissionsError(Exception):
    """Raised when an auth file has overly permissive mode bits."""


def _check_permissions(path: Path) -> None:
    """
    Refuse to proceed if *path* is readable by group or others.
    """
    st = path.stat()
    if st.st_mode & 0o077:
        raise InsecurePermissionsError(
            f"{path} has mode {oct(stat.S_IMODE(st.st_mode))}; "
            f"must not be group- or world-readable (expected 0600)"
        )


def _ensure_directory(dir_path: Path) -> None:
    """
    Create *dir_path* (and parents) with mode 0700.
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    os.chmod(dir_path, _REQUIRED_DIR_MODE)


def _write_secure(path: Path, data: bytes) -> None:
    """
    Atomically write *data* to *path* with mode 0600.
    """
    _ensure_directory(path.parent)
    tmp_path = path.with_suffix(".tmp")
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _REQUIRED_FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, path)
    os.chmod(path, _REQUIRED_FILE_MODE)


def ensure_secret_key(auth_dir: Path) -> bytes:
    """
    Return the persisted Flask secret key, creating it if missing.

    The key is a 32-byte random value stored as 64 hex characters in
    ``<auth_dir>/secret_key``.
    """
    _ensure_directory(auth_dir)
    key_path = auth_dir / "secret_key"

    if key_path.exists():
        _check_permissions(key_path)
        return bytes.fromhex(key_path.read_text().strip())

    key = os.urandom(32)
    _write_secure(key_path, key.hex().encode())
    logger.info("Generated new Flask secret key at %s", key_path)
    return key


def load_password_hash(user_dir: Path) -> bytes | None:
    """
    Return the bcrypt hash bytes for the user, or None if no hash exists.
    """
    hash_path = user_dir / "password.hash"
    if not hash_path.exists():
        return None
    _check_permissions(hash_path)
    return hash_path.read_bytes().strip()


def write_password_hash(user_dir: Path, plaintext: str) -> None:
    """
    Hash *plaintext* with bcrypt and write it atomically with mode 0600.
    """
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt())
    _write_secure(user_dir / "password.hash", hashed)
