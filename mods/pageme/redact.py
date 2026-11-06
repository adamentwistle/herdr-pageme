"""Cleans screen text before it leaves the machine. Best effort: a secret with no recognisable shape gets through, which the
README and the panel say. Everything sent to Telegram from a screen goes through `safe`."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Iterable

HIDDEN = "[hidden]"
LINE_HIDDEN = "[line hidden]"

ANSI = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[@-Z\\^_])")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)")
# By letters, not word boundaries: an underscore is a word character, and DB_PASSWORD is the usual spelling.
PASSWORD_LINE = re.compile(r"^.*(?<![A-Za-z])(?:pass(?:word|wd|phrase)|pwd)(?![A-Za-z]).*$", re.I | re.M)
SHAPES = [
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),  # Telegram bot token
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),  # Anthropic, OpenAI
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),  # GitHub
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}\b"),  # GitLab
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[abeoprs]-[A-Za-z0-9-]{10,}\b"),  # Slack
    re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}\b"),  # Stripe
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),  # Google
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b"),  # JWT
]
BEARER = re.compile(r"\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{12,}", re.I)
URL_LOGIN = re.compile(r"\b([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s/@]+@", re.I)
ASSIGNED = re.compile(
    r"([A-Za-z0-9_.-]*(?:secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|credential|auth|passw|passphrase|pwd)[A-Za-z0-9_.-]*"
    r"[\"']?\s*(?::|=|=>)\s*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s,;]+)",
    re.I,
)
LONG_WORD = re.compile(r"[A-Za-z0-9+/_=-]{28,}")


def _entropy(text: str) -> float:
    counts = Counter(text)
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values())


def _hide_random(match: "re.Match[str]") -> str:
    word = match.group(0)
    mixed = any(c.isdigit() for c in word) and any(c.isalpha() for c in word)
    return HIDDEN if mixed and _entropy(word) >= 3.4 else word


def redact(text: str, known: Iterable[str] = ()) -> str:
    for secret in known:
        if secret:
            text = text.replace(secret, HIDDEN)
    text = PRIVATE_KEY.sub(HIDDEN, text)
    text = PASSWORD_LINE.sub(LINE_HIDDEN, text)
    for shape in SHAPES:
        text = shape.sub(HIDDEN, text)
    text = BEARER.sub(lambda m: f"{m.group(1)} {HIDDEN}", text)
    text = URL_LOGIN.sub(lambda m: f"{m.group(1)}{HIDDEN}@", text)
    text = ASSIGNED.sub(lambda m: f"{m.group(1)}{HIDDEN}", text)
    return LONG_WORD.sub(_hide_random, text)


def strip_controls(text: str) -> str:
    """Takes out escape sequences, control characters, and the invisible and direction-changing characters that make text
    read differently from what it is. Newlines stay."""
    text = ANSI.sub("", text)
    kept = []
    for char in text:
        if char == "\n":
            kept.append(char)
        elif char == "\t":
            kept.append(" ")
        elif unicodedata.category(char) in ("Cc", "Cf", "Co", "Cs", "Zl", "Zp"):
            continue
        else:
            kept.append(char)
    return "".join(kept)


def cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "\u2026"


def safe(text: str, limit: int, known: Iterable[str] = ()) -> str:
    """Screen text, ready to leave: no controls, no likely secrets, no longer than `limit`. It redacts before it cuts, so a cut
    can't break a secret's shape and let the first half through."""
    return cap(redact(strip_controls(text), known), limit)
