#!/usr/bin/env python3
"""PageMe's one entry point. `run` is the daemon. The rest are short commands for the panel and for people, and all of them
finish well inside a mod's 30 second limit.

    pageme.py run [--watch]      start the daemon; --watch never presses or types anything
    pageme.py status [--demo [name]]  one line of JSON for the panel
    pageme.py token [--clear]    ask for the bot token, or remove it
    pageme.py pair | unpair      make a code, or forget the paired user
    pageme.py pause | resume
    pageme.py approvals on|off   approving permission prompts from Telegram
    pageme.py finished on|off    messages when an agent finishes
    pageme.py mode act|watch
"""
from __future__ import annotations

import argparse
import getpass
import json
import secrets
import statistics
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import credential  # noqa: E402
import render  # noqa: E402
from sample import DEMOS, demo_status  # noqa: E402
from store import SingleDaemon, Store  # noqa: E402

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_TTL_MS = 5 * 60 * 1000
HEARTBEAT_FRESH_MS = 20_000
POLL_FRESH_MS = 120_000
HOUR_MS = 3_600_000


def now_ms() -> int:
    return int(time.time() * 1000)


def day_start(now: int) -> int:
    """Local midnight, in ms."""
    moment = time.localtime(now / 1000)
    return int(time.mktime((moment.tm_year, moment.tm_mon, moment.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000)


def answer_for(record: dict, recent: list) -> Optional[dict]:
    """The answered entry that followed this question. `recent` is newest first, so the last match is the nearest."""
    found = None
    for entry in recent:
        if entry["kind"] == "answered" and entry["where"] == record["place"] and entry["ms"] >= record["ms"]:
            found = entry
    return found


def latest_page(state: dict) -> Optional[dict]:
    """The newest question, as the phone shows it. A record from before these fields has only what `recent` kept."""
    records = state["prompts"].values()
    if not records:
        return None
    record = max(records, key=lambda item: item["ms"])
    answered = answer_for(record, state["recent"]) if record["state"] == "used" else None
    asked = record.get("asked")
    if asked is None:
        asked = next((entry["text"] for entry in state["recent"] if entry["kind"] == "asked" and entry["where"] == record["place"]), "")
    return {
        "ms": record["ms"],
        "where": record["place"],
        "lead": render.lead(record.get("agent"), record["kind"]),
        "text": asked,
        "options": record.get("labels", []),
        "state": record["state"],
        "answer": answered["text"] if answered else None,
    }


def day_stats(state: dict, now: int) -> dict:
    """Today's numbers. A question is kept for 24 hours, so every one asked today is here. Reply time is the middle gap between
    a question and its answer, from those `recent` still holds. `hours` counts questions in each of the last 24 hours, oldest
    first."""
    start = day_start(now)
    records = state["prompts"].values()
    today = [record for record in records if record["ms"] >= start]
    hours = [0] * 24
    for record in records:
        back = (now - record["ms"]) // HOUR_MS
        if 0 <= back < 24:
            hours[23 - back] += 1
    gaps = []
    for record in today:
        if record["state"] == "used":
            answered = answer_for(record, state["recent"])
            if answered:
                gaps.append(answered["ms"] - record["ms"])
    return {
        "pages": len(today),
        "answered": sum(record["state"] == "used" for record in today),
        "reply_ms": int(statistics.median(gaps)) if gaps else None,
        "hours": hours,
    }


def status(store: Store) -> dict:
    state = store.read()
    now = now_ms()
    code = state["code"]
    if code and now > code["expires_ms"]:
        code = None
    telegram = state["telegram"]
    running = now - state["heartbeat_ms"] < HEARTBEAT_FRESH_MS
    pair = state["pair"]
    return {
        "demo": False,
        "token": credential.load() is not None,
        "token_where": credential.where(),
        "running": running,
        "connected": running and telegram["ok"] and now - telegram["ms"] < POLL_FRESH_MS,
        "error": telegram["error"] if running else None,
        "paired": {"name": pair["name"], "ms": pair["ms"]} if pair else None,
        "code": {"value": code["value"], "seconds": max(0, (code["expires_ms"] - now) // 1000)} if code else None,
        "paused": state["settings"]["paused"],
        "mode": state["settings"]["mode"],
        "approvals": state["settings"]["approvals"],
        "finished": state["settings"]["finished"],
        "remote": state["settings"]["remote"],
        "recent": state["recent"],
        "latest": latest_page(state),
        "today": day_stats(state, now),
    }


def make_code(store: Store) -> dict:
    now = now_ms()

    def change(state: dict) -> dict:
        if state["pair"]:
            return {"error": "Already paired. Unpair first."}
        value = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        state["code"] = {"value": value, "created_ms": now, "expires_ms": now + CODE_TTL_MS, "tries": 0}
        return {"code": value}

    return store.update(change)


def unpair(state: dict) -> None:
    """Drops the user and every open question with them, so no old button or reply works after this."""
    state["pair"] = None
    state["code"] = None
    state["prompts"] = {}
    state["finished"] = {}


def setting(store: Store, name: str, value: object) -> None:
    store.update(lambda state: state["settings"].update({name: value}))


def read_token() -> str:
    if sys.stdin.isatty():
        return getpass.getpass("Bot token from @BotFather (hidden): ").strip()
    return sys.stdin.readline().strip()


def set_token(clear: bool) -> int:
    if clear:
        credential.clear()
        print("Token removed.")
        return 0
    token = read_token()
    if not credential.valid(token):
        print("That doesn't look like a bot token. Nothing was saved.")
        code = 1
    else:
        credential.save(token)
        print(f"Saved in {credential.where()}.")
        code = 0
    if sys.stdin.isatty():
        input("Press Enter to close. ")
    return code


def run(store: Store, watch: bool) -> int:
    from daemon import Daemon
    from hcli import Hc
    from telegram import Telegram

    token = credential.load()
    if not token:
        print("No bot token yet. Set one in the panel, or run: pageme.py token")
        return 1
    lock = SingleDaemon(store.folder)
    if not lock.acquire():
        print("PageMe is already running.")
        return 1
    if watch:
        setting(store, "mode", "watch")
    daemon = Daemon(Hc(), Telegram(token), store, token=token)
    print(f"PageMe is running. Mode: {store.read()['settings']['mode']}.", flush=True)
    try:
        daemon.run()
    except KeyboardInterrupt:
        daemon.stopping.set()
    finally:
        lock.release()
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="pageme.py")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("run")
    start.add_argument("--watch", action="store_true")
    show = commands.add_parser("status")
    show.add_argument("--demo", nargs="?", const="on-call", choices=DEMOS)
    token = commands.add_parser("token")
    token.add_argument("--clear", action="store_true")
    for name in ("pair", "unpair", "pause", "resume"):
        commands.add_parser(name)
    for name in ("approvals", "finished", "remote"):
        commands.add_parser(name).add_argument("value", choices=["on", "off"])
    commands.add_parser("mode").add_argument("value", choices=["act", "watch"])
    args = parser.parse_args(argv)

    if args.command == "status" and args.demo:
        print(json.dumps(demo_status(now_ms(), args.demo)))
        return 0
    if args.command == "token":
        return set_token(args.clear)

    store = Store()
    if args.command == "run":
        return run(store, args.watch)
    if args.command == "status":
        print(json.dumps(status(store), ensure_ascii=False))
    elif args.command == "pair":
        result = make_code(store)
        print(json.dumps(result))
        return 1 if "error" in result else 0
    elif args.command == "unpair":
        store.update(unpair)
    elif args.command in ("pause", "resume"):
        setting(store, "paused", args.command == "pause")
    elif args.command in ("approvals", "finished", "remote"):
        setting(store, args.command, args.value == "on")
    elif args.command == "mode":
        setting(store, "mode", args.value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
