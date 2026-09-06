import hashlib
import ipaddress
import logging
import math
import time
from dataclasses import dataclass

from django.core.cache import cache

logger = logging.getLogger(__name__)

LOGIN_ATTEMPT_LIMIT = 5
LOGIN_WINDOW_SECONDS = 900
MFA_VERIFICATION_LIMIT = 5
MFA_VERIFICATION_WINDOW_SECONDS = 300
GITHUB_CONNECT_LIMIT = 10
GITHUB_CONNECT_WINDOW_SECONDS = 300
GITHUB_CALLBACK_LIMIT = 10
GITHUB_CALLBACK_WINDOW_SECONDS = 300


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0
    first_denial: bool = False


def rate_limit_key(surface: str, subject: str) -> str:
    digest = hashlib.sha256(f"{surface}\x00{subject}".encode()).hexdigest()
    return f"accounts.auth_rate_limit.v1:{surface}:{digest}"


def request_subjects(request, principal: str) -> tuple[str, str]:
    remote_addr = _client_ip(request)
    session_key = str(request.session.session_key or "").strip()
    client_subject = f"ip:{remote_addr}" if remote_addr else f"session:{session_key or 'anonymous'}"
    return client_subject, f"principal:{principal.strip().casefold() or 'anonymous'}"


def _client_ip(request) -> str:
    """SEC-006: trust Cloudflare's client address only through the local tunnel.

    The development tunnel connects to Django from loopback, so using only
    ``REMOTE_ADDR`` would put every public visitor in one shared rate-limit
    bucket. A direct remote request cannot opt into the forwarded address path.
    """
    remote_addr = str(request.META.get("REMOTE_ADDR") or "").strip()
    try:
        remote_ip = ipaddress.ip_address(remote_addr)
    except ValueError:
        return remote_addr
    if not remote_ip.is_loopback:
        return remote_addr

    forwarded = str(request.META.get("HTTP_CF_CONNECTING_IP") or "").strip()
    try:
        return str(ipaddress.ip_address(forwarded)) if forwarded else remote_addr
    except ValueError:
        logger.warning("Ignored malformed CF-Connecting-IP from the local tunnel")
        return remote_addr


def check_rate_limit(
    request, *, surface: str, principal: str, limit: int, window_seconds: int
) -> RateLimitDecision:
    decisions = tuple(
        _check_subject(surface, subject, limit=limit, window_seconds=window_seconds)
        for subject in request_subjects(request, principal)
    )
    denied = tuple(decision for decision in decisions if not decision.allowed)
    if not denied:
        return RateLimitDecision(allowed=True)
    return RateLimitDecision(
        allowed=False,
        retry_after=max(decision.retry_after for decision in denied),
        first_denial=any(decision.first_denial for decision in denied),
    )


def consume_rate_limit(
    request, *, surface: str, principal: str, limit: int, window_seconds: int
) -> RateLimitDecision:
    decisions = tuple(
        _consume_subject(surface, subject, limit=limit, window_seconds=window_seconds)
        for subject in request_subjects(request, principal)
    )
    denied = tuple(decision for decision in decisions if not decision.allowed)
    if not denied:
        return RateLimitDecision(allowed=True)
    return RateLimitDecision(
        allowed=False,
        retry_after=max(decision.retry_after for decision in denied),
        first_denial=any(decision.first_denial for decision in denied),
    )


def _check_subject(
    surface: str, subject: str, *, limit: int, window_seconds: int
) -> RateLimitDecision:
    key = rate_limit_key(surface, subject)
    now = time.time()
    try:
        count = cache.get(key)
        if count is None or int(count) < limit:
            return RateLimitDecision(allowed=True)
        retry_after = _retry_after(cache.get(_reset_key(key)), now, window_seconds)
        return RateLimitDecision(
            allowed=False,
            retry_after=retry_after,
            first_denial=cache.add(_denial_key(key), True, timeout=retry_after),
        )
    except Exception:
        logger.exception("Authentication rate-limit cache access failed for surface=%s", surface)
        return RateLimitDecision(allowed=False, retry_after=window_seconds)


def _consume_subject(
    surface: str, subject: str, *, limit: int, window_seconds: int
) -> RateLimitDecision:
    key = rate_limit_key(surface, subject)
    reset_key = _reset_key(key)
    now = time.time()
    try:
        if cache.add(key, 1, timeout=window_seconds):
            cache.add(reset_key, now + window_seconds, timeout=window_seconds)
            return RateLimitDecision(allowed=True)
        count = cache.incr(key)
        if count <= limit:
            return RateLimitDecision(allowed=True)
        retry_after = _retry_after(cache.get(reset_key), now, window_seconds)
        return RateLimitDecision(
            allowed=False,
            retry_after=retry_after,
            first_denial=cache.add(_denial_key(key), True, timeout=retry_after),
        )
    except Exception:
        logger.exception("Authentication rate-limit cache access failed for surface=%s", surface)
        return RateLimitDecision(allowed=False, retry_after=window_seconds)


def _reset_key(key: str) -> str:
    return f"{key}:reset"


def _denial_key(key: str) -> str:
    return f"{key}:denied"


def _retry_after(reset_at, now: float, window_seconds: int) -> int:
    try:
        remaining = float(reset_at) - now
    except (TypeError, ValueError):
        return window_seconds
    return max(1, min(window_seconds, math.ceil(remaining)))
