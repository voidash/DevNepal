import pytest

from apps.observability.scrub import scrub_secrets

pytestmark = pytest.mark.unit


def test_github_personal_access_token_is_redacted():
    """NFR-OBS-01-U2: a GitHub PAT-shaped token is stripped before it reaches a log sink."""
    text = "connected using ghp_abcdefghijklmnopqrstuvwxyz012345"
    assert "ghp_" not in scrub_secrets(text)
    assert "[REDACTED]" in scrub_secrets(text)


def test_bearer_authorization_header_is_redacted():
    """NFR-OBS-01-U2: an Authorization bearer header value is stripped from logs."""
    text = "Authorization: Bearer sk-live-abcdef1234567890"
    scrubbed = scrub_secrets(text)
    assert "abcdef1234567890" not in scrubbed


def test_password_and_secret_key_value_pairs_are_redacted():
    """NFR-OBS-01-U2: password/secret/token key=value pairs never reach a log sink."""
    scrubbed = scrub_secrets("password=hunter2 secret: s3cr3t token=abc123")
    assert "hunter2" not in scrubbed
    assert "s3cr3t" not in scrubbed
    assert "abc123" not in scrubbed


def test_ordinary_text_is_left_untouched():
    """NFR-OBS-01-U2: the scrubber only redacts secret-shaped substrings, nothing else."""
    text = "ministry.created for the National Service Directory"
    assert scrub_secrets(text) == text
