"""
Tests for UserStore: username validation, user lifecycle, password verification.
"""

import unittest
import tempfile
from pathlib import Path

from madblog.auth._users import (
    RESERVED_NAMES,
    User,
    UserStore,
    validate_username,
)
from madblog.auth._secrets import _ensure_directory


class TestValidateUsername(unittest.TestCase):
    def test_valid_names(self):
        for name in ("admin", "jane", "user-1", "user_2", "a0"):
            self.assertEqual(validate_username(name), name)

    def test_normalises_to_lowercase(self):
        self.assertEqual(validate_username("Admin"), "admin")
        self.assertEqual(validate_username("  JanE  "), "jane")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            validate_username("")

    def test_rejects_too_long(self):
        with self.assertRaises(ValueError):
            validate_username("a" * 32)

    def test_rejects_leading_hyphen(self):
        with self.assertRaises(ValueError):
            validate_username("-user")

    def test_rejects_special_chars(self):
        for name in ("user@name", "user.name", "user name", "user/name"):
            with self.assertRaises(ValueError):
                validate_username(name)

    def test_rejects_reserved_names(self):
        for name in RESERVED_NAMES:
            with self.assertRaises(ValueError):
                validate_username(name)

    def test_admin_is_allowed(self):
        self.assertEqual(validate_username("admin"), "admin")


class TestUserStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.auth_dir = Path(self._tmp.name) / "auth"
        self.store = UserStore(self.auth_dir, "admin")

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_username(self):
        self.assertEqual(self.store.default_username, "admin")

    def test_get_nonexistent_user(self):
        self.assertIsNone(self.store.get("nobody"))

    def test_set_password_creates_user_dir(self):
        self.store.set_password("admin", "pw123")
        user_dir = self.auth_dir / "users" / "admin"
        self.assertTrue(user_dir.is_dir())
        self.assertTrue((user_dir / "password.hash").exists())

    def test_get_after_set_password(self):
        self.store.set_password("admin", "pw123")
        user = self.store.get("admin")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "admin")
        self.assertEqual(user.display_name, "admin")

    def test_verify_correct_password(self):
        self.store.set_password("admin", "secret")
        self.assertTrue(self.store.verify("admin", "secret"))

    def test_verify_wrong_password(self):
        self.store.set_password("admin", "secret")
        self.assertFalse(self.store.verify("admin", "wrong"))

    def test_verify_nonexistent_user(self):
        self.assertFalse(self.store.verify("nobody", "any"))

    def test_is_auth_enabled_false_when_empty(self):
        self.assertFalse(self.store.is_auth_enabled())

    def test_is_auth_enabled_true_after_set_password(self):
        self.store.set_password("admin", "pw")
        self.assertTrue(self.store.is_auth_enabled())

    def test_set_password_rejects_reserved_name(self):
        with self.assertRaises(ValueError):
            self.store.set_password("login", "pw")

    def test_get_returns_none_for_empty_string(self):
        self.assertIsNone(self.store.get(""))

    def test_get_returns_none_for_none(self):
        self.assertIsNone(self.store.get(None))

    def test_profile_yaml_loaded(self):
        self.store.set_password("admin", "pw")
        user_dir = self.auth_dir / "users" / "admin"
        (user_dir / "profile.yaml").write_text("display_name: The Admin\n")
        user = self.store.get("admin")
        self.assertEqual(user.display_name, "The Admin")


if __name__ == "__main__":
    unittest.main()
