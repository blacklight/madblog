"""
Tests for auth secrets management (secret_key, password hashing, permissions).
"""

import os
import stat
import unittest
from pathlib import Path
import tempfile

from madblog.auth._secrets import (
    InsecurePermissionsError,
    _check_permissions,
    _ensure_directory,
    _write_secure,
    ensure_secret_key,
    load_password_hash,
    write_password_hash,
)


class TestEnsureDirectory(unittest.TestCase):
    def test_creates_with_0700(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "auth"
            _ensure_directory(d)
            self.assertTrue(d.is_dir())
            mode = stat.S_IMODE(d.stat().st_mode)
            self.assertEqual(mode, 0o700)

    def test_nested_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "a" / "b" / "c"
            _ensure_directory(d)
            self.assertTrue(d.is_dir())


class TestWriteSecure(unittest.TestCase):
    def test_file_has_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "secret"
            _write_secure(p, b"hello")
            mode = stat.S_IMODE(p.stat().st_mode)
            self.assertEqual(mode, 0o600)
            self.assertEqual(p.read_bytes(), b"hello")

    def test_atomic_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "secret"
            _write_secure(p, b"first")
            _write_secure(p, b"second")
            self.assertEqual(p.read_bytes(), b"second")


class TestCheckPermissions(unittest.TestCase):
    def test_rejects_world_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "loose"
            p.write_text("secret")
            os.chmod(p, 0o644)
            with self.assertRaises(InsecurePermissionsError):
                _check_permissions(p)

    def test_accepts_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "tight"
            _write_secure(p, b"ok")
            _check_permissions(p)  # should not raise


class TestEnsureSecretKey(unittest.TestCase):
    def test_generates_key_on_first_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_dir = Path(tmp) / "auth"
            key = ensure_secret_key(auth_dir)
            self.assertEqual(len(key), 32)
            self.assertTrue((auth_dir / "secret_key").exists())

    def test_returns_same_key_on_subsequent_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_dir = Path(tmp) / "auth"
            key1 = ensure_secret_key(auth_dir)
            key2 = ensure_secret_key(auth_dir)
            self.assertEqual(key1, key2)

    def test_key_file_has_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_dir = Path(tmp) / "auth"
            ensure_secret_key(auth_dir)
            mode = stat.S_IMODE((auth_dir / "secret_key").stat().st_mode)
            self.assertEqual(mode, 0o600)


class TestPasswordHash(unittest.TestCase):
    def test_write_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            user_dir = Path(tmp) / "users" / "admin"
            _ensure_directory(user_dir)
            write_password_hash(user_dir, "hunter2")
            stored = load_password_hash(user_dir)
            self.assertIsNotNone(stored)

            import bcrypt

            self.assertTrue(bcrypt.checkpw(b"hunter2", stored))
            self.assertFalse(bcrypt.checkpw(b"wrong", stored))

    def test_load_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            user_dir = Path(tmp) / "users" / "admin"
            _ensure_directory(user_dir)
            self.assertIsNone(load_password_hash(user_dir))

    def test_hash_file_has_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            user_dir = Path(tmp) / "users" / "admin"
            _ensure_directory(user_dir)
            write_password_hash(user_dir, "test")
            mode = stat.S_IMODE((user_dir / "password.hash").stat().st_mode)
            self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
