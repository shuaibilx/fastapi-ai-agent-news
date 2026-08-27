"""Server-side deterministic redaction and credential blocking."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from langchain.agents.middleware.pii import (
    PIIMatch,
    detect_credit_card,
    detect_ip,
)


class SensitiveDataBlocked(ValueError):
    """Raised when a credential must never enter the model or memory."""

    def __init__(self, pii_type: str):
        super().__init__(f"检测到不允许提交的敏感信息: {pii_type}")
        self.pii_type = pii_type


_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_NATIONAL_ID_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_API_KEY_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:sk|ak|api[_-]?key)[-_=: ]+[A-Za-z0-9_\-.]{16,}"
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
_JWT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9_.-])"
)


def _regex_detector(pattern: re.Pattern[str], pii_type: str):
    def detect(content: str) -> list[PIIMatch]:
        return [
            PIIMatch(type=pii_type, value=match.group(), start=match.start(), end=match.end())
            for match in pattern.finditer(content)
        ]

    return detect


detect_phone = _regex_detector(_PHONE_PATTERN, "phone")
detect_national_id = _regex_detector(_NATIONAL_ID_PATTERN, "national_id")
detect_api_key = _regex_detector(_API_KEY_PATTERN, "api_key")
detect_bearer_token = _regex_detector(_BEARER_PATTERN, "bearer_token")
detect_jwt = _regex_detector(_JWT_PATTERN, "jwt")
detect_private_key = _regex_detector(_PRIVATE_KEY_PATTERN, "private_key")
detect_email = _regex_detector(_EMAIL_PATTERN, "email")

_PERSONAL_DETECTORS = (
    detect_email,
    detect_credit_card,
    detect_ip,
    detect_phone,
    detect_national_id,
)
_CREDENTIAL_DETECTORS = (
    detect_api_key,
    detect_bearer_token,
    detect_jwt,
    detect_private_key,
)


def _matches(content: str, detectors) -> list[PIIMatch]:
    matches: list[PIIMatch] = []
    for detector in detectors:
        matches.extend(detector(content))
    return sorted(matches, key=lambda match: (match["start"], match["end"]), reverse=True)


def sanitize_text(content: str) -> str:
    """Block credentials, then redact supported personal information."""
    credentials = _matches(content, _CREDENTIAL_DETECTORS)
    if credentials:
        raise SensitiveDataBlocked(credentials[0]["type"])

    redacted = content
    for match in _matches(content, _PERSONAL_DETECTORS):
        redacted = (
            redacted[: match["start"]]
            + f"[REDACTED_{match['type'].upper()}]"
            + redacted[match["end"] :]
        )
    return redacted


def sanitize_value(value: Any) -> Any:
    """Recursively sanitize response/artifact values without mutating them."""
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, Mapping):
        return {key: sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_value(item) for item in value)
    return value
