"""Reads a blocked agent's screen and says what it is asking.

Everything on a screen can be written by someone else: a file the agent read, a web page, a command's output. So this reads
one thing only, the menu at the very bottom of the screen, walking up from the last line. A menu-shaped block anywhere higher
is text, whatever it says. An unknown last line means no menu at all, and the caller shows the screen with no buttons.

An option's class decides what it may do, and is set here and nowhere else:

    answer   a choice in a question dialog
    approve  lets a permission prompt go ahead
    deny     refuses a permission prompt
    hidden   never a button, in any mode

Permission prompts use a list of exact labels, not a list of bad words. Claude Code keeps adding new ways to say yes for good
("Yes, and switch to auto mode"), and a label nobody has seen must come out hidden.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

from redact import strip_controls

SOLID_RULE = re.compile(r"^\s*[─━▔]{8,}\s*$")
ANY_RULE = re.compile(r"^\s*[─━▔╌]{8,}\s*$")
OPTION = re.compile(r"^(\s*)([❯›]\s+)?([1-9])\.\s+(\S.*)$")
PREVIEW_COLUMN = re.compile(r"\s{2,}[┌│└┐┘].*$")
KEY_HINT = re.compile(r"\s+\((?:[a-z]|esc)\)$")
# Footers are matched from the start of a line, and an option is never one, so words inside an option count for nothing.
FOOTER = re.compile(r"^\s*(?:esc to cancel|enter to select|press enter to confirm|ctrl\+g to edit)\b", re.I)
QUESTION_FOOTER = re.compile(r"^\s*enter to select\b", re.I)
CURSOR = re.compile(r"^(\s*)[❯›](?=\s)", re.M)
CHAT_ROW = re.compile(r"^\s*(?:[❯›]\s+)?(?:[1-9]\.\s+)?Chat about this\s*$")
TYPE_ROW = re.compile(r"^Type something\.?$")
CHECKBOX = re.compile(r"^\[( |✔|x|X)\]\s+(.*)$")
REVIEW_ASK = "Ready to submit your answers?"
KNOWN_AGENTS = {"claude-code", "codex"}

MAX_DESCRIPTION_LINES = 14
COLUMN_INDENT = 20
MAX_BODY_LINES = 40
UNPARSED_LINES = 15

# The only labels a permission prompt can show as buttons. Exact, after the key hint is taken off.
APPROVE_LABELS = {"Yes", "Yes, proceed", "Yes, manually approve edits"}
DENY_LABELS = {
    "No",
    "No, and tell Claude what to do differently",
    "No, and tell Codex what to do differently",
}

# A question's options are free text from the agent. These never become buttons either.
FOREVER_WORDS = re.compile(
    r"\balways\b|\bforever\b|\bpermanent|don'?t ask|do not ask|never ask|stop asking|auto[- ]?mode|auto[- ]?approve|accept edits"
    r"|bypass|skip permission|yolo|for this session|for all|from now on|dangerously",
    re.I,
)


@dataclass
class Option:
    key: str
    label: str
    cls: str
    note: str = ""
    checked: bool = False


@dataclass
class Prompt:
    kind: str  # question, permission or unparsed
    agent: str
    title: str
    body: List[str] = field(default_factory=list)
    options: List[Option] = field(default_factory=list)
    multi: bool = False
    type_key: Optional[str] = None
    cursor_key: Optional[str] = None
    region: str = ""
    menu_like: bool = False

    def buttons(self, approvals: bool) -> List[Option]:
        """What a person may press from a phone, as policy has it."""
        shown = []
        for option in self.options:
            if option.cls in ("answer", "deny") or (option.cls == "approve" and approvals):
                shown.append(option)
        return shown


def fold(label: str) -> str:
    """One spelling for what a screen and a list compare on: Claude Code writes don't with a curly quote."""
    return label.replace("’", "'").replace("‘", "'").replace(" ", " ").strip()


def _bottom(lines: List[str]) -> int:
    """The index of the last menu line, past any footer and the Chat row."""
    i = len(lines) - 1
    while i >= 0 and (not lines[i].strip() or (FOOTER.match(lines[i]) and not OPTION.match(lines[i]))):
        i -= 1
    if i >= 0 and CHAT_ROW.match(lines[i]):
        i -= 1
        while i >= 0 and not lines[i].strip():
            i -= 1
        if i >= 0 and ANY_RULE.match(lines[i]):
            i -= 1
            while i >= 0 and not lines[i].strip():
                i -= 1
    return i


def _read_menu(lines: List[str], last: int):
    """Walks up from `last` for options numbered 1 to n. Returns (options, first index), or None if it isn't a clean menu."""
    found = []
    notes: List[str] = []
    expected = None
    column_only = True
    skipped_blank = False
    i = last
    while i >= 0:
        line = lines[i]
        match = OPTION.match(line)
        if match:
            number = int(match.group(3))
            if expected is not None and number != expected:
                return None
            found.insert(0, {"n": number, "label": match.group(4), "cursor": bool(match.group(2)), "notes": list(reversed(notes))})
            notes = []
            expected = number - 1
            if number == 1:
                if skipped_blank and not any(PREVIEW_COLUMN.search(option["label"]) for option in found):
                    return None
                return found, i
        elif line.strip():
            # Anything under an option must be indented, as a description is. A flush line ends the idea of a menu.
            if not line.startswith("  ") or len(notes) >= MAX_DESCRIPTION_LINES:
                return None
            column_only = column_only and line.startswith(" " * COLUMN_INDENT)
            notes.append(line.strip())
        elif not found and notes and column_only:
            # A preview's column, drawn to the right of the options, is the one place a real menu has blanks. Only deep
            # column text may sit below them, and an option must really have a box beside it.
            skipped_blank = True
        else:
            # Otherwise real menus have no blank lines in them. A block split by one is two things.
            return None
        i -= 1
    return None


def _region(lines: List[str], first: int) -> int:
    """Where the dialog starts: the solid rule above the menu, or the one before it when the dialog is only a line or two, as a
    plan's is, or the top of the screen when there's no rule, as with Codex. This only decides what's shown: a rule can be
    faked, so the hash doesn't rely on it."""
    rules = [i for i in range(first - 1, -1, -1) if SOLID_RULE.match(lines[i])]
    if rules:
        start = rules[0] + 1
        if sum(1 for line in lines[start:first] if line.strip()) < 3 and len(rules) > 1:
            start = rules[1] + 1
        return start
    return 0


def _unparsed(agent: str, lines: List[str]) -> Prompt:
    tail = [line.strip() for line in lines if line.strip() and not ANY_RULE.match(line)][-UNPARSED_LINES:]
    # A menu PageMe couldn't read is still a menu. Typed text could pick any option on it, the lasting ones included.
    menu_like = any(OPTION.match(line) for line in lines)
    return Prompt(kind="unparsed", agent=agent, title="", body=tail, region="\n".join(tail), menu_like=menu_like)


def known_agent(app: object) -> str:
    """An agent's report of its own name is untrusted text. Only a name on the list goes any further."""
    return app if isinstance(app, str) and app in KNOWN_AGENTS else "agent"


def parse(screen: str, status: Optional[dict]) -> Prompt:
    """Reads a screen. `status` is what `hc get` reports, and only its `kind` and `app` are used."""
    status = status or {}
    status_kind = status.get("kind")
    agent = known_agent(status.get("app"))
    # Cleaned first, so a word is judged as it will look on a phone, with nothing invisible splitting it.
    lines = [line.rstrip() for line in strip_controls(screen).split("\n")]

    last = _bottom(lines)
    if last < 0:
        return _unparsed(agent, lines)
    menu = _read_menu(lines, last)
    if menu is None:
        return _unparsed(agent, lines)
    raw, first = menu
    if len(raw) < 2 or sum(1 for option in raw if option["cursor"]) != 1:
        return _unparsed(agent, lines)

    start = _region(lines, first)
    shown_from = max(start, first - MAX_BODY_LINES)
    above = [line.strip() for line in lines[shown_from:first] if line.strip() and not ANY_RULE.match(line)]

    labels = [fold(PREVIEW_COLUMN.sub("", option["label"])) for option in raw]
    review = bool(above) and above[-1] == REVIEW_ASK and labels == ["Submit answers", "Cancel"]
    question_shape = review or any(QUESTION_FOOTER.match(line) for line in lines[last + 1:])
    # Both must agree. The agent's report alone could be stale, and the screen alone could be anyone's text.
    is_question = status_kind == "question" and question_shape

    boxes = [label for label in labels if CHECKBOX.match(label)]
    multi = is_question and len(boxes) >= 2
    options: List[Option] = []
    type_key = None
    cursor_key = None
    for option, label in zip(raw, labels):
        key = str(option["n"])
        if option["cursor"]:
            cursor_key = key
        checked = False
        box = CHECKBOX.match(label)
        if multi and box:
            checked = box.group(1) != " "
            label = box.group(2).strip()
        bare = KEY_HINT.sub("", label)
        # A narrow pane wraps a label, and a wrapped line looks just like a description. So every line below an option counts
        # as part of it: an option can lose its button over a harmless description, which is the safe way to be wrong.
        whole = fold(" ".join([bare] + option["notes"]))
        if is_question:
            if TYPE_ROW.match(bare):
                if not multi:
                    type_key = key
                cls = "hidden"
            elif FOREVER_WORDS.search(unicodedata.normalize("NFKC", whole)):
                cls = "hidden"
            else:
                cls = "answer"
        elif bare in APPROVE_LABELS and not option["notes"]:
            cls = "approve"
        elif bare in DENY_LABELS and not option["notes"]:
            cls = "deny"
        else:
            cls = "hidden"
        note = next((n for n in option["notes"] if n != "Submit"), "")
        options.append(Option(key=key, label=bare, cls=cls, note=note, checked=checked))

    return Prompt(
        kind="question" if is_question else "permission",
        agent=agent,
        title=above[-1] if above else "",
        body=above[:-1],
        options=options,
        multi=multi,
        type_key=type_key,
        cursor_key=cursor_key,
        # The hash runs from the topmost solid rule on the screen, not the one nearest the menu, because a rule inside the
        # question's own text could otherwise cut part of it out. The live transcript above that rule moves, so it stays out.
        region="\n".join(lines[next((i for i in range(last) if SOLID_RULE.match(lines[i])), 0):last + 1]),
    )


def _normal(region: str) -> str:
    """What a hash covers: every character, spaces and line breaks too, because `/tmp /cache` is not `/tmp/cache`. Only the
    cursor is left out, since a digit doesn't care where it is. A resized pane counts as a change, which refuses a tap: the
    safe way to be wrong."""
    return "\n".join(line.rstrip() for line in CURSOR.sub(lambda match: match.group(1) + " ", region).split("\n"))


def fingerprint(prompt: Prompt, terminal: dict) -> str:
    """Names one block of one terminal. The same words asked again later get a new hash, because `status_ms` and `turn` move,
    so an old button can't answer a new question that happens to look the same."""
    status = terminal.get("status") or {}
    parts = [
        str(terminal.get("address")),
        str(terminal.get("created_ms")),
        str(terminal.get("turn")),
        str(terminal.get("status_ms")),
        str(status.get("kind")),
        str(status.get("msg")),
        prompt.kind,
        _normal(prompt.region),
    ]
    return hashlib.sha256("\x00".join(parts).encode("utf-8", "replace")).hexdigest()
