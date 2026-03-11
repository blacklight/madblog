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
