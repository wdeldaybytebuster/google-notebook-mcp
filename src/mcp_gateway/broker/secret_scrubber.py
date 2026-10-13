"""Redaction utility preventing credential and session secret leaks into logs and IPC frames."""

from __future__ import annotations

import re
from typing import Any

PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)\bBearer\s+(?:ya29\.[A-Za-z0-9_\-\.]+|[A-Za-z0-9_\-\.]{10,})"),
    re.compile(r"(?i)\bSID=[A-Za-z0-9_\-\.]+"),
    re.compile(r"(?i)\bHSID=[A-Za-z0-9_]+"),
    re.compile(r"(?i)\bSSID=[A-Za-z0-9_]+"),
    re.compile(r"(?i)__Secure-1PSID=[A-Za-z0-9_\-\.]+"),
    re.compile(r"(?i)\bSAPISID=[A-Za-z0-9_\-\.]+"),
    re.compile(r"ya29\.[A-Za-z0-9_\-\.]+"),
    re.compile(r"SNlM0e[\"\s]*[:=][\"\s]*[A-Za-z0-9_\-\.]+"),
    re.compile(r"FdrFJe[\"\s]*[:=][\"\s]*[A-Za-z0-9_\-\.]+"),
    re.compile(r"(?i)\bBearer\s+\[REDACTED\]"),
]


def scrub(text: str) -> str:
    """Scrubs known auth tokens, cookies, and session secrets from a string."""
    result = text
    for pattern in PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def scrub_dict(obj: dict[str, Any]) -> dict[str, Any]:
    """Recursively scrubs strings within dictionaries and nested collections."""
    scrubbed: dict[str, Any] = {}
    for key, value in obj.items():
        if isinstance(value, str):
            scrubbed[key] = scrub(value)
        elif isinstance(value, dict):
            scrubbed[key] = scrub_dict(value)
        elif isinstance(value, list):
            scrubbed[key] = [
                scrub(item)
                if isinstance(item, str)
                else (scrub_dict(item) if isinstance(item, dict) else item)
                for item in value
            ]
        else:
            scrubbed[key] = value
    return scrubbed


def assert_clean(text: str) -> None:
    """Raises ValueError if any sensitive tokens or session cookies are detected."""
    if scrub(text) != text:
        raise ValueError("[SECRET DETECTED]")
