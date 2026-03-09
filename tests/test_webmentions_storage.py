import tempfile
import unittest
from pathlib import Path

from madblog.webmentions._storage import FileWebmentionsStorage


class TestWebmentionsStateDirPlacement(unittest.TestCase):
    """
    Regression test: the ``.madblog`` state directory must live under
    ``root_dir`` (the content root), **not** under ``content_dir``
    (the pages directory).
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        self.root = Path(self._tmpdir.name)
        self.pages_dir = self.root / "markdown"
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.mentions_dir = self.root / "mentions"

    def test_state_dir_under_root_dir(self):
        """When root_dir is given, .madblog must be under root_dir."""
        storage = FileWebmentionsStorage(
            content_dir=self.pages_dir,
            mentions_dir=self.mentions_dir,
            base_url="https://example.com",
            root_dir=self.root,
        )

        expected = self.root / ".madblog" / "webmentions_sync.json"
        self.assertEqual(storage._sync_cache_file, expected)
        self.assertTrue(expected.parent.is_dir())
        # Must NOT be under pages_dir
        self.assertFalse(str(storage._sync_cache_file).startswith(str(self.pages_dir)))

    def test_state_dir_defaults_to_content_dir_when_no_root(self):
        """When root_dir is omitted, .madblog falls back to content_dir."""
        storage = FileWebmentionsStorage(
            content_dir=self.pages_dir,
            mentions_dir=self.mentions_dir,
            base_url="https://example.com",
        )

        expected = self.pages_dir / ".madblog" / "webmentions_sync.json"
        self.assertEqual(storage._sync_cache_file, expected)

    def test_file_to_url_uses_content_dir(self):
        """URL generation must use content_dir (pages dir), not root_dir."""
        (self.pages_dir / "hello.md").write_text("# Hello\n", encoding="utf-8")

        storage = FileWebmentionsStorage(
            content_dir=self.pages_dir,
            mentions_dir=self.mentions_dir,
            base_url="https://example.com",
            root_dir=self.root,
        )

        url = storage.file_to_url(str(self.pages_dir / "hello.md"))
        self.assertEqual(url, "https://example.com/article/hello")


if __name__ == "__main__":
    unittest.main()
