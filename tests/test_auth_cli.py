"""
Tests for the ``madblog set-password`` CLI subcommand.
"""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from madblog.config import config


class TestCliSetPassword(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.temp_dir = self._tmp.name
        self._orig_content_dir = config.content_dir
        self._orig_state_dir = config.state_dir
        self._orig_auth_password = config.auth_password

        config.content_dir = self.temp_dir
        config.state_dir = os.path.join(self.temp_dir, ".madblog")
        config.auth_password = None

        pages_dir = Path(self.temp_dir) / "markdown"
        pages_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        config.content_dir = self._orig_content_dir
        config.state_dir = self._orig_state_dir
        config.auth_password = self._orig_auth_password
        self._tmp.cleanup()

    def test_set_password_via_env(self):
        from madblog.cli import _cmd_set_password
        from types import SimpleNamespace

        opts = SimpleNamespace(
            dir=self.temp_dir,
            config=None,
            user=None,
            host=None,
            port=None,
            debug=None,
        )

        env = {"MADBLOG_AUTH_PASSWORD": "envpass"}
        with patch.dict(os.environ, env):
            _cmd_set_password(opts)

        hash_path = config.auth_dir / "users" / "blog" / "password.hash"
        self.assertTrue(hash_path.exists())
        mode = stat.S_IMODE(hash_path.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_set_password_custom_user(self):
        from madblog.cli import _cmd_set_password
        from types import SimpleNamespace

        opts = SimpleNamespace(
            dir=self.temp_dir,
            config=None,
            user="jane",
            host=None,
            port=None,
            debug=None,
        )

        env = {"MADBLOG_AUTH_PASSWORD": "janepass"}
        with patch.dict(os.environ, env):
            _cmd_set_password(opts)

        hash_path = config.auth_dir / "users" / "jane" / "password.hash"
        self.assertTrue(hash_path.exists())

    def test_set_password_rejects_reserved_name(self):
        from madblog.cli import _cmd_set_password
        from types import SimpleNamespace

        opts = SimpleNamespace(
            dir=self.temp_dir,
            config=None,
            user="login",
            host=None,
            port=None,
            debug=None,
        )

        env = {"MADBLOG_AUTH_PASSWORD": "pw"}
        with patch.dict(os.environ, env):
            with self.assertRaises(SystemExit) as ctx:
                _cmd_set_password(opts)
            self.assertEqual(ctx.exception.code, 1)


class TestCliSubcommandParsing(unittest.TestCase):
    def test_serve_is_default(self):
        from madblog.cli import get_args

        opts, _ = get_args(["/some/dir"])
        self.assertEqual(opts.command, "serve")
        self.assertEqual(opts.dir, "/some/dir")

    def test_set_password_parsed(self):
        from madblog.cli import get_args

        opts, _ = get_args(["set-password", "--config", "c.yaml"])
        self.assertEqual(opts.command, "set-password")
        self.assertEqual(opts.config, "c.yaml")

    def test_no_args_defaults_to_serve(self):
        from madblog.cli import get_args

        opts, _ = get_args([])
        self.assertEqual(opts.command, "serve")

    def test_flags_only_defaults_to_serve(self):
        from madblog.cli import get_args

        opts, _ = get_args(["--debug"])
        self.assertEqual(opts.command, "serve")


if __name__ == "__main__":
    unittest.main()
