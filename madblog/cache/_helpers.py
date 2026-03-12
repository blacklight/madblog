import email.utils
import hashlib

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


@staticmethod
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
