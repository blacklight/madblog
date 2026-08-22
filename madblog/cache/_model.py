import email.utils
import os
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Optional, Union

from ._helpers import (
    check_cache_validity,
    generate_etag,
    get_followers_mtime,
    get_interactions_mtime,
    make_304_response,
)


@dataclass
class CachedPage:
    """
    Information about a cached page.

    Supports computing cache validity from both the article file and
    any associated interaction directories (webmentions, AP interactions,
    author replies).
    """

    md_file: str
    metadata: dict = field(default_factory=dict)
    article_slug: Optional[str] = None
    mentions_dir: Optional[str] = None
    ap_interactions_dir: Optional[str] = None
    replies_dir: Optional[str] = None
    followers_dir: Optional[Union[str, Path]] = None

    @property
    def file_mtime(self) -> float:
        try:
            return os.stat(self.md_file).st_mtime
        except OSError:
            return 0.0

    @property
    def interactions_mtime(self) -> float:
        """Get the most recent mtime from interaction directories."""
        if not self.article_slug:
            return 0.0
        return get_interactions_mtime(
            article_slug=self.article_slug,
            mentions_dir=self.mentions_dir,
            ap_interactions_dir=self.ap_interactions_dir,
            replies_dir=self.replies_dir,
        )

    @cached_property
    def effective_mtime(self) -> float:
        """Get the most recent mtime considering file, interactions, and followers."""
        return max(
            self.file_mtime,
            self.interactions_mtime,
            get_followers_mtime(self.followers_dir),
        )

    @property
    def last_modified(self) -> str:
        return email.utils.formatdate(self.effective_mtime, usegmt=True)

    @property
    def etag(self) -> str:
        return generate_etag(self.effective_mtime)

    def is_client_cache_valid(self) -> bool:
        return check_cache_validity(self.effective_mtime, self.etag)

    def make_304_response(self):
        return make_304_response(self.last_modified, self.etag, self.metadata)
