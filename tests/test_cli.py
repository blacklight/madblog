"""
Tests for the CLI entry-point, including memory-optimisation guards.
"""

import os
import threading
import unittest
from unittest.mock import patch, MagicMock


class MemoryOptimisationTest(unittest.TestCase):
    """Verify that ``run()`` applies malloc-arena and stack-size tuning."""

    @patch("madblog.cli.get_args")
    def test_malloc_arena_max_env_is_set(self, mock_args):
        """MALLOC_ARENA_MAX should be set in the environment."""
        mock_args.return_value = (
            MagicMock(dir=None, config=None, host=None, port=None, debug=None),
            [],
        )

        # Remove the key so we can detect it being set
        os.environ.pop("MALLOC_ARENA_MAX", None)

        with patch("madblog.cli.init_config", create=True), patch(
            "madblog.app.app"
        ) as mock_app:
            mock_app.start = MagicMock()
            mock_app.run = MagicMock(side_effect=SystemExit(0))
            mock_app.stop = MagicMock()

            try:
                from madblog.cli import run

                run()
            except SystemExit:
                pass

        self.assertEqual(os.environ.get("MALLOC_ARENA_MAX"), "2")

    @patch("madblog.cli.get_args")
    def test_thread_stack_size_is_reduced(self, mock_args):
        """Thread stack size should be set to 2 MB."""
        mock_args.return_value = (
            MagicMock(dir=None, config=None, host=None, port=None, debug=None),
            [],
        )

        with patch("madblog.cli.init_config", create=True), patch(
            "madblog.app.app"
        ) as mock_app:
            mock_app.start = MagicMock()
            mock_app.run = MagicMock(side_effect=SystemExit(0))
            mock_app.stop = MagicMock()

            try:
                from madblog.cli import run

                run()
            except SystemExit:
                pass

        # threading.stack_size() with no args returns the current setting
        self.assertEqual(threading.stack_size(), 2 * 1024 * 1024)

    @patch("madblog.cli.get_args")
    def test_malloc_arena_max_respects_existing_value(self, mock_args):
        """If MALLOC_ARENA_MAX is already set, ``run()`` should not override it."""
        mock_args.return_value = (
            MagicMock(dir=None, config=None, host=None, port=None, debug=None),
            [],
        )

        os.environ["MALLOC_ARENA_MAX"] = "4"

        with patch("madblog.cli.init_config", create=True), patch(
            "madblog.app.app"
        ) as mock_app:
            mock_app.start = MagicMock()
            mock_app.run = MagicMock(side_effect=SystemExit(0))
            mock_app.stop = MagicMock()

            try:
                from madblog.cli import run

                run()
            except SystemExit:
                pass

        self.assertEqual(os.environ.get("MALLOC_ARENA_MAX"), "4")


class RenderingFeaturesConfigTest(unittest.TestCase):
    """Tests for enable_latex / enable_mermaid config flags."""

    def setUp(self):
        # Reset the cached extensions before each test
        import madblog.markdown._render as render_module

        render_module._md_extensions = None

    def test_latex_disabled_via_config(self):
        """When enable_latex=False, LaTeX extension should not be loaded."""
        from madblog.config import config

        config.enable_latex = False
        config.enable_mermaid = False

        from madblog.markdown._render import _build_extensions

        extensions = _build_extensions()
        extension_names = [
            type(ext).__name__ for ext in extensions if not isinstance(ext, str)
        ]

        self.assertNotIn("MarkdownLatex", extension_names)
        self.assertNotIn("MarkdownMermaid", extension_names)

    def test_latex_enabled_via_config(self):
        """When enable_latex=True, LaTeX extension should be loaded."""
        from madblog.config import config

        config.enable_latex = True
        config.enable_mermaid = False

        from madblog.markdown._render import _build_extensions

        extensions = _build_extensions()
        extension_names = [
            type(ext).__name__ for ext in extensions if not isinstance(ext, str)
        ]

        self.assertIn("MarkdownLatex", extension_names)
        self.assertNotIn("MarkdownMermaid", extension_names)

    def test_mermaid_enabled_via_config(self):
        """When enable_mermaid=True, Mermaid extension should be loaded."""
        from madblog.config import config

        config.enable_latex = False
        config.enable_mermaid = True

        from madblog.markdown._render import _build_extensions

        extensions = _build_extensions()
        extension_names = [
            type(ext).__name__ for ext in extensions if not isinstance(ext, str)
        ]

        self.assertNotIn("MarkdownLatex", extension_names)
        self.assertIn("MarkdownMermaid", extension_names)

    def test_config_from_yaml(self):
        """Config flags should be readable from YAML."""
        import tempfile
        import yaml

        from madblog.config import _init_config_from_file, config

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"enable_latex": False, "enable_mermaid": False}, f)
            f.flush()

            # Reset config
            config.enable_latex = True
            config.enable_mermaid = True

            _init_config_from_file(f.name)

            self.assertFalse(config.enable_latex)
            self.assertFalse(config.enable_mermaid)

            os.unlink(f.name)

    def test_config_from_env(self):
        """Config flags should be readable from environment variables."""
        from madblog.config import config, _init_config_from_env

        # Reset
        config.enable_latex = True
        config.enable_mermaid = True

        os.environ["MADBLOG_ENABLE_LATEX"] = "0"
        os.environ["MADBLOG_ENABLE_MERMAID"] = "0"

        try:
            _init_config_from_env()
            self.assertFalse(config.enable_latex)
            self.assertFalse(config.enable_mermaid)
        finally:
            os.environ.pop("MADBLOG_ENABLE_LATEX", None)
            os.environ.pop("MADBLOG_ENABLE_MERMAID", None)
