import base64
import hashlib
import hmac
import os

from app.aws_clients import cognito_idp_client


def _client_id() -> str:
    return os.environ["COGNITO_CLIENT_ID"]


def _client_secret() -> str:
    return os.environ["COGNITO_CLIENT_SECRET"]


def _user_pool_id() -> str:
    return os.environ["COGNITO_USER_POOL_ID"]


def secret_hash(username: str) -> str:
    """Required on every user-level Cognito call for a confidential (secret-bearing)
    app client. Note .digest() + base64 -- not .hexdigest() -- a common mistake."""
    digest = hmac.new(_client_secret().encode(), (username + _client_id()).encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def sign_up(email: str, password: str) -> str:
    """Registers a new, unconfirmed user. Returns the Cognito sub (UUID)."""
    response = cognito_idp_client().sign_up(
        ClientId=_client_id(),
        Username=email,
        Password=password,
        SecretHash=secret_hash(email),
        UserAttributes=[{"Name": "email", "Value": email}],
    )
    return response["UserSub"]


def confirm_sign_up(email: str, confirmation_code: str) -> None:
    cognito_idp_client().confirm_sign_up(
        ClientId=_client_id(),
        Username=email,
        ConfirmationCode=confirmation_code,
        SecretHash=secret_hash(email),
    )


def resend_confirmation_code(email: str) -> None:
    cognito_idp_client().resend_confirmation_code(
        ClientId=_client_id(), Username=email, SecretHash=secret_hash(email)
    )


def login(email: str, password: str) -> dict:
    """Returns the AuthenticationResult dict (AccessToken/IdToken/RefreshToken/ExpiresIn).
    The refresh token is intentionally never persisted by callers (see README/plan)."""
    response = cognito_idp_client().initiate_auth(
        ClientId=_client_id(),
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": email,
            "PASSWORD": password,
            "SECRET_HASH": secret_hash(email),
        },
    )
    return response["AuthenticationResult"]


def get_user_sub(access_token: str) -> str:
    response = cognito_idp_client().get_user(AccessToken=access_token)
    attributes = {a["Name"]: a["Value"] for a in response["UserAttributes"]}
    return attributes["sub"]


def global_sign_out(access_token: str) -> None:
    cognito_idp_client().global_sign_out(AccessToken=access_token)


def forgot_password(email: str) -> None:
    cognito_idp_client().forgot_password(ClientId=_client_id(), Username=email, SecretHash=secret_hash(email))


def confirm_forgot_password(email: str, confirmation_code: str, new_password: str) -> None:
    cognito_idp_client().confirm_forgot_password(
        ClientId=_client_id(),
        Username=email,
        ConfirmationCode=confirmation_code,
        Password=new_password,
        SecretHash=secret_hash(email),
    )


def admin_list_groups(email: str) -> list[str]:
    """IAM-authorized (AdminListGroupsForUser), not token-authorized -- this is how the
    app learns group membership. The app never decodes a JWT anywhere."""
    response = cognito_idp_client().admin_list_groups_for_user(UserPoolId=_user_pool_id(), Username=email)
    return [group["GroupName"] for group in response["Groups"]]


def _summarize_user(attributes: dict, username: str, status: str, enabled: bool) -> dict:
    return {
        "sub": attributes.get("sub", username),
        "email": attributes.get("email", ""),
        "status": status,
        "enabled": enabled,
    }


def list_users() -> list[dict]:
    """Admin CRM screen -- every registered user's sub/email/status, IAM-authorized
    (ListUsers). Paginated defensively even though this PoC's user base is small."""
    client = cognito_idp_client()
    users = []
    pagination_token = None
    while True:
        kwargs = {"UserPoolId": _user_pool_id()}
        if pagination_token:
            kwargs["PaginationToken"] = pagination_token
        response = client.list_users(**kwargs)
        for user in response["Users"]:
            attributes = {a["Name"]: a["Value"] for a in user["Attributes"]}
            users.append(_summarize_user(attributes, user["Username"], user["UserStatus"], user["Enabled"]))
        pagination_token = response.get("PaginationToken")
        if not pagination_token:
            break
    return users


def get_user(email: str) -> dict | None:
    """AdminGetUser by email -- Cognito accepts the aliased username_attributes
    value here just like it does for InitiateAuth/ForgotPassword (see sign_up's
    own Username=email usage), so this needs no separate sub-to-username lookup.
    IAM-authorized, used for the admin customer detail screen."""
    client = cognito_idp_client()
    try:
        response = client.admin_get_user(UserPoolId=_user_pool_id(), Username=email)
    except client.exceptions.UserNotFoundException:
        return None
    attributes = {a["Name"]: a["Value"] for a in response["UserAttributes"]}
    return _summarize_user(attributes, response["Username"], response["UserStatus"], response["Enabled"])
