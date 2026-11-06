"""What a phone may do. Small on purpose: these are the rules docs/security.md points at."""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from prompts import Option, Prompt
from redact import strip_controls

PROMPT_TTL_MS = 15 * 60 * 1000
FINISHED_TTL_MS = 60 * 60 * 1000
MAX_REPLY = 2000
SINGLE_KEY_LENGTH = 3
PRESSABLE = re.compile(r"^(?:[1-9]|right)$")
ADDRESS = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/)?t[0-9a-z]{1,12}$")
BLANK_LETTERS = "\u115f\u1160\u17b4\u17b5\u2800\u3164\uffa0"
REMOTE_OFF = "Other machines are off."


def is_remote(address: str) -> bool:
    return "/" in address


def may_press(option: Option, approvals: bool) -> bool:
    if option.cls in ("answer", "deny"):
        return True
    return option.cls == "approve" and approvals


def may_type(prompt: Prompt, status_kind: Optional[str]) -> bool:
    """Text goes into a dialog only where it can't be an approval. A pasted `1` or `y` on a permission prompt would be one, and
    on a menu it could be "don't ask again", which no setting allows. So turning approvals on doesn't open this: a screen with
    no `kind` may be a permission prompt, because Codex reports none, and a `question` report can be stale."""
    if prompt.kind == "question":
        return prompt.type_key is not None
    if prompt.kind == "unparsed":
        return status_kind == "question" and not prompt.menu_like
    return False


def dialog_refusal(prompt: Prompt, text: str) -> Optional[str]:
    """Why this text can't be typed into a dialog. On a screen PageMe couldn't read, a short reply could be one keypress."""
    if not text or len(text) > MAX_REPLY:
        return "That can't be sent."
    refusal = command_refusal(text)
    if refusal:
        return refusal
    if prompt.kind == "unparsed" and len(text) <= SINGLE_KEY_LENGTH:
        return "Too short. On a screen PageMe can't read, that could pick an option."
    return None


def clean_reply(text: str, into_dialog: bool) -> str:
    """A reply as it will be typed. A control character could be a key, and a newline in a dialog field would press Enter."""
    text = strip_controls(text).strip()
    return " ".join(text.split()) if into_dialog else text


def _first_visible(text: str) -> str:
    """The first character a person would see, as its plain form. Whitespace, marks and blank letters are passed over."""
    for char in unicodedata.normalize("NFKC", text):
        if char not in BLANK_LETTERS and unicodedata.category(char)[0] not in "ZCM":
            return char
    return ""


def command_refusal(text: str) -> Optional[str]:
    """Why this text can't be sent on any path. A leading `!` runs a shell command with no permission prompt at all, seen on a
    real Claude Code session, and a leading `/` can change a session's permission mode."""
    first = _first_visible(text)
    if first == "!":
        return "Refused. A message can't start with ! because that runs a shell command with no approval."
    if first == "/":
        return "Refused. A message can't start with / because a slash command can change permissions."
    return None


def reply_refusal(text: str) -> Optional[str]:
    """Why this text can't go to an idle agent."""
    if not text:
        return "Empty."
    if len(text) > MAX_REPLY:
        return f"Too long. The limit is {MAX_REPLY} characters."
    return command_refusal(text)
