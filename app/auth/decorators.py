from functools import wraps

from flask import abort, g, redirect, request, url_for


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.current_user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """404, not 403: an anonymous or customer session gets the same response as a
    route that doesn't exist -- the admin area's existence is never revealed."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.current_user is None or not g.current_user.is_admin:
            abort(404)
        return view(*args, **kwargs)

    return wrapped
