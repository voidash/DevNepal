import re

_REDACTED = "[REDACTED]"

_SECRET_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"ghs_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)(authorization\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(password\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(secret\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(token\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)\S+"),
)


def scrub_secrets(text: str) -> str:
    """NFR-OBS-01-U2: redact token/secret-shaped substrings before they reach a log sink."""
    scrubbed = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            scrubbed = pattern.sub(rf"\1{_REDACTED}", scrubbed)
        else:
            scrubbed = pattern.sub(_REDACTED, scrubbed)
    return scrubbed
