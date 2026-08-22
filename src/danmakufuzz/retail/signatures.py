from __future__ import annotations

import re


_WHITESPACE_RE = re.compile(r"\s+")
_THREAD_RE = re.compile(r"\(thread\s+[0-9a-fA-F]+\)")
_AT_ADDRESS_RE = re.compile(r"\bat address\s+(?:0x)?[0-9a-fA-F]+\b")
_ACCESS_TO_RE = re.compile(r"\b(read|write|execute)\s+access\s+to\s+(?:0x)?[0-9a-fA-F]+\b")
_IP_RE = re.compile(r"\bip=(?:0x)?[0-9a-fA-F]+\b")
_ADDR_ASSIGNMENT_RE = re.compile(r"\baddr=(?:0x)?[0-9a-fA-F]+\b")


def normalize_signature_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _WHITESPACE_RE.sub(" ", value.strip())
    return normalized or None


def normalize_wine_primary_signature(value: str | None) -> str | None:
    normalized = normalize_signature_text(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    lowered = _THREAD_RE.sub("(thread <thread>)", lowered)
    lowered = _AT_ADDRESS_RE.sub("at address <addr>", lowered)
    lowered = _ACCESS_TO_RE.sub(lambda match: f"{match.group(1)} access to <value>", lowered)
    lowered = _IP_RE.sub("ip=<addr>", lowered)
    lowered = _ADDR_ASSIGNMENT_RE.sub("addr=<addr>", lowered)
    lowered = _WHITESPACE_RE.sub(" ", lowered).strip()
    return lowered or None


def retail_signature_key(classification: str | None, primary_signature: str | None) -> str:
    normalized_classification = classification or "unknown"
    normalized_signature = normalize_wine_primary_signature(primary_signature)
    if normalized_signature is None:
        return normalized_classification
    return f"{normalized_classification}:{normalized_signature}"
