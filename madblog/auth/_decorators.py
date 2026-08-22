"""
Auth decorators and helpers.
"""

from functools import wraps

from flask import current_app, redirect, request, session, url_for

from ._users import User


def current_user() -> "User | None":
    """
    Return the currently authenticated User, or None.
    """
    name = session.get("user")
    if not name:
        return None
    store = getattr(current_app, "user_store", None)
    if store is None:
        return None
    return store.get(name)


def login_required(view):
    """
    Decorator: redirect to login if no authenticated session.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login_route", next=request.path))
        return view(*args, **kwargs)

    return wrapped
