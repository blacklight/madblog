"""Tests for the visibility module."""

import pytest

from madblog.visibility import Visibility, resolve_visibility


class TestVisibilityEnum:
    """Tests for the Visibility enum."""

    def test_visibility_values(self):
        """All visibility levels have correct string values."""
        assert Visibility.PUBLIC.value == "public"
        assert Visibility.UNLISTED.value == "unlisted"
        assert Visibility.FOLLOWERS.value == "followers"
        assert Visibility.DIRECT.value == "direct"
        assert Visibility.DRAFT.value == "draft"

    def test_from_str_valid(self):
        """from_str parses valid visibility strings."""
        assert Visibility.from_str("public") == Visibility.PUBLIC
        assert Visibility.from_str("unlisted") == Visibility.UNLISTED
        assert Visibility.from_str("followers") == Visibility.FOLLOWERS
        assert Visibility.from_str("direct") == Visibility.DIRECT
        assert Visibility.from_str("draft") == Visibility.DRAFT

    def test_from_str_case_insensitive(self):
        """from_str is case-insensitive."""
        assert Visibility.from_str("PUBLIC") == Visibility.PUBLIC
        assert Visibility.from_str("Unlisted") == Visibility.UNLISTED
        assert Visibility.from_str("FOLLOWERS") == Visibility.FOLLOWERS
        assert Visibility.from_str("Direct") == Visibility.DIRECT
        assert Visibility.from_str("DRAFT") == Visibility.DRAFT

    def test_from_str_strips_whitespace(self):
        """from_str strips leading/trailing whitespace."""
        assert Visibility.from_str("  public  ") == Visibility.PUBLIC
        assert Visibility.from_str("\tunlisted\n") == Visibility.UNLISTED

    def test_from_str_invalid(self):
        """from_str raises ValueError for invalid values."""
        with pytest.raises(ValueError, match="Invalid visibility"):
            Visibility.from_str("invalid")
        with pytest.raises(ValueError, match="Invalid visibility"):
            Visibility.from_str("")

    def test_visibility_is_str(self):
        """Visibility enum members are also strings."""
        assert isinstance(Visibility.PUBLIC, str)
        assert Visibility.PUBLIC == "public"


class TestResolveVisibility:
    """Tests for resolve_visibility function."""

    def test_explicit_visibility_in_metadata(self):
        """Explicit visibility in metadata takes precedence."""
        metadata = {"visibility": "unlisted"}
        assert resolve_visibility(metadata) == Visibility.UNLISTED

        metadata = {"visibility": "followers"}
        assert resolve_visibility(metadata) == Visibility.FOLLOWERS

        metadata = {"visibility": "direct"}
        assert resolve_visibility(metadata) == Visibility.DIRECT

        metadata = {"visibility": "draft"}
        assert resolve_visibility(metadata) == Visibility.DRAFT

    def test_explicit_visibility_case_insensitive(self):
        """Visibility in metadata is case-insensitive."""
        metadata = {"visibility": "UNLISTED"}
        assert resolve_visibility(metadata) == Visibility.UNLISTED

    def test_unlisted_reply_default(self):
        """Unlisted replies default to UNLISTED visibility."""
        metadata = {}
        assert (
            resolve_visibility(metadata, is_unlisted_reply=True) == Visibility.UNLISTED
        )

    def test_explicit_overrides_unlisted_reply(self):
        """Explicit visibility overrides unlisted reply default."""
        metadata = {"visibility": "public"}
        assert resolve_visibility(metadata, is_unlisted_reply=True) == Visibility.PUBLIC

        metadata = {"visibility": "draft"}
        assert resolve_visibility(metadata, is_unlisted_reply=True) == Visibility.DRAFT

    def test_default_parameter(self):
        """Default parameter is used when no metadata or special case."""
        metadata = {}
        assert (
            resolve_visibility(metadata, default=Visibility.UNLISTED)
            == Visibility.UNLISTED
        )

    def test_config_default(self, monkeypatch):
        """Config default_visibility is used when no metadata."""
        from madblog import config as config_module

        monkeypatch.setattr(config_module.config, "default_visibility", "unlisted")

        metadata = {}
        assert resolve_visibility(metadata) == Visibility.UNLISTED

    def test_invalid_metadata_falls_through(self, monkeypatch):
        """Invalid visibility in metadata falls through to defaults."""
        from madblog import config as config_module

        monkeypatch.setattr(config_module.config, "default_visibility", "public")

        metadata = {"visibility": "invalid_value"}
        assert resolve_visibility(metadata) == Visibility.PUBLIC

    def test_invalid_config_falls_through(self, monkeypatch):
        """Invalid config default falls through to PUBLIC."""
        from madblog import config as config_module

        monkeypatch.setattr(config_module.config, "default_visibility", "invalid")

        metadata = {}
        assert resolve_visibility(metadata) == Visibility.PUBLIC

    def test_ultimate_fallback_is_public(self, monkeypatch):
        """Ultimate fallback is PUBLIC when all else fails."""
        from madblog import config as config_module

        monkeypatch.setattr(config_module.config, "default_visibility", "")

        metadata = {}
        assert resolve_visibility(metadata) == Visibility.PUBLIC

    def test_empty_metadata(self, monkeypatch):
        """Empty metadata uses config default."""
        from madblog import config as config_module

        monkeypatch.setattr(config_module.config, "default_visibility", "public")

        assert resolve_visibility({}) == Visibility.PUBLIC
