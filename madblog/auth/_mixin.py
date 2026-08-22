"""
AuthMixin — wires the auth subsystem into the Flask app.

Mixed into BlogApp. Initialises the user store, secret key, session
config, CSRF protection, rate limiter, and auth routes when a password
is configured.
"""

from datetime import timedelta
from logging import getLogger
from typing import Callable

from flask import Config
from flask.sansio.app import Map

from madblog.config import config

from ._decorators import current_user
from ._routes import register_auth_routes
from ._secrets import ensure_secret_key
from ._users import UserStore

logger = getLogger(__name__)


class AuthMixin:
    """
    Provides authentication initialisation for BlogApp.
    """

    user_store: UserStore
    blog_config = config
    config: Config
    url_map: Map
    view_functions: dict[str, Callable]

    def _init_auth(self) -> None:  # type: ignore[misc]
        """
        Bootstrap the auth subsystem. Must be called from BlogApp.__init__.
        """

        if getattr(self, "_auth_initialized", False):
            return
        self._auth_initialized = True

        default_username = (
            config.default_user or config.activitypub_username or "admin"
        )
        self.user_store = UserStore(config.auth_dir, default_username)

        # Bootstrap: if a plaintext password is in config/env but no hash
        # exists on disk, hash it now.
        if config.auth_password:
            user = self.user_store.get(self.user_store.default_username)
            if user is None or not (user.user_dir / "password.hash").exists():
                self.user_store.set_password(
                    self.user_store.default_username, config.auth_password
                )
                logger.warning(
                    "Password for user %r was hashed from config/env and "
                    "written to disk. Remove the plaintext from your "
                    "configuration for security.",
                    self.user_store.default_username,
                )

        if not self.user_store.is_auth_enabled():
            # Auth not configured — nothing to wire up.
            self.auth_enabled = False
            return

        self.auth_enabled = True

        # Secret key
        self.secret_key = ensure_secret_key(config.auth_dir)

        # Session cookie settings
        self.config.update(
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            SESSION_COOKIE_SECURE=config.link.startswith("https://"),
            PERMANENT_SESSION_LIFETIME=timedelta(
                days=config.auth_session_lifetime_days
            ),
        )

        if not config.link.startswith("https://"):
            logger.warning(
                "Auth is enabled but config.link (%s) is not HTTPS. "
                "Session cookies will NOT be marked Secure.",
                config.link,
            )

        # CSRF protection
        from flask_wtf.csrf import CSRFProtect

        self.csrf = CSRFProtect(self)

        # Exempt signature-authenticated federation endpoints from CSRF.
        # These are registered by pubby (AP inbox) and webmentions before
        # _init_auth() is called.
        for rule in self.url_map.iter_rules():
            if rule.rule in ("/ap/inbox", "/webmentions") and "POST" in rule.methods:
                view_func = self.view_functions.get(rule.endpoint)
                if view_func:
                    self.csrf.exempt(view_func)

        # Rate limiter
        try:
            from flask_limiter import Limiter
            from flask_limiter.util import get_remote_address

            self.login_limiter = Limiter(
                get_remote_address,
                app=self,  # type: ignore
                storage_uri="memory://",
                default_limits=[],
            )
        except ImportError:
            logger.warning("flask-limiter unavailable; login rate limiting disabled")
            self.login_limiter = None

        # Auth routes
        register_auth_routes(self)  # type: ignore

        # Context processor
        @self.context_processor  # type: ignore
        def _auth_context():
            return {
                "auth_enabled": True,
                "current_user": current_user(),
            }
