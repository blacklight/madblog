"""
Auth routes: /login and /logout.

Registered only when auth is enabled.
"""

from logging import getLogger
from urllib.parse import urlparse

from flask import Flask, flash, redirect, request, session, url_for

from ._decorators import current_user
from ._forms import LoginForm

logger = getLogger(__name__)


def _is_safe_redirect(target: str) -> bool:
    """Only allow relative paths as redirect targets."""
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc and target.startswith("/")


def register_auth_routes(app: Flask) -> None:
    """
    Register /login and /logout on the given app.
    """
    limiter = getattr(app, "login_limiter", None)

    def _login_route():
        if request.method == "GET":
            if current_user():
                return redirect("/")
            form = LoginForm()
            return (
                app.jinja_env.get_template("login.html").render(form=form, config=app.blog_config),
                200,
            )

        # POST
        form = LoginForm()
        if not form.validate_on_submit():
            flash("Invalid request.", "error")
            return (
                app.jinja_env.get_template("login.html").render(form=form, config=app.blog_config),
                400,
            )

        username = form.username.data.strip().lower()
        password = form.password.data

        if app.user_store.verify(username, password):
            session.clear()
            session["user"] = username
            session.permanent = True
            logger.info("Successful login for user %r", username)
            next_url = request.args.get("next", "/")
            if not _is_safe_redirect(next_url):
                next_url = "/"
            return redirect(next_url)

        logger.warning("Failed login attempt for user %r", username)
        flash("Invalid username or password.", "error")
        return (
            app.jinja_env.get_template("login.html").render(form=form, config=app.blog_config),
            401,
        )

    def _logout_route():
        session.clear()
        return redirect("/")

    # Register the login route with rate limiting on POST
    login_view = _login_route
    if limiter:
        from flask_limiter import Limiter

        login_view = limiter.limit(
            app.blog_config.auth_login_rate_limit, methods=["POST"]
        )(login_view)

    app.add_url_rule(
        "/login",
        endpoint="login_route",
        view_func=login_view,
        methods=["GET", "POST"],
    )

    app.add_url_rule(
        "/logout",
        endpoint="logout_route",
        view_func=_logout_route,
        methods=["POST"],
    )
