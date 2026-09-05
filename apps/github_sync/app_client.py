"""GitHub App API client (GIT-001, GIT-003, GIT-011; AUTH-008).

The App JWT and installation tokens cross this module in memory only: they are
returned to the caller, never stored on models, never rendered, and never
logged. Transport is injectable (callable(request_dict) -> (status, json)) so
tests and operations can substitute the network; the default transport uses
urllib with a 10 second timeout.
"""

import base64
import hashlib
import importlib
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote

from django.conf import settings

from apps.github_sync.errors import (
    GithubAppAuthError,
    GithubAppError,
    GithubAppKeyError,
    GithubAppNotConfiguredError,
    GithubAppResponseError,
)

logger = logging.getLogger(__name__)

GITHUB_API_ROOT = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
USER_AGENT = "DevNepal"
HTTP_TIMEOUT_SECONDS = 10
PAGE_SIZE = 100
MAX_PAGES = 3
JWT_LIFETIME_SECONDS = 540
JWT_CLOCK_SKEW_SECONDS = 60

SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")

Transport = Callable[[dict], tuple[int, object]]


class RsaPrivateKey(NamedTuple):
    n: int
    e: int
    d: int


@dataclass(frozen=True)
class GithubAppConfig:
    app_id: str
    private_key: str

    @property
    def enabled(self) -> bool:
        return bool(self.app_id) and bool(self.private_key)


def github_app_config() -> GithubAppConfig:
    """GIT-001: resolve GITHUB_APP_ID/GITHUB_APP_PRIVATE_KEY from settings, then env."""
    return GithubAppConfig(
        app_id=_credential("GITHUB_APP_ID"),
        private_key=_credential("GITHUB_APP_PRIVATE_KEY"),
    )


def _credential(name: str) -> str:
    value = getattr(settings, name, None)
    if value is None:
        value = os.environ.get(name, "")
    return str(value or "").strip()


def _transport_hook() -> Transport | None:
    hook = getattr(settings, "GITHUB_APP_TRANSPORT", None)
    if hook is None:
        return None
    if callable(hook):
        return hook
    if isinstance(hook, str):
        module_name, _, attribute = hook.rpartition(".")
        return getattr(importlib.import_module(module_name), attribute)
    raise GithubAppError("GITHUB_APP_TRANSPORT must be a callable or dotted path")


def default_transport(request: dict) -> tuple[int, object]:
    body = request.get("body")
    data = body.encode("utf-8") if body is not None else None
    http_request = urllib_request.Request(  # noqa: S310
        request["url"],
        data=data,
        headers=dict(request["headers"]),
        method=request["method"],
    )
    try:
        with urllib_request.urlopen(http_request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310
            status = response.status
            raw = response.read()
    except urllib_error.HTTPError as exc:
        status = exc.code
        try:
            raw = exc.read()
        except OSError:
            raw = b""
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        logger.warning(
            "GitHub App API unreachable (method=%s path=%s)",
            request["method"],
            request["url"],
        )
        raise GithubAppResponseError("GitHub App API could not be reached") from exc
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        payload = None
    return status, payload


def installation_granted_scopes(installation: dict) -> list[str]:
    permissions = installation.get("permissions")
    if not isinstance(permissions, dict):
        return []
    return sorted(f"{name}:{level}" for name, level in permissions.items())


def parse_rsa_private_key(pem: str) -> RsaPrivateKey:
    """GIT-001: parse an unencrypted PKCS#1 or PKCS#8 PEM into RSA primitives."""
    text = pem.strip()
    if text.startswith("-----BEGIN ENCRYPTED PRIVATE KEY-----"):
        raise GithubAppKeyError("encrypted GitHub App private keys are not supported")
    der = _pem_der_body(text)
    if text.startswith("-----BEGIN PRIVATE KEY-----"):
        der = _pkcs8_private_key_der(der)
    elif not text.startswith("-----BEGIN RSA PRIVATE KEY-----"):
        raise GithubAppKeyError("unsupported GitHub App private key PEM header")
    return _pkcs1_rsa_private_key(der)


def _pem_der_body(pem: str) -> bytes:
    body = "".join(line.strip() for line in pem.splitlines() if "-----" not in line)
    try:
        return base64.b64decode(body, validate=True)
    except ValueError as exc:
        raise GithubAppKeyError("GitHub App private key is not valid PEM") from exc


def _der_read(data: bytes, offset: int) -> tuple[int, bytes, int]:
    if offset + 2 > len(data):
        raise GithubAppKeyError("truncated DER structure in GitHub App private key")
    tag = data[offset]
    offset += 1
    first = data[offset]
    offset += 1
    if first < 0x80:
        length = first
    else:
        count = first & 0x7F
        end = offset + count
        if end > len(data):
            raise GithubAppKeyError("truncated DER structure in GitHub App private key")
        length = int.from_bytes(data[offset:end], "big")
        offset = end
    if offset + length > len(data):
        raise GithubAppKeyError("truncated DER structure in GitHub App private key")
    return tag, data[offset : offset + length], offset + length


def _pkcs8_private_key_der(der: bytes) -> bytes:
    tag, body, _ = _der_read(der, 0)
    if tag != 0x30:
        raise GithubAppKeyError("GitHub App PKCS#8 key is not a DER sequence")
    offset = 0
    while offset < len(body):
        child_tag, value, offset = _der_read(body, offset)
        if child_tag == 0x04:
            return value
    raise GithubAppKeyError("GitHub App PKCS#8 key carries no private key octet")


def _pkcs1_rsa_private_key(der: bytes) -> RsaPrivateKey:
    tag, body, _ = _der_read(der, 0)
    if tag != 0x30:
        raise GithubAppKeyError("GitHub App private key is not a DER sequence")
    integers: list[int] = []
    offset = 0
    while offset < len(body) and len(integers) < 4:
        child_tag, value, offset = _der_read(body, offset)
        if child_tag != 0x02:
            raise GithubAppKeyError("GitHub App private key has an unexpected DER field")
        integers.append(int.from_bytes(value, "big"))
    if len(integers) < 4:
        raise GithubAppKeyError("GitHub App private key is missing RSA primitives")
    version, n, e, d = integers
    if version != 0 or n <= 0 or e <= 0 or d <= 0:
        raise GithubAppKeyError("GitHub App private key has invalid RSA primitives")
    return RsaPrivateKey(n=n, e=e, d=d)


def sign_rs256(key: RsaPrivateKey, message: bytes) -> bytes:
    digest_info = SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(message).digest()
    k = (key.n.bit_length() + 7) // 8
    padding_len = k - len(digest_info) - 3
    if padding_len < 8:
        raise GithubAppKeyError("GitHub App RSA key is too small for RS256 signing")
    em = b"\x00\x01" + b"\xff" * padding_len + b"\x00" + digest_info
    signature = pow(int.from_bytes(em, "big"), key.d, key.n)
    return signature.to_bytes(k, "big")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_app_jwt(app_id: str, private_key_pem: str, *, now: float | None = None) -> str:
    """GIT-001: sign a short-lived RS256 App JWT; the result stays in memory only."""
    key = parse_rsa_private_key(private_key_pem)
    issued = int(now if now is not None else time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iat": issued - JWT_CLOCK_SKEW_SECONDS,
        "exp": issued + JWT_LIFETIME_SECONDS,
        "iss": app_id,
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    )
    return signing_input + "." + _b64url(sign_rs256(key, signing_input.encode("ascii")))


class GithubAppClient:
    """GIT-001/GIT-003: GitHub App operations with injectable transport (AUTH-008)."""

    def __init__(
        self,
        *,
        config: GithubAppConfig | None = None,
        transport: Transport | None = None,
    ):
        self._config = config if config is not None else github_app_config()
        self._transport = transport if transport is not None else default_transport

    @property
    def is_configured(self) -> bool:
        return self._config.enabled

    def list_installations(self) -> list[dict]:
        return self._paged_get("/app/installations", _extract_items)

    def list_installation_repositories(self, installation_id: int) -> list[dict]:
        token = self.mint_installation_token(installation_id)
        return self._paged_get("/installation/repositories", _extract_repositories, token=token)

    def list_open_issues(self, installation_id: int, full_name: str) -> list[dict]:
        """GIT-003/DSC-009: retrieve open issues through an in-memory App token."""
        repository = _repository_path(full_name)
        token = self.mint_installation_token(installation_id)
        return self._paged_get(
            f"/repos/{repository}/issues?state=open", _extract_items, token=token
        )

    def mint_installation_token(self, installation_id: int) -> str:
        """GIT-001: mint a short-lived installation token, returned in memory only."""
        payload = self._request("POST", f"/app/installations/{installation_id}/access_tokens")
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise GithubAppResponseError("GitHub App token response carried no token material")
        return token

    def _paged_get(self, path: str, extract: Callable[[object], list[dict]], *, token=None):
        items: list[dict] = []
        separator = "&" if "?" in path else "?"
        for page in range(1, MAX_PAGES + 1):
            payload = self._request(
                "GET", f"{path}{separator}per_page={PAGE_SIZE}&page={page}", token=token
            )
            batch = extract(payload)
            items.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
        return items

    def _request(self, method: str, path: str, *, token: str | None = None) -> object:
        if not self.is_configured:
            raise GithubAppNotConfiguredError("GitHub App credentials are not configured")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": USER_AGENT,
            "Authorization": f"token {token}" if token else f"Bearer {self._app_jwt()}",
        }
        payload = self._dispatch(
            {
                "method": method,
                "url": f"{GITHUB_API_ROOT}{path}",
                "headers": headers,
                "body": None,
            }
        )
        logger.debug(
            "GitHub App API call completed (method=%s path=%s)", method, path.split("?")[0]
        )
        return payload

    def _dispatch(self, request: dict) -> object:
        try:
            status, payload = self._transport(request)
        except GithubAppError:
            raise
        except Exception as exc:
            raise GithubAppResponseError("GitHub App transport call failed") from exc
        if isinstance(status, bool) or not isinstance(status, int):
            raise GithubAppResponseError("GitHub App transport returned a malformed status")
        if 200 <= status < 300:
            return payload
        if status in (401, 403):
            raise GithubAppAuthError(f"GitHub App credentials rejected (status {status})")
        raise GithubAppResponseError(f"GitHub App API request failed (status {status})")

    def _app_jwt(self) -> str:
        return build_app_jwt(self._config.app_id, _load_private_key(self._config.private_key))


def _load_private_key(value: str) -> str:
    text = value.strip()
    if not text:
        raise GithubAppKeyError("GitHub App private key is empty")
    if text.startswith("-----BEGIN"):
        return text
    path = os.path.expanduser(text)
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError as exc:
        raise GithubAppKeyError("GitHub App private key file could not be read") from exc


def _extract_items(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _extract_repositories(payload: object) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("repositories"), list):
        return [item for item in payload["repositories"] if isinstance(item, dict)]
    return []


def _repository_path(full_name: str) -> str:
    pieces = [piece for piece in str(full_name).split("/") if piece]
    if len(pieces) != 2:
        raise GithubAppResponseError("repository name was malformed")
    return "/".join(quote(piece, safe="") for piece in pieces)


def github_app_client() -> GithubAppClient:
    """Build the App client, honoring an optional GITHUB_APP_TRANSPORT hook."""
    return GithubAppClient(transport=_transport_hook())
