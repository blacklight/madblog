import email.utils
import hashlib
import os
from pathlib import Path
from typing import Union

from flask import Response, has_request_context, make_response, request

from madblog.config import config


def generate_etag(mtime: float) -> str:
    """
    Generate an ETag based on modification time.

    :param mtime: File modification timestamp
    :return: ETag string (quoted)
    """
    # Use hash of timestamp for more compact ETag
    etag_hash = hashlib.md5(str(mtime).encode()).hexdigest()[:16]
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
    paths_to_check = []

    # Webmentions: <mentions_dir>/incoming/<slug>/
    if mentions_dir:
        # For paths like "subdir/my-article", use just the basename for mentions
        slug_basename = os.path.basename(article_slug)
        wm_path = Path(mentions_dir) / "incoming" / slug_basename
        paths_to_check.append(wm_path)

    # ActivityPub interactions: check the whole interactions dir
    # (interactions are stored by target URL hash, not by slug)
    if ap_interactions_dir:
        paths_to_check.append(ap_interactions_dir)

    # Author replies: <replies_dir>/<slug>/
    if replies_dir:
        replies_path = Path(replies_dir) / article_slug
        paths_to_check.append(replies_path)

    return get_max_mtime(*paths_to_check)


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
    paths_to_check = []

    # Webmentions targeting the home page are stored in incoming/_homepage/
    # or in the root incoming/ directory
    if mentions_dir:
        paths_to_check.append(Path(mentions_dir) / "incoming")

    # ActivityPub interactions directory
    if ap_interactions_dir:
        paths_to_check.append(ap_interactions_dir)

    # Author replies to guestbook are in replies/_guestbook/
    if replies_dir:
        paths_to_check.append(Path(replies_dir) / "_guestbook")

    return get_max_mtime(*paths_to_check)


def check_cache_validity(file_mtime: float, etag: str) -> bool:
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
    last_modified: str,
    etag: str,
    metadata: dict,
) -> Response:
    """
    Create a 304 Not Modified response with appropriate headers.
    """
    response = make_response("", 304)
    response.headers["Last-Modified"] = last_modified
    response.headers["ETag"] = etag
    article_language = metadata.get("language")

    if article_language:
        response.headers["Language"] = article_language
    elif config.language:
        response.headers["Language"] = config.language

    return response
