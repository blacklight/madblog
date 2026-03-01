import tempfile
import unittest
from pathlib import Path


class TaskListTest(unittest.TestCase):
    def setUp(self):
        # Import inside setUp so tests are resilient to execution order.
        from madblog.app import app
        from madblog.config import config

        self.app = app
        self.config = config

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        markdown_dir = root / "markdown"
        markdown_dir.mkdir(parents=True, exist_ok=True)

        # Point the app at the temp content.
        self.config.content_dir = str(root)
        self.config.link = "https://example.com"
        self.config.title = "Example"
        self.config.description = "Example feed"

        # Ensure app reads from our markdown directory.
        self.app.pages_dir = str(markdown_dir)

        # Tests shouldn't depend on webmentions.
        self.config.enable_webmentions = False

        self.client = self.app.test_client()

    def test_task_list_renders_checkboxes(self):
        markdown_dir = Path(self.app.pages_dir)
        (markdown_dir / "tasklist-post.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Tasklist Post)",
                    "[//]: # (published: 2025-02-13)",
                    "",
                    "# Tasklist Post",
                    "",
                    "- [ ] First",
                    "- [x] Second",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        rsp = self.client.get("/article/tasklist-post")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.data.decode("utf-8")

        self.assertNotIn("[ ]", html)
        self.assertNotIn("[x]", html)
        self.assertIn('type="checkbox"', html)
        self.assertIn("disabled", html)
        self.assertRegex(
            html,
            r"<li[^>]*>\s*<input[^>]*type=\"checkbox\"[^>]*>\s*First",
        )
        self.assertIn('class="task-list-item"', html)


if __name__ == "__main__":
    unittest.main()
