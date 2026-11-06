"""Made-up data for the panel's demo mode and preview.png. Nothing here comes from a real machine."""
from __future__ import annotations

SECOND = 1_000
MINUTE = 60_000

DEMO_HOURS = [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 2, 1, 0, 0, 1, 3, 1, 2, 1]
DEMOS = ("on-call", "answered", "approval", "quiet", "paused", "offline", "stopped", "no-token", "setup", "pairing")


def demo_recent(now: int) -> list:
    return [
        {"ms": now - 1 * MINUTE, "kind": "asked", "where": "mac/t4 · sample-app", "text": "Which colour should the banner be?"},
        {"ms": now - 9 * MINUTE, "kind": "finished", "where": "t7 · demo-site", "text": "Added the search box and its tests"},
        {"ms": now - 14 * MINUTE, "kind": "refused", "where": "t7 · demo-site", "text": "That question has changed, so nothing was pressed."},
        {"ms": now - 16 * MINUTE, "kind": "asked", "where": "t7 · demo-site", "text": "Do you want to proceed?"},
        {"ms": now - 39 * MINUTE, "kind": "answered", "where": "t2 · toy-api", "text": "No"},
        {"ms": now - 41 * MINUTE, "kind": "asked", "where": "t2 · toy-api", "text": "Do you want to create notes.txt?"},
        {"ms": now - 66 * MINUTE, "kind": "answered", "where": "mac/t4 · sample-app", "text": "Dark"},
        {"ms": now - 67 * MINUTE, "kind": "asked", "where": "mac/t4 · sample-app", "text": "Which theme should the site start in?"},
        {"ms": now - 92 * MINUTE, "kind": "finished", "where": "t2 · toy-api", "text": "Moved the routes into their own file"},
    ]


def demo_latest(now: int) -> dict:
    return {
        "ms": now - 1 * MINUTE,
        "where": "mac/t4 · sample-app",
        "lead": "Claude Code has a question",
        "text": "Which colour should the banner be?",
        "options": ["Green", "Blue", "Orange"],
        "state": "open",
        "answer": None,
    }


def demo_status(now: int, name: str = "on-call") -> dict:
    nothing = {"recent": [], "latest": None, "today": {"pages": 0, "answered": 0, "reply_ms": None, "hours": [0] * 24}}
    status = {
        "demo": True,
        "token": True,
        "token_where": "macOS keychain",
        "running": True,
        "connected": True,
        "error": None,
        "paired": {"name": "Sam", "ms": now - 3 * 24 * 60 * MINUTE},
        "code": None,
        "paused": False,
        "mode": "act",
        "approvals": False,
        "finished": True,
        "remote": True,
        "recent": demo_recent(now),
        "latest": demo_latest(now),
        "today": {"pages": 9, "answered": 8, "reply_ms": 1 * MINUTE + 40 * SECOND, "hours": DEMO_HOURS},
    }
    if name == "answered":
        status["recent"].insert(0, {"ms": now - 20 * SECOND, "kind": "answered", "where": "mac/t4 · sample-app", "text": "Green"})
        status["latest"].update({"state": "used", "answer": "Green"})
    elif name == "approval":
        status["latest"].update({
            "lead": "Claude Code wants approval",
            "text": "Run npm run migrate against the sample database, then rebuild the search index and restart the demo server?",
            "options": ["No"],
        })
    elif name == "quiet":
        status.update(nothing)
    elif name == "paused":
        status["paused"] = True
    elif name == "offline":
        status.update({"connected": False, "error": "Telegram can't be reached"})
    elif name == "stopped":
        status.update({"running": False, "connected": False})
    elif name in ("no-token", "setup", "pairing"):
        status.update({**nothing, "paired": None})
        if name == "no-token":
            status.update({"token": False, "running": False, "connected": False})
        if name == "pairing":
            status["code"] = {"value": "K7QM2XRT", "seconds": 272}
    return status
