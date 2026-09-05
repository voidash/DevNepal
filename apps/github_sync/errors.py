class GithubSyncError(Exception):
    """Base class for github_sync pipeline errors."""


class WebhookSignatureError(GithubSyncError):
    """GIT-004: a webhook delivery failed signature validation (missing/invalid/malformed)."""


class UnsupportedEventError(GithubSyncError):
    """GIT-007/D7: an event type outside the configured verified set was submitted for crediting."""


class WebhookReplayError(GithubSyncError):
    """GIT-005: a delivery whose timestamp falls outside the replay window was rejected."""


class ConnectionNotFoundError(GithubSyncError):
    """GIT-011: disconnect was requested for a user with no provider connection."""


class ReconciliationError(GithubSyncError):
    """GIT-006: a repository reconciliation sweep could not complete safely."""


class GithubAppError(GithubSyncError):
    """GIT-001: base failure for GitHub App API operations."""


class GithubAppNotConfiguredError(GithubAppError):
    """GIT-001: GITHUB_APP_ID/GITHUB_APP_PRIVATE_KEY are absent or empty."""


class GithubAppKeyError(GithubAppError):
    """GIT-001: the configured GitHub App private key is unreadable or unparseable."""


class GithubAppAuthError(GithubAppError):
    """GIT-001: GitHub rejected the App JWT or the installation token credentials."""


class GithubAppResponseError(GithubAppError):
    """GIT-001: a GitHub App API call failed in transport or returned an unusable response."""
