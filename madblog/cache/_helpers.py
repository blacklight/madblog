import email.utils
import hashlib
import os
from pathlib import Path
from typing import Any, Optional, Union

from flask import Response, has_request_context, make_response, request

from madblog.config import config


def generate_etag(mtime: float, *extra: str) -> str:
    """
    Generate an ETag based on modification time.

    :param mtime: File modification timestamp
    :param extra: Optional extra strings folded into the hash so that
        different variants (e.g. tab names) produce distinct ETags.
    :return: ETag string (quoted)
    """
    # Use hash of timestamp (+ optional discriminators) for compact ETag
    parts = [str(mtime)] + list(extra)
    etag_hash = hashlib.md5(
        ":".join(parts).encode(), usedforsecurity=False
    ).hexdigest()[:16]
    return f'"{etag_hash}"'


def get_dir_mtime(path: Union[str, Path]) -> float:
    """
    Get the modification time of a directory.

    Returns the directory's own mtime, which is updated when files are
    added, removed, or renamed within it. This is efficient because it
    doesn't scan all files.

    :param path: Path to the directory
    :return: Modification timestamp, or 0 if the directory doesn't exist
    """
    try:
        return os.stat(path).st_mtime
    except (OSError, TypeError):
        return 0.0


def get_recursive_max_mtime(path: Union[str, Path, None]) -> float:
    """
    Get the maximum modification time of a path and all nested entries.

    For a directory, this walks the entire tree and returns the most
    recent ``st_mtime`` found on the directory itself or any file or
    subdirectory under it. For a file, only the file's own mtime is
    considered.

    Use this when a route depends on nested content (e.g. interaction
    directories stored by target URL hash, or folder subtrees).

    :param path: Path to a file or directory (``None`` or missing paths
        return ``0.0``)
    :return: Maximum modification timestamp found, or 0 if the path does
        not exist or is not accessible
    """
    if not path:
        return 0.0

    try:
        path = Path(path)
    except (TypeError, ValueError):
        return 0.0

    if not path.exists():
        return 0.0

    max_mtime = 0.0
    try:
        max_mtime = path.stat().st_mtime
    except OSError:
        pass

    if path.is_dir():
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                entry_path = Path(root) / name
                try:
                    mtime = entry_path.stat().st_mtime
                    if mtime > max_mtime:
                        max_mtime = mtime
                except OSError:
                    pass

    return max_mtime


def get_max_mtime(*paths: Union[str, Path, None]) -> float:
    """
    Get the maximum modification time from multiple paths.

    For directories, uses the directory's own mtime (efficient).
    For files, uses the file's mtime.

    :param paths: Paths to files or directories (None values are ignored)
    :return: Maximum modification timestamp found, or 0 if none exist
    """
    max_mtime = 0.0
    for path in paths:
        if path is None:
            continue
        try:
            mtime = os.stat(path).st_mtime
            if mtime > max_mtime:
                max_mtime = mtime
        except (OSError, TypeError):
            pass
    return max_mtime


def get_interactions_mtime(
    *,
    article_slug: str,
    mentions_dir: Union[str, Path, None] = None,
    ap_interactions_dir: Union[str, Path, None] = None,
    replies_dir: Union[str, Path, None] = None,
) -> float:
    """
    Get the most recent modification time for all interactions related to an article.

    Checks:
    - Webmentions directory: <mentions_dir>/incoming/<slug>/
    - ActivityPub interactions directory: <ap_interactions_dir>/
    - Author replies directory: <replies_dir>/<slug>/

    :param article_slug: The article slug (e.g., "my-article" or "subdir/my-article")
    :param mentions_dir: Base directory for webmentions storage
    :param ap_interactions_dir: Directory for ActivityPub interactions
    :param replies_dir: Base directory for author replies
    :return: Maximum modification timestamp found, or 0 if none exist
    """
    mtimes = []

    # Webmentions: <mentions_dir>/incoming/<slug>/
    if mentions_dir:
        # For paths like "subdir/my-article", use just the basename for mentions
        slug_basename = os.path.basename(article_slug)
        wm_path = Path(mentions_dir) / "incoming" / slug_basename
        mtimes.append(get_recursive_max_mtime(wm_path))

    # ActivityPub interactions: check the whole interactions dir recursively
    # (interactions are stored by target URL hash, not by slug)
    if ap_interactions_dir:
        mtimes.append(get_recursive_max_mtime(ap_interactions_dir))

    # Author replies: <replies_dir>/<slug>/
    if replies_dir:
        replies_path = Path(replies_dir) / article_slug
        mtimes.append(get_recursive_max_mtime(replies_path))

    return max(mtimes) if mtimes else 0.0


def get_guestbook_mtime(
    *,
    mentions_dir: Union[str, Path, None] = None,
    ap_interactions_dir: Union[str, Path, None] = None,
    replies_dir: Union[str, Path, None] = None,
) -> float:
    """
    Get the most recent modification time for guestbook interactions.

    Guestbook entries come from:
    - Webmentions targeting the home page
    - ActivityPub interactions (mentions/replies not targeting articles)
    - Author replies in _guestbook/

    :param mentions_dir: Base directory for webmentions storage
    :param ap_interactions_dir: Directory for ActivityPub interactions
    :param replies_dir: Base directory for author replies
    :return: Maximum modification timestamp found, or 0 if none exist
    """
    mtimes = []

    # Webmentions targeting the home page are stored in incoming/_homepage/
    # or in the root incoming/ directory. Walk recursively so nested
    # additions under existing subdirectories are seen.
    if mentions_dir:
        mtimes.append(get_recursive_max_mtime(Path(mentions_dir) / "incoming"))

    # ActivityPub interactions directory (stored by target URL hash)
    if ap_interactions_dir:
        mtimes.append(get_recursive_max_mtime(ap_interactions_dir))

    # Author replies to guestbook are in replies/_guestbook/
    if replies_dir:
        mtimes.append(get_recursive_max_mtime(Path(replies_dir) / "_guestbook"))

    return max(mtimes) if mtimes else 0.0


def check_cache_validity(file_mtime: float, etag: str | None) -> bool:
    """
    Check if the client's cached version is still valid.

    :param file_mtime: File modification timestamp
    :param etag: ETag for the current file version
    :return: True if the client's cache is valid (304 should be returned)
    """
    if not has_request_context():
        return False

    if_modified_since = request.headers.get("If-Modified-Since")
    if_none_match = request.headers.get("If-None-Match")

    # Check If-Modified-Since
    if if_modified_since:
        try:
            parsed_date = email.utils.parsedate_tz(if_modified_since)
            if parsed_date:
                cached_timestamp = email.utils.mktime_tz(parsed_date)  # type: ignore
                if cached_timestamp is not None and cached_timestamp >= file_mtime:
                    return True
        except (ValueError, TypeError, OverflowError):
            pass

    # Check If-None-Match (ETag)
    if if_none_match:
        client_etags = [tag.strip() for tag in if_none_match.split(",")]
        if etag in client_etags or "*" in client_etags:
            return True

    return False


def make_304_response(
    last_modified: str | None,
    etag: str | None,
    metadata: dict | None = None,
) -> Response:
    """
    Create a 304 Not Modified response with appropriate headers.

    :param last_modified: Last-Modified header value (optional)
    :param etag: ETag header value (optional)
    :param metadata: Optional dict with article-specific metadata (e.g., language)
    """
    response = make_response("", 304)
    if last_modified:
        response.headers["Last-Modified"] = last_modified
    if etag:
        response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

    article_language = (metadata or {}).get("language")
    if article_language:
        response.headers["Language"] = article_language
    elif config.language:
        response.headers["Language"] = config.language

    return response


def set_cache_headers(
    response: Response,
    last_modified: str | None,
    etag: str | None,
) -> None:
    """
    Set cache and language headers on a response.

    :param response: Flask Response object to modify
    :param last_modified: Last-Modified header value (optional)
    :param etag: ETag header value (optional)
    """
    if last_modified:
        response.headers["Last-Modified"] = last_modified
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    if etag:
        response.headers["ETag"] = etag
    if config.language:
        response.headers["Language"] = config.language


def get_followers_mtime(path: Union[str, Path, None]) -> float:
    """
    Get the most recent modification time for ActivityPub followers.

    This is a thin wrapper around :func:`get_recursive_max_mtime` so that
    call sites express their intent clearly. It returns the most recent
    mtime of the followers directory and any files or subdirectories
    inside it.

    :param path: Path to the followers state directory
    :return: Maximum modification timestamp found, or 0 if it does not exist
    """
    return get_recursive_max_mtime(path)


def get_followers_dir(app: Any) -> Optional[Path]:
    """
    Return the ActivityPub followers state directory for ``app``.

    Returns ``None`` when ActivityPub is disabled or the storage backend
    has not been initialized.
    """
    if not config.enable_activitypub:
        return None
    if not getattr(app, "activitypub_storage", None):
        return None
    return config.resolved_state_dir / "activitypub" / "state" / "followers"


def get_followers_mtime_for_app(app: Any) -> float:
    """
    Return the most recent mtime of the ActivityPub followers tree.

    Returns ``0.0`` when ActivityPub is disabled or the storage backend
    has not been initialized.
    """
    return get_followers_mtime(get_followers_dir(app))


def compute_pages_mtime(
    pages: list,
    pages_dir,
    folder: str = "",
    followers_mtime: Optional[float] = None,
) -> float:
    """
    Compute the most recent modification time from pages and pages_dir.

    Considers:
    - The folder subtree (when ``folder`` is provided) or the pages
      directory itself (to detect added/removed articles).
    - Local file mtimes for the pages in the list.
    - An optional follower mtime contribution for any page that renders
      the shared nav follower count.

    :param pages: List of (index, page_data) tuples from get_pages()
    :param pages_dir: Path to the pages directory
    :param folder: Optional folder path (relative to ``pages_dir``) to
        scope the recursive tree signal to a folder index
    :param followers_mtime: Optional pre-computed followers modification
        timestamp to fold into the result
    :return: Most recent modification timestamp
    """
    if folder:
        most_recent_mtime = get_recursive_max_mtime(Path(pages_dir) / folder)
    else:
        most_recent_mtime = get_max_mtime(pages_dir)

    for _, page_data in pages:
        if "file_mtime" in page_data:
            most_recent_mtime = max(most_recent_mtime, page_data["file_mtime"])

    if followers_mtime:
        most_recent_mtime = max(most_recent_mtime, followers_mtime)

    return most_recent_mtime
