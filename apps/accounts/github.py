"""GitHub OAuth identity flows (AUTH-001, AUTH-002, GIT-002).

Access tokens cross these functions in memory only. They are never written to
models, sessions, logs, or audit payloads (AUTH-008).
"""

import json
import logging
import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core import signing

logger = logging.getLogger(__name__)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_CODE_EXCHANGE_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_API_URL = "https://api.github.com/user"
GITHUB_USER_EMAILS_API_URL = "https://api.github.com/user/emails"

OAUTH_SCOPE = "read:user user:email"
STATE_SESSION_KEY = "github_connect_state"
STATE_MAX_AGE_SECONDS = 600
HTTP_TIMEOUT_SECONDS = 10
USER_AGENT = "DevNepal"

_FALSE_ENV_VALUES = frozenset({"", "0", "false", "no", "off"})


class GitHubConnectError(Exception):
    """Base failure for GitHub identity connection (AUTH-001/AUTH-002)."""


class GitHubTokenExchangeError(GitHubConnectError):
    """The authorization code could not be exchanged for an access token."""


class GitHubProfileError(GitHubConnectError):
    """The GitHub identity or email list could not be fetched."""


@dataclass(frozen=True)
class GitHubOAuthConfig:
    client_id: str
    client_secret: str
    enabled: bool


def oauth_config() -> GitHubOAuthConfig:
    """Resolve GITHUB_CLIENT_ID/GITHUB_CLIENT_SECRET/GITHUB_OAUTH_ENABLED.

    Settings win; environment variables are the fallback. Without credentials the
    provider stays disabled even if the flag is switched on (AUTH-001 policy).
    """
    client_id = _credential("GITHUB_CLIENT_ID")
    client_secret = _credential("GITHUB_CLIENT_SECRET")
    flag = getattr(settings, "GITHUB_OAUTH_ENABLED", None)
    if flag is None:
        flag = _env_flag("GITHUB_OAUTH_ENABLED")
    enabled = bool(client_id) and bool(client_secret) and flag is not False
    return GitHubOAuthConfig(client_id=client_id, client_secret=client_secret, enabled=enabled)


def _credential(name: str) -> str:
    value = getattr(settings, name, None)
    if value is None:
        value = os.environ.get(name, "")
    return str(value or "")


def _env_flag(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return True
    return raw.strip().lower() not in _FALSE_ENV_VALUES


def generate_state() -> str:
    """AUTH-002: create a signed, single-use state token bound to SECRET_KEY."""
    return signing.dumps(secrets.token_urlsafe(32))


def verify_state(state_param, session) -> bool:
    """Consume the session state and require an exact, unexpired signature match."""
    stored = session.get(STATE_SESSION_KEY)
    session.pop(STATE_SESSION_KEY, None)
    if not state_param or not stored or state_param != stored:
        return False
    try:
        signing.loads(state_param, max_age=STATE_MAX_AGE_SECONDS)
    except signing.BadSignature:
        return False
    return True


def authorize_url(config: GitHubOAuthConfig, state: str) -> str:
    query = urlencode({"client_id": config.client_id, "scope": OAUTH_SCOPE, "state": state})
    return f"{GITHUB_AUTHORIZE_URL}?{query}"


def parse_scopes(raw_scope: str) -> list[str]:
    return [scope for scope in raw_scope.replace(",", " ").split() if scope]


def exchange_code(config: GitHubOAuthConfig, code: str) -> tuple[str, list[str]]:
    """Exchange the authorization code for an in-memory token plus granted scopes."""
    body = json.dumps(
        {"client_id": config.client_id, "client_secret": config.client_secret, "code": code}
    ).encode()
    request = Request(
        GITHUB_CODE_EXCHANGE_URL,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    payload = _request_json(request, GitHubTokenExchangeError)
    token = None
    error = True
    if isinstance(payload, dict):
        token = payload.get("access_token")
        error = payload.get("error")
    if not token or error:
        raise GitHubTokenExchangeError("GitHub rejected the authorization code")
    return str(token), parse_scopes(str(payload.get("scope", "")))


def fetch_github_user(access_token: str) -> dict:
    request = _identity_request(GITHUB_USER_API_URL, access_token)
    profile = _request_json(request, GitHubProfileError)
    if not isinstance(profile, dict):
        raise GitHubProfileError("GitHub identity response was not an object")
    return profile


def fetch_user_emails(access_token: str) -> list[dict]:
    request = _identity_request(GITHUB_USER_EMAILS_API_URL, access_token)
    emails = _request_json(request, GitHubProfileError)
    if not isinstance(emails, list):
        return []
    return [email for email in emails if isinstance(email, dict)]


def _identity_request(url: str, access_token: str) -> Request:
    return Request(  # noqa: S310
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": USER_AGENT,
        },
    )


def _request_json(request: Request, error_type: type[GitHubConnectError]) -> dict | list:
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310
            return json.loads(response.read().decode())
    except GitHubConnectError:
        raise
    except (OSError, ValueError) as exc:
        logger.exception("GitHub OAuth HTTP call failed (url=%s)", request.full_url)
        raise error_type("GitHub identity request could not be completed") from exc
