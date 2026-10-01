import hmac
import secrets
import time
from dataclasses import dataclass, field

from flask import g, session

from app.config import ADMIN_GROUP_NAME, SESSION_TTL_SECONDS
from app.repositories import single_table
from app.session_cart import get_or_create_cart_id


@dataclass(frozen=True)
class CurrentUser:
    session_id: str
    sub: str
    email: str
    groups: list[str] = field(default_factory=list)
    cart_id: str = ""
    csrf_token: str = ""

    @property
    def is_admin(self) -> bool:
        return ADMIN_GROUP_NAME in self.groups


def _destroy_current_session_record() -> None:
    session_id = session.get("session_id")
    if session_id:
        single_table.delete_session(session_id)


def login_user(sub: str, email: str, groups: list[str]) -> CurrentUser:
    """Creates a fresh server-side session, rotating away any pre-existing one (a
    session-fixation defense), and points the signed cookie at it via one opaque
    session_id -- never the raw Cognito tokens. Carries the guest cart_id forward
    (it already lives in the same cookie dict under "cart_id" and is never cleared
    here, so nothing special is needed for it to survive login) -- except for an
    admin, who has no shopping-cart concept at all: any pre-existing cart_id
    (e.g. left over from a customer who used the same browser) is dropped rather
    than adopted, so an admin session never ends up "with a cart"."""
    _destroy_current_session_record()

    is_admin = ADMIN_GROUP_NAME in groups
    if is_admin:
        session.pop("cart_id", None)
        cart_id = ""
    else:
        cart_id = get_or_create_cart_id()
    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS

    single_table.create_session(session_id, sub, email, groups, cart_id, csrf_token, expires_at)
    session["session_id"] = session_id

    return CurrentUser(
        session_id=session_id, sub=sub, email=email, groups=groups, cart_id=cart_id, csrf_token=csrf_token
    )


def logout_user() -> None:
    """True server-side logout: deleting the record kills the session everywhere
    immediately, unlike a signed/encrypted cookie alone, which a client could keep
    presenting until it expires on its own."""
    _destroy_current_session_record()
    session.pop("session_id", None)


def resolve_current_user() -> CurrentUser | None:
    session_id = session.get("session_id")
    if not session_id:
        return None

    item = single_table.get_session(session_id)
    if item is None:
        session.pop("session_id", None)
        return None

    # DynamoDB TTL deletion is best-effort/delayed -- storage hygiene only, not a
    # security control. The app enforces expiry itself, here.
    if int(item["expires_at"]) < int(time.time()):
        single_table.delete_session(session_id)
        session.pop("session_id", None)
        return None

    return CurrentUser(
        session_id=session_id,
        sub=item["cognito_sub"],
        email=item["email"],
        groups=list(item.get("groups", [])),
        cart_id=item.get("cart_id", ""),
        csrf_token=item.get("csrf_token", ""),
    )


def load_current_user() -> None:
    """Registered as app.before_request -- populates g.current_user on every
    request (None when there's no valid session), so routes/templates never
    resolve it themselves."""
    g.current_user = resolve_current_user()


def verify_csrf_token(submitted_token: str) -> bool:
    user = getattr(g, "current_user", None)
    if user is None or not submitted_token:
        return False
    return hmac.compare_digest(user.csrf_token, submitted_token)
