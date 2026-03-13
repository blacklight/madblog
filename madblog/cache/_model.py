import email.utils
import os
from dataclasses import dataclass, field

from ._helpers import check_cache_validity, generate_etag, make_304_response


@dataclass
class CachedPage:
    """
    Information about a cached page.
    """

    md_file: str
    metadata: dict = field(default_factory=dict)

    @property
    def file_mtime(self) -> float:
        return os.stat(self.md_file).st_mtime

    @property
    def last_modified(self) -> str:
        return email.utils.formatdate(self.file_mtime, usegmt=True)

    @property
    def etag(self) -> str:
        return generate_etag(self.file_mtime)

    def is_client_cache_valid(self) -> bool:
        return check_cache_validity(self.file_mtime, self.etag)

    def make_304_response(self):
        return make_304_response(self.last_modified, self.etag, self.metadata)
