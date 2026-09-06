import base64
import hashlib
import json
import logging
from pathlib import Path

import pytest

from apps.github_sync.app_client import (
    GithubAppAuthError,
    GithubAppClient,
    GithubAppConfig,
    GithubAppKeyError,
    GithubAppNotConfiguredError,
    GithubAppResponseError,
    parse_rsa_private_key,
)

pytestmark = pytest.mark.unit

DATA_DIR = Path(__file__).parent / "data"
PKCS1_PEM = (DATA_DIR / "test_app_key_pkcs1.pem").read_text(encoding="utf-8")
PKCS8_PEM = (DATA_DIR / "test_app_key_pkcs8.pem").read_text(encoding="utf-8")

APP_ID = "987654"
INSTALLATION_ID = 42001
INSTALLATION_TOKEN = "ghs_inmemory_installation_token_value"
FAKE_JWT = "fake-jwt-placeholder"


class FakeTransport:
    def __init__(self, handler):
        self.requests = []
        self._handler = handler

    def __call__(self, request):
        self.requests.append(request)
        return self._handler(request)


def installations_page(count, start=1):
    return [
        {"id": INSTALLATION_ID + offset, "account": {"login": f"acct{start + offset}"}}
        for offset in range(count)
    ]


def repositories_page(count, start=1, owner="cdjk"):
    return {
        "total_count": count,
        "repositories": [
            {
                "id": 500_000 + start + offset,
                "node_id": f"R_kgDOPage{start + offset:08d}",
                "name": f"repo-{start + offset}",
                "full_name": f"{owner}/repo-{start + offset}",
                "private": bool(offset % 2),
                "owner": {"login": owner},
            }
            for offset in range(count)
        ],
    }


def token_transport():
    return FakeTransport(
        lambda request: (201, {"token": INSTALLATION_TOKEN, "expires_at": "2026-01-01T00:00:00Z"})
    )


def test_list_open_issues_uses_the_installation_token_and_preserves_query_parameters():
    """GIT-003/DSC-009: starter-task sync reads open issue metadata via the App token."""

    def handler(request):
        if request["method"] == "POST":
            return 201, {"token": INSTALLATION_TOKEN}
        assert request["headers"]["Authorization"] == f"token {INSTALLATION_TOKEN}"
        assert request["url"].endswith(
            "/repos/doit-np/sewa-portal/issues?state=open&per_page=100&page=1"
        )
        return 200, [{"id": 1, "number": 1, "title": "Example"}]

    client = client_for(transport=FakeTransport(handler))

    assert client.list_open_issues(INSTALLATION_ID, "doit-np/sewa-portal") == [
        {"id": 1, "number": 1, "title": "Example"}
    ]


def test_get_public_user_uses_the_public_api_without_an_invalid_app_jwt():
    """GIT-010: public GitHub profiles do not send App JWTs to the public user endpoint."""

    def handler(request):
        assert "Authorization" not in request["headers"]
        assert request["url"] == "https://api.github.com/users/voidash"
        return 200, {"id": 1, "login": "voidash"}

    client = client_for(transport=FakeTransport(handler))

    assert client.get_public_user("voidash") == {"id": 1, "login": "voidash"}


def jwt_segment(segment: str):
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def b64u_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def client_for(pem=PKCS1_PEM, transport=None):
    return GithubAppClient(
        config=GithubAppConfig(app_id=APP_ID, private_key=pem),
        transport=transport if transport is not None else token_transport(),
    )


class TestAppJwt:
    def test_jwt_is_rs256_signed_with_expected_claims(self):
        """GIT-001/AUTH-008: the App JWT is RS256, identifies the App and is short-lived."""
        transport = FakeTransport(
            lambda request: (
                201,
                {"token": INSTALLATION_TOKEN, "expires_at": "2026-01-01T00:00:00Z"},
            )
        )
        client = client_for(transport=transport)

        client.mint_installation_token(INSTALLATION_ID)

        auth_header = transport.requests[0]["headers"]["Authorization"]
        assert auth_header.startswith("Bearer ")
        encoded = auth_header.removeprefix("Bearer ")
        header_b64, payload_b64, signature_b64 = encoded.split(".")
        assert jwt_segment(header_b64) == {"alg": "RS256", "typ": "JWT"}
        payload = jwt_segment(payload_b64)
        assert payload["iss"] == APP_ID
        assert payload["exp"] - payload["iat"] == 600
        assert payload["exp"] - 540 == payload["iat"] + 60

        signing_input = f"{header_b64}.{payload_b64}".encode()
        key = parse_rsa_private_key(PKCS1_PEM)
        k = (key.n.bit_length() + 7) // 8
        signature = int.from_bytes(b64u_decode(signature_b64), "big")
        em = pow(signature, key.e, key.n).to_bytes(k, "big")
        digest_info = (
            bytes.fromhex("3031300d060960864801650304020105000420")
            + hashlib.sha256(signing_input).digest()
        )
        expected = b"\x00\x01" + b"\xff" * (k - len(digest_info) - 3) + b"\x00" + digest_info
        assert em == expected

    def test_private_key_can_be_given_as_file_path(self):
        """GIT-001: the App private key resolves from a PEM file path as well as a literal."""
        client = client_for(pem=str(DATA_DIR / "test_app_key_pkcs8.pem"))

        token = client.mint_installation_token(INSTALLATION_ID)

        assert token == INSTALLATION_TOKEN


class TestInstallationTokens:
    def test_mint_posts_to_installation_access_tokens(self):
        """GIT-001: short-lived installation tokens are minted per installation via POST."""
        transport = token_transport()
        client = client_for(transport=transport)

        token = client.mint_installation_token(INSTALLATION_ID)

        request = transport.requests[0]
        assert request["method"] == "POST"
        assert request["url"] == (
            f"https://api.github.com/app/installations/{INSTALLATION_ID}/access_tokens"
        )
        assert request["headers"]["Accept"] == "application/vnd.github+json"
        assert token == INSTALLATION_TOKEN

    def test_mint_rejects_response_without_token(self):
        """GIT-001: a token response without token material fails with a typed error."""
        client = client_for(transport=FakeTransport(lambda request: (201, {"unexpected": True})))

        with pytest.raises(GithubAppResponseError):
            client.mint_installation_token(INSTALLATION_ID)

    def test_unconfigured_client_raises_typed_error(self, monkeypatch):
        """GIT-001: without GITHUB_APP_ID/GITHUB_APP_PRIVATE_KEY no API call is attempted."""
        monkeypatch.delenv("GITHUB_APP_ID", raising=False)
        monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
        transport = token_transport()
        client = GithubAppClient(
            config=GithubAppConfig(app_id="", private_key=""), transport=transport
        )

        assert client.is_configured is False
        with pytest.raises(GithubAppNotConfiguredError):
            client.mint_installation_token(INSTALLATION_ID)
        with pytest.raises(GithubAppNotConfiguredError):
            client.list_installations()
        assert transport.requests == []

    def test_unreadable_key_path_raises_typed_key_error(self):
        """GIT-001: an unusable private key fails loudly with a typed error."""
        client = client_for(pem=str(DATA_DIR / "does-not-exist.pem"))

        with pytest.raises(GithubAppKeyError):
            client.mint_installation_token(INSTALLATION_ID)

    def test_malformed_pem_raises_typed_key_error(self):
        """GIT-001: an unparseable private key fails loudly with a typed error."""
        garbage = "-----BEGIN RSA PRIVATE KEY-----\nnot base64 !!!\n-----END RSA PRIVATE KEY-----"
        client = client_for(pem=garbage)

        with pytest.raises(GithubAppKeyError):
            client.mint_installation_token(INSTALLATION_ID)


class TestApiListing:
    def test_list_installations_pages_through_three_pages_maximum(self):
        """GIT-001/GIT-003: installations listing pages at per_page=100 and stops at 3 pages."""
        transport = FakeTransport(lambda request: (200, installations_page(100)))
        client = client_for(transport=transport)

        installations = client.list_installations()

        assert len(installations) == 300
        assert len(transport.requests) == 3
        urls = [request["url"] for request in transport.requests]
        assert urls == [
            "https://api.github.com/app/installations?per_page=100&page=1",
            "https://api.github.com/app/installations?per_page=100&page=2",
            "https://api.github.com/app/installations?per_page=100&page=3",
        ]

    def test_list_installations_stops_on_short_page(self):
        """GIT-001: pagination stops once a page comes back short."""
        pages = {1: installations_page(100), 2: installations_page(37)}

        def handler(request):
            page = int(request["url"].rsplit("page=", 1)[1])
            return 200, pages[page]

        transport = FakeTransport(handler)
        client = client_for(transport=transport)

        installations = client.list_installations()

        assert len(installations) == 137
        assert len(transport.requests) == 2

    def test_list_installation_repositories_pages_and_uses_minted_token(self):
        """GIT-003: installation repositories are listed with a fresh installation token."""
        pages = {
            1: repositories_page(100),
            2: repositories_page(21, start=101, owner="cdjk"),
        }

        def handler(request):
            if request["method"] == "POST":
                return 201, {"token": INSTALLATION_TOKEN, "expires_at": "2026-01-01T00:00:00Z"}
            page = int(request["url"].rsplit("page=", 1)[1])
            return 200, pages[page]

        transport = FakeTransport(handler)
        client = client_for(transport=transport)

        repositories = client.list_installation_repositories(INSTALLATION_ID)

        assert len(repositories) == 121
        assert len(transport.requests) == 3
        list_requests = [request for request in transport.requests if request["method"] == "GET"]
        assert all(
            request["url"].startswith(
                "https://api.github.com/installation/repositories?per_page=100"
            )
            for request in list_requests
        )
        assert all(
            request["headers"]["Authorization"] == f"token {INSTALLATION_TOKEN}"
            for request in list_requests
        )


class TestErrorTyping:
    def test_transport_outage_raises_typed_response_error(self):
        """GIT-001: transport outages surface as typed GithubAppError, not raw OSError."""

        def broken(request):
            raise OSError("connection refused")

        client = client_for(transport=FakeTransport(broken))

        with pytest.raises(GithubAppResponseError):
            client.list_installations()

    def test_http_401_and_403_raise_auth_error(self):
        """GIT-001: rejected App credentials raise the typed auth error."""
        client = client_for(
            transport=FakeTransport(lambda request: (401, {"message": "Bad credentials"}))
        )

        with pytest.raises(GithubAppAuthError):
            client.list_installations()

    def test_other_http_errors_raise_response_error(self):
        """GIT-001: unexpected API statuses raise the typed response error."""
        client = client_for(transport=FakeTransport(lambda request: (500, {"message": "boom"})))

        with pytest.raises(GithubAppResponseError):
            client.list_installations()


class TestSecretHygiene:
    def test_tokens_and_jwt_never_reach_logs(self, caplog):
        """AUTH-008/GIT-011: token and JWT material never appears in application logs."""

        def handler(request):
            if request["method"] == "POST":
                return 201, {"token": INSTALLATION_TOKEN, "expires_at": "2026-01-01T00:00:00Z"}
            return 200, repositories_page(2)

        transport = FakeTransport(handler)
        client = client_for(transport=transport)
        real_jwt = client._app_jwt()

        with caplog.at_level(logging.DEBUG):
            client.mint_installation_token(INSTALLATION_ID)
            client.list_installation_repositories(INSTALLATION_ID)

        assert INSTALLATION_TOKEN not in caplog.text
        assert real_jwt not in caplog.text
        for request in transport.requests:
            assert request["headers"].get("Authorization") not in caplog.text


class TestConfigResolution:
    def test_config_reads_settings_then_environment(self, monkeypatch, settings):
        """GIT-001: GITHUB_APP_ID/GITHUB_APP_PRIVATE_KEY resolve from settings or env."""
        from apps.github_sync import app_client

        monkeypatch.delattr(settings, "GITHUB_APP_ID", raising=False)
        monkeypatch.delattr(settings, "GITHUB_APP_PRIVATE_KEY", raising=False)
        monkeypatch.setenv("GITHUB_APP_ID", "env-app-id")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", PKCS8_PEM)
        resolved = app_client.github_app_config()
        assert resolved.app_id == "env-app-id"
        assert resolved.private_key == PKCS8_PEM.strip()

        settings.GITHUB_APP_ID = "settings-app-id"
        settings.GITHUB_APP_PRIVATE_KEY = PKCS1_PEM
        resolved = app_client.github_app_config()
        assert resolved.app_id == "settings-app-id"
        assert resolved.private_key == PKCS1_PEM.strip()
