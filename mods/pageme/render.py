"""Builds what Telegram shows. Messages use HTML mode so PageMe's own words and screen text look different: whatever came from
a screen is cleaned, escaped and put in a <pre> block, where nothing in it can become a link, a mention or formatting."""
from __future__ import annotations

import html
import os
from typing import Iterable, List, Optional

from prompts import Prompt
from redact import safe

BODY_LIMIT = 1800
TITLE_LIMIT = 400
LABEL_LIMIT = 40
NAMES = {"claude-code": "Claude Code", "codex": "Codex"}


def screen_block(text: str, known: Iterable[str], limit: int = BODY_LIMIT) -> str:
    return f"<pre>{html.escape(safe(text, limit, known), quote=False)}</pre>"


def folder_name(cwd: Optional[str]) -> str:
    return os.path.basename((cwd or "").replace("\\", "/").rstrip("/"))


def where(address: str, cwd: Optional[str], known: Iterable[str]) -> str:
    """Plain text naming a terminal. The address is from `hc ls`, and the folder's name is cleaned like screen text."""
    folder = safe(folder_name(cwd), 60, known)
    return f"{address} · {folder}" if folder else address


def heading(place: str, agent: str, doing: str) -> str:
    return f"<b>{html.escape(place, quote=False)}</b>\n{html.escape(NAMES.get(agent, 'An agent'), quote=False)} {doing}"


def doing(kind: str) -> str:
    if kind == "question":
        return "has a question"
    if kind == "permission":
        return "wants approval"
    return "is blocked"


def lead(agent: Optional[str], kind: str) -> str:
    """The line under the place in a blocked agent's message, as plain text for the panel."""
    return f"{NAMES.get(agent, 'An agent')} {doing(kind)}"


def blocked(prompt: Prompt, place: str, approvals: bool, can_act: bool, can_type: bool, known: Iterable[str]) -> str:
    parts = [heading(place, prompt.agent, doing(prompt.kind))]

    words: List[str] = list(prompt.body)
    if prompt.title:
        words.append(prompt.title)
    if words:
        parts.append(screen_block("\n".join(words), known))

    if not can_act:
        parts.append("PageMe is in watch mode.")
    elif prompt.kind == "permission" and not approvals:
        parts.append("Approving from Telegram is off.")
    elif prompt.kind == "question" and can_type:
        parts.append("Or reply to this message with your own answer.")
    elif prompt.kind == "unparsed":
        parts.append("Reply to this message to type into it." if can_type else "This can't be answered from here.")
    return "\n\n".join(parts)


def button_label(label: str, cls: str, known: Iterable[str]) -> str:
    return "No" if cls == "deny" else safe(label, LABEL_LIMIT, known)


def keyboard(pid: str, prompt: Prompt, approvals: bool, chosen: Iterable[str], known: Iterable[str]) -> list:
    """One button per option. A button carries a random id and an option number and nothing else: which terminal it presses
    and what it presses are looked up on this machine, and checked again against the screen."""
    picked = set(chosen)
    rows = []
    for option in prompt.buttons(approvals):
        label = button_label(option.label, option.cls, known)
        if prompt.multi:
            mark = "☑ " if option.key in picked else "☐ "
            rows.append([{"text": mark + label, "callback_data": f"{pid}:t{option.key}"}])
        else:
            rows.append([{"text": label, "callback_data": f"{pid}:o{option.key}"}])
    if prompt.multi and rows:
        rows.append([{"text": "Done", "callback_data": f"{pid}:d"}])
    return rows


def closed(text: str, ending: str) -> str:
    return f"{text}\n\n<b>{html.escape(ending, quote=False)}</b>"


def finished(place: str, agent: str, summary: str, can_reply: bool, known: Iterable[str]) -> str:
    parts = [heading(place, agent, "finished")]
    if summary:
        parts.append(screen_block(summary, known, 600))
    if can_reply:
        parts.append("Reply to this message to give it a new prompt.")
    return "\n\n".join(parts)


def agent_list(rows: List[dict], known: Iterable[str]) -> str:
    """`rows` come from `hc ls`. Anything blocked comes first."""
    order = {"blocked": 0, "working": 1, "done": 2, "idle": 3}
    agents = sorted((row for row in rows if row.get("status")), key=lambda row: order.get(row.get("status"), 4))
    if not agents:
        return "No agents."
    lines = []
    for row in agents[:40]:
        place = html.escape(where(row["address"], row.get("cwd"), known), quote=False)
        lines.append(f"<b>{html.escape(str(row.get('status')), quote=False)}</b> {place}")
    if len(agents) > 40:
        lines.append(f"And {len(agents) - 40} more.")
    return "\n".join(lines)
