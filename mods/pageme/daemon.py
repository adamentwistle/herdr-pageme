"""The daemon: watches agents through `hc`, tells a paired Telegram user, and presses what they tap.

Two loops share this class. `scan` looks at the terminals, and `poll_once` reads Telegram. A lock keeps a tap and a scan from
working on the same prompt at once. Every press and every typed reply goes through `_fresh`, which reads the terminal again at
that moment: nothing is trusted because of what a chat message says, or what was on screen when the message went out.
"""
from __future__ import annotations

import hmac
import re
import secrets
import threading
import time
from typing import Iterable, List, Optional, Tuple

import policy
import render
from hcli import Hc, HcError
from prompts import Prompt, fingerprint, known_agent, parse
from redact import safe
from store import Store
from telegram import Telegram, TelegramError, scrub

CODE_SHAPE = re.compile(r"^[A-Z2-9]{8}$")
CALLBACK = re.compile(r"^([A-Za-z0-9_-]{8,24}):(o[1-9]|t[1-9]|d)$")
CODE_TRIES = 5
SCAN_S = 5
MESSAGES_PER_MINUTE = 20
UNPARSED_GAP_MS = 20_000
KEEP_MS = 24 * 60 * 60 * 1000
FINISHED_KEEP = 50
RECENT_TEXT = 110
SETTLE_S = 0.4

GONE = "That question has gone."
CHANGED = "That question has changed, so nothing was pressed."


def now_ms() -> int:
    return int(time.time() * 1000)


class Daemon:
    def __init__(self, hc: Hc, telegram: Telegram, store: Store, token: str = "", clock=now_ms, log=None, settle_s: float = SETTLE_S):
        self.hc = hc
        self.hc.remote_allowed = lambda: self.store.read()["settings"]["remote"]
        self.tg = telegram
        self.store = store
        self.token = token
        self.now = clock
        self.log = log or (lambda text: print(text, flush=True))
        self.settle_s = settle_s
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.seen: dict = {}
        self.sent_at: List[int] = []
        self.unparsed_at: dict = {}
        self.hold_until = 0
        self.reissue = False
        self.known_chat: Optional[int] = None
        self.known_settings: Optional[dict] = None

    # Sending

    @property
    def known(self) -> Iterable[str]:
        return (self.token,)

    def _note(self, kind: str, place: str, text: str) -> None:
        cleaned = safe(text, RECENT_TEXT, self.known)
        self.store.update(lambda state: self.store.add_recent(state, self.now(), kind, place, cleaned))

    def _room(self) -> bool:
        """A busy or hostile agent can't flood the chat, or get the bot limited by Telegram."""
        now = self.now()
        if now < self.hold_until:
            return False
        self.sent_at = [ms for ms in self.sent_at if now - ms < 60_000]
        if len(self.sent_at) >= MESSAGES_PER_MINUTE:
            return False
        self.sent_at.append(now)
        return True

    def _say(self, chat: int, text: str, keyboard: Optional[list] = None) -> Optional[dict]:
        try:
            return self.tg.send(chat, text, keyboard)
        except TelegramError as error:
            self._telegram_trouble(error)
            return None

    def _edit(self, chat: int, message_id: int, text: str, keyboard: Optional[list] = None) -> None:
        try:
            self.tg.edit(chat, message_id, text, keyboard)
        except TelegramError as error:
            self._telegram_trouble(error)

    def _answer(self, callback_id: str, text: str) -> None:
        try:
            self.tg.answer(callback_id, text)
        except TelegramError as error:
            self._telegram_trouble(error)

    def _telegram_trouble(self, error: TelegramError) -> None:
        if error.retry_after:
            self.hold_until = self.now() + error.retry_after * 1000
        self.log(f"Telegram: {scrub(error.description, self.token)}")

    # Scanning

    def _terminals(self, settings: dict) -> List[dict]:
        """Other machines are left out until someone turns them on, because their screens may not be allowed to leave."""
        terminals = self.hc.ls()
        if settings["remote"]:
            return terminals
        return [terminal for terminal in terminals if not policy.is_remote(terminal.get("address", ""))]

    def scan(self) -> None:
        with self.lock:
            state = self.store.read()
            self._notice_changes(state)
            pair = state["pair"]
            settings = state["settings"]
            terminals = self._terminals(settings)
            live = {}
            for terminal in terminals:
                address = terminal.get("address", "")
                if not policy.ADDRESS.match(address):
                    continue
                live[address] = terminal
                status = terminal.get("status")
                before = self.seen.get(address)
                self.seen[address] = status
                if not pair or settings["paused"]:
                    continue
                try:
                    if status == "blocked":
                        self._blocked(address, pair, settings)
                    elif status == "done" and before in ("working", "blocked") and settings["finished"]:
                        self._finished(address, pair, settings)
                except HcError as error:
                    self.log(f"{address}: {scrub(error, self.token)}")
            for address in [address for address in self.seen if address not in live]:
                del self.seen[address]
            self.reissue = False
            if pair:
                self._close_old(live, pair)

    def _notice_changes(self, state: dict) -> None:
        """Turning approvals on is always said out loud in the chat, however it was done. So is unpairing."""
        pair = state["pair"]
        settings = state["settings"]
        if self.known_chat and not pair:
            self._say(self.known_chat, "Unpaired.")
        if pair:
            was_on = bool(self.known_settings and self.known_settings["approvals"])
            if settings["approvals"] and not was_on:
                self._say(pair["chat_id"], "<b>Approving from Telegram is on.</b>")
            elif was_on and not settings["approvals"]:
                self._say(pair["chat_id"], "Approving from Telegram is off.")
        self.known_chat = pair["chat_id"] if pair else None
        self.known_settings = dict(settings)

    def _blocked(self, address: str, pair: dict, settings: dict) -> None:
        terminal = self.hc.get(address)
        status = terminal.get("status") or {}
        if status.get("state") != "blocked":
            return
        prompt = parse(self.hc.read(address, 0), status)
        mark = fingerprint(prompt, terminal)

        state = self.store.read()
        same = [record for record in state["prompts"].values() if record["address"] == address and record["mark"] == mark]
        if same and not (self.reissue and all(record["state"] == "expired" for record in same)):
            return
        now = self.now()
        if prompt.kind == "unparsed":
            # A moving screen would otherwise be a new message on every scan.
            if now - self.unparsed_at.get(address, 0) < UNPARSED_GAP_MS:
                return
        if not self._room():
            return
        self._close_address(address, pair, "Moved on.", keep=mark)

        approvals = settings["approvals"]
        can_act = settings["mode"] == "act"
        can_type = can_act and policy.may_type(prompt, status.get("kind"))
        place = render.where(address, terminal.get("cwd"), self.known)
        text = render.blocked(prompt, place, approvals, can_act, can_type, self.known)
        pid = secrets.token_urlsafe(9)
        asked = prompt.title or (prompt.body[-1] if prompt.body else "Blocked")
        ticked = [option.key for option in prompt.buttons(approvals) if option.checked] if prompt.multi else []
        keys = render.keyboard(pid, prompt, approvals, ticked, self.known) if can_act else []
        sent = self._say(pair["chat_id"], text, keys)
        if not sent:
            return
        if prompt.kind == "unparsed":
            self.unparsed_at[address] = now
        record = {
            "pid": pid,
            "address": address,
            "mark": mark,
            "message_id": sent["message_id"],
            "created_ms": terminal.get("created_ms"),
            "ms": now,
            "expires_ms": now + policy.PROMPT_TTL_MS,
            "state": "open",
            "kind": prompt.kind,
            "place": place,
            "text": text,
            "chosen": ticked,
            "agent": prompt.agent,
            "asked": safe(asked, RECENT_TEXT, self.known),
            "labels": [button["text"] for row in keys for button in row],
        }

        def keep(state: dict) -> None:
            state["prompts"][pid] = record
            for old in same:
                state["prompts"].get(old["pid"], {})["state"] = "gone"
            self._prune(state)
            self.store.add_recent(state, now, "asked", place, record["asked"])

        self.store.update(keep)

    def _prune(self, state: dict) -> None:
        now = self.now()
        for pid in [pid for pid, record in state["prompts"].items() if now - record["ms"] > KEEP_MS]:
            del state["prompts"][pid]

    def _finished(self, address: str, pair: dict, settings: dict) -> None:
        if not self._room():
            return
        terminal = self.hc.get(address)
        status = terminal.get("status") or {}
        place = render.where(address, terminal.get("cwd"), self.known)
        can_reply = settings["mode"] == "act"
        sent = self._say(pair["chat_id"], render.finished(place, known_agent(status.get("app")), status.get("msg") or "", can_reply, self.known))
        if not sent:
            return
        entry = {"address": address, "created_ms": terminal.get("created_ms"), "turn": terminal.get("turn"), "ms": self.now(), "place": place}

        def keep(state: dict) -> None:
            state["finished"][str(sent["message_id"])] = entry
            for message_id in sorted(state["finished"], key=int)[:-FINISHED_KEEP]:
                del state["finished"][message_id]
            self.store.add_recent(state, self.now(), "finished", place, safe(status.get("msg") or "Finished", RECENT_TEXT, self.known))

        self.store.update(keep)

    def _close_address(self, address: str, pair: dict, ending: str, keep: str = "") -> None:
        for record in list(self.store.read()["prompts"].values()):
            if record["address"] == address and record["state"] == "open" and record["mark"] != keep:
                self._close(record, pair, "gone", ending)

    def _close(self, record: dict, pair: dict, new_state: str, ending: str) -> None:
        self.store.update(lambda state: state["prompts"].get(record["pid"], {}).update({"state": new_state}))
        self._edit(pair["chat_id"], record["message_id"], render.closed(record["text"], ending))

    def _close_old(self, live: dict, pair: dict) -> None:
        now = self.now()
        for record in list(self.store.read()["prompts"].values()):
            if record["state"] != "open":
                continue
            terminal = live.get(record["address"])
            if not terminal or terminal.get("status") != "blocked":
                self._close(record, pair, "gone", "Answered somewhere else.")
            elif now > record["expires_ms"]:
                self._close(record, pair, "expired", "Expired. Send /agents to get it again.")

    # Telegram updates

    def poll_once(self, wait: int = 50) -> None:
        offset = self.store.read()["offset"]
        try:
            updates = self.tg.updates(offset, wait)
        except TelegramError as error:
            self._telegram_trouble(error)
            trouble = scrub(error.description, self.token)
            self.store.update(lambda state: state.update({"telegram": {"ok": False, "ms": self.now(), "error": trouble}}))
            raise
        self.store.update(lambda state: state.update({"telegram": {"ok": True, "ms": self.now(), "error": None}}))
        for update in updates:
            # Saved before it's handled: after a crash an update is lost, and is never acted on twice.
            next_offset = update["update_id"] + 1
            self.store.update(lambda state: state.update({"offset": next_offset}))
            try:
                self.handle(update)
            except Exception as error:  # One bad update mustn't stop the daemon.
                self.log(f"Update failed: {type(error).__name__}: {scrub(error, self.token)}")

    def handle(self, update: dict) -> None:
        with self.lock:
            if "callback_query" in update:
                self._tap(update["callback_query"])
            elif "message" in update:
                self._message(update["message"])

    def _is_paired(self, sender: Optional[dict], chat: Optional[dict], pair: Optional[dict]) -> bool:
        return bool(pair and sender and chat and sender.get("id") == pair["user_id"] and chat.get("id") == pair["chat_id"])

    def _message(self, message: dict) -> None:
        state = self.store.read()
        pair = state["pair"]
        if not pair:
            self._try_pairing(message)
            return
        if not self._is_paired(message.get("from"), message.get("chat"), pair):
            return
        text = message.get("text") or ""
        reply = message.get("reply_to_message")
        if reply:
            self._reply(message, reply, text, state, pair)
        elif text.startswith("/agents"):
            self.reissue = True
            self._say(pair["chat_id"], render.agent_list(self._terminals(self.store.read()["settings"]), self.known))
            self.wake.set()
        elif text.startswith("/pause"):
            self.store.update(lambda s: s["settings"].update({"paused": True}))
            self._say(pair["chat_id"], "Paused.")
        elif text.startswith("/resume"):
            self.store.update(lambda s: s["settings"].update({"paused": False}))
            self._say(pair["chat_id"], "Resumed.")
            self.wake.set()
        else:
            self._say(pair["chat_id"], "Reply to an agent's message, or send /agents.")

    def _try_pairing(self, message: dict) -> None:
        """The one thing a stranger's message can reach. Nobody gets a reply unless they had the code."""
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        if chat.get("type") != "private" or sender.get("is_bot") or "forward_origin" in message or "forward_date" in message:
            return
        text = (message.get("text") or "").strip().upper()
        if not CODE_SHAPE.match(text):
            return
        now = self.now()

        def attempt(state: dict) -> bool:
            code = state["code"]
            if not code or now > code["expires_ms"] or state["pair"]:
                return False
            # A message from before the code existed can't be its answer, even if it was queued while the daemon was down.
            if message.get("date", 0) * 1000 < code["created_ms"] - 2000:
                return False
            if not hmac.compare_digest(text, code["value"]):
                code["tries"] += 1
                if code["tries"] >= CODE_TRIES:
                    state["code"] = None
                return False
            state["code"] = None
            state["pair"] = {
                "user_id": sender["id"],
                "chat_id": chat["id"],
                "name": safe(sender.get("first_name") or "Telegram user", 40, self.known),
                "ms": now,
            }
            self.store.add_recent(state, now, "paired", "Telegram", state["pair"]["name"])
            return True

        if self.store.update(attempt):
            self._say(chat["id"], "Paired. Blocked agents will show up here. /agents lists them.")
            self.log("Paired.")

    def _tap(self, query: dict) -> None:
        state = self.store.read()
        pair = state["pair"]
        message = query.get("message") or {}
        if not self._is_paired(query.get("from"), message.get("chat"), pair):
            return  # Ignored with no reply, not even the spinner's.

        match = CALLBACK.match(query.get("data") or "")
        record = state["prompts"].get(match.group(1)) if match else None
        if not record or record.get("message_id") != message.get("message_id"):
            self._answer(query["id"], "That button doesn't work any more.")
            return
        action = match.group(2)
        refusal = self._closed_reason(record, state)
        if refusal:
            self._refuse(query["id"], record, refusal, pair, action)
            return

        if action[0] == "t":
            self._toggle(query["id"], record, action[1], pair, state)
            return

        terminal, prompt, refusal = self._fresh(record)
        if refusal:
            self._refuse(query["id"], record, refusal, pair, action)
            return
        approvals = state["settings"]["approvals"]
        if action == "d":
            allowed = {option.key: option for option in prompt.buttons(approvals)}
            # A tick the chat can't show must not ride along on a submit, and a tick isn't a thing a phone can see to clear.
            if any(option.checked and option.key not in allowed for option in prompt.options):
                self._refuse(query["id"], record, "Something hidden is ticked. Answer this one at the keyboard.", pair, action)
                return
            chosen = [key for key in record["chosen"] if key in allowed]
            if not prompt.multi or not chosen:
                self._refuse(query["id"], record, "Pick something first.", pair, action)
                return
            # A digit toggles, so only what differs from the screen is pressed.
            keys = [key for key, option in allowed.items() if (key in chosen) != option.checked] + ["right"]
            label = ", ".join(render.button_label(allowed[key].label, allowed[key].cls, self.known) for key in chosen)
            approving = False
        else:
            option = next((option for option in prompt.options if option.key == action[1]), None)
            if not option or not policy.may_press(option, approvals):
                self._refuse(query["id"], record, "That option can't be pressed from here.", pair, action)
                return
            keys = [option.key]
            label = render.button_label(option.label, option.cls, self.known)
            approving = option.cls == "approve"
        self._press(query["id"], record, prompt, keys, label, pair, approving, action)

    def _closed_reason(self, record: dict, state: dict) -> Optional[str]:
        settings = state["settings"]
        if record["state"] == "used":
            return "That was already answered."
        if record["state"] != "open":
            return GONE
        if self.now() > record["expires_ms"]:
            return "Too late. That button has expired."
        if policy.is_remote(record["address"]) and not settings["remote"]:
            return policy.REMOTE_OFF
        if settings["paused"]:
            return "PageMe is paused."
        if settings["mode"] != "act":
            return "PageMe is in watch mode."
        return None

    def _fresh(self, record: dict) -> Tuple[Optional[dict], Optional[Prompt], Optional[str]]:
        """Is this terminal still blocked on this question, right now? The terminal is the one saved on this machine when the
        message went out. Nothing in the tap or the screen can name another."""
        try:
            terminal = self.hc.get(record["address"])
            status = terminal.get("status") or {}
            if terminal.get("state") != "live" or status.get("state") != "blocked":
                return None, None, GONE
            if terminal.get("created_ms") != record["created_ms"]:
                return None, None, GONE
            prompt = parse(self.hc.read(record["address"], 0), status)
        except HcError:
            return None, None, GONE
        if fingerprint(prompt, terminal) != record["mark"]:
            return None, None, CHANGED
        return terminal, prompt, None

    def _allowed_now(self, state: dict, record: dict, pair: dict, approving: bool) -> bool:
        """The panel is another process, so anything read earlier may be out of date. This asks the saved state itself.
        Unpairing removes every prompt, so a missing prompt means it was taken back."""
        live = state["prompts"].get(record["pid"])
        current = state["pair"]
        settings = state["settings"]
        if not live or not current or current["user_id"] != pair["user_id"] or current["chat_id"] != pair["chat_id"]:
            return False
        if settings["paused"] or settings["mode"] != "act" or self.now() > live["expires_ms"]:
            return False
        if policy.is_remote(record["address"]) and not settings["remote"]:
            return False
        return settings["approvals"] or not approving

    def _take(self, record: dict, pair: dict, approving: bool = False) -> bool:
        """Spends the prompt, under the state's lock, if it may still be spent. True only for the first caller."""

        def take(state: dict) -> bool:
            if not self._allowed_now(state, record, pair, approving) or state["prompts"][record["pid"]]["state"] != "open":
                return False
            state["prompts"][record["pid"]]["state"] = "used"
            return True

        return self.store.update(take)

    def _press(self, callback_id: str, record: dict, prompt: Prompt, keys: List[str], label: str, pair: dict, approving: bool, attempt: str) -> None:
        if not self._take(record, pair, approving):
            self._refuse(callback_id, record, "That can't be answered now.", pair, attempt)
            return
        try:
            self.hc.keys(record["address"], keys)
        except HcError as error:
            self._forget(record)
            self._audit(record, prompt.kind, "press", label, keys, "failed", pair)
            self._answer(callback_id, "That didn't go through.")
            self.log(f"{record['address']}: {scrub(error, self.token)}")
            return
        self._audit(record, prompt.kind, "press", label, keys, "sent", pair)
        self._answer(callback_id, "Sent.")
        self._edit(pair["chat_id"], record["message_id"], render.closed(record["text"], f"Answered: {label}"))
        self._note("answered", record["place"], label)
        self._look_again()

    def _toggle(self, callback_id: str, record: dict, key: str, pair: dict, state: dict) -> None:
        """Ticks an option in the chat only. No key is pressed until Done, so Done is the one press that counts."""
        terminal, prompt, refusal = self._fresh(record)
        if refusal:
            self._refuse(callback_id, record, refusal, pair, f"t{key}")
            return
        allowed = {option.key for option in prompt.buttons(state["settings"]["approvals"])}
        if not prompt.multi or key not in allowed:
            self._refuse(callback_id, record, "That option can't be pressed from here.", pair, f"t{key}")
            return
        chosen = sorted(set(record["chosen"]) ^ {key})
        self.store.update(lambda s: s["prompts"][record["pid"]].update({"chosen": chosen}))
        keyboard = render.keyboard(record["pid"], prompt, state["settings"]["approvals"], chosen, self.known)
        self._edit(pair["chat_id"], record["message_id"], record["text"], keyboard)
        self._answer(callback_id, "")

    def _forget(self, record: dict) -> None:
        """A press that never landed: the next scan sends the question again."""
        self.store.update(lambda state: state["prompts"].pop(record["pid"], None))

    def _refuse(self, callback_id: str, record: dict, why: str, pair: dict, attempt: str) -> None:
        self._answer(callback_id, why)
        self._note("refused", record["place"], why)
        self.store.audit(
            {"ms": self.now(), "terminal": record["address"], "how": "press", "attempt": attempt, "mark": record["mark"][:16], "user": pair["user_id"], "result": "refused", "why": why}
        )

    def _turn_down(self, record: dict, why: str, text: str, pair: dict) -> None:
        """A typed answer that won't be sent: said in the chat, shown in the panel and written down."""
        self._say(pair["chat_id"], why)
        self._note("refused", record["place"], why)
        self._audit(record, record.get("kind", "prompt"), "type", text, [], "refused", pair, why)

    def _audit(self, record: dict, kind: str, how: str, answer: str, keys: List[str], result: str, pair: dict, why: str = "") -> None:
        entry = {
            "ms": self.now(),
            "terminal": record["address"],
            "kind": kind,
            "how": how,
            "answer": safe(answer, 200, self.known),
            "keys": keys,
            "mark": record["mark"][:16],
            "user": pair["user_id"],
            "result": result,
        }
        if why:
            entry["why"] = why
        self.store.audit(entry)

    def _look_again(self) -> None:
        """A wizard's next page sends no event, so the screen is read again once it has had time to draw."""
        timer = threading.Timer(0.8, self.wake.set)
        timer.daemon = True
        timer.start()

    # Replies

    def _reply(self, message: dict, reply: dict, text: str, state: dict, pair: dict) -> None:
        replied_to = reply.get("message_id")
        record = next((r for r in state["prompts"].values() if r.get("message_id") == replied_to), None)
        if record:
            self._reply_to_prompt(record, text, state, pair)
            return
        entry = state["finished"].get(str(replied_to))
        if entry:
            self._reply_to_finished(entry, text, state, pair)
            return
        self._say(pair["chat_id"], "That message can't take a reply.")

    def _reply_to_prompt(self, record: dict, text: str, state: dict, pair: dict) -> None:
        chat = pair["chat_id"]
        cleaned = policy.clean_reply(text, into_dialog=True)
        refusal = self._closed_reason(record, state)
        if refusal:
            self._turn_down(record, refusal, cleaned, pair)
            return
        terminal, prompt, refusal = self._fresh(record)
        if refusal:
            self._turn_down(record, refusal, cleaned, pair)
            return
        if not policy.may_type(prompt, (terminal.get("status") or {}).get("kind")):
            self._turn_down(record, "Text can't answer this one.", cleaned, pair)
            return
        refusal = policy.dialog_refusal(prompt, cleaned)
        if refusal:
            self._turn_down(record, refusal, cleaned, pair)
            return
        if not self._take(record, pair):
            self._turn_down(record, "That can't be answered now.", cleaned, pair)
            return
        try:
            if prompt.kind == "question":
                self.hc.keys(record["address"], [prompt.type_key])
                time.sleep(self.settle_s)
                # Pasted text goes wherever the cursor is, so it must be on the answer field of this same question.
                terminal, again, refusal = self._fresh(record)
                if refusal or again.cursor_key != prompt.type_key or again.type_key != prompt.type_key:
                    self._forget(record)
                    self._turn_down(record, CHANGED, cleaned, pair)
                    return
                # The digit took a moment, and the panel may have taken this back during it.
                if not self.store.update(lambda state: self._allowed_now(state, record, pair, False)):
                    self._turn_down(record, "That can't be answered now.", cleaned, pair)
                    return
            self.hc.send(record["address"], cleaned, force=True)
        except HcError as error:
            self._forget(record)
            self._audit(record, prompt.kind, "type", cleaned, [], "failed", pair)
            self._say(chat, "That didn't go through.")
            self.log(f"{record['address']}: {scrub(error, self.token)}")
            return
        self._audit(record, prompt.kind, "type", cleaned, [], "sent", pair)
        self._edit(chat, record["message_id"], render.closed(record["text"], "Answered with your reply."))
        self._note("answered", record["place"], cleaned)
        self._look_again()

    def _reply_to_finished(self, entry: dict, text: str, state: dict, pair: dict) -> None:
        chat = pair["chat_id"]
        settings = state["settings"]
        fake = {"address": entry["address"], "mark": "", "place": entry["place"]}
        cleaned = policy.clean_reply(text, into_dialog=False)
        if not settings["finished"]:
            self._turn_down(fake, "Finished messages are off.", cleaned, pair)
            return
        if policy.is_remote(entry["address"]) and not settings["remote"]:
            self._turn_down(fake, policy.REMOTE_OFF, cleaned, pair)
            return
        if settings["paused"] or settings["mode"] != "act":
            self._turn_down(fake, "PageMe can't send anything right now.", cleaned, pair)
            return
        if self.now() - entry["ms"] > policy.FINISHED_TTL_MS:
            self._turn_down(fake, "Too late. That message has expired.", cleaned, pair)
            return
        refusal = policy.reply_refusal(cleaned)
        if refusal:
            self._turn_down(fake, refusal, cleaned, pair)
            return
        try:
            terminal = self.hc.get(entry["address"])
            status = terminal.get("status") or {}
            still = terminal.get("state") == "live" and terminal.get("created_ms") == entry["created_ms"]
            if not still or status.get("state") not in ("done", "idle") or terminal.get("turn") != entry["turn"]:
                self._turn_down(fake, "That agent has moved on, so nothing was sent.", cleaned, pair)
                return
            self.hc.send(entry["address"], cleaned)
        except HcError as error:
            self._audit(fake, "prompt", "type", cleaned, [], "failed", pair)
            self._say(chat, "That didn't go through.")
            self.log(f"{entry['address']}: {scrub(error, self.token)}")
            return
        self._audit(fake, "prompt", "type", cleaned, [], "sent", pair)
        self._say(chat, "Sent.")
        self._note("answered", entry["place"], cleaned)

    # Running

    def _scan_loop(self) -> None:
        while not self.stopping.is_set():
            self.wake.wait(SCAN_S)
            self.wake.clear()
            try:
                self.scan()
            except HcError as error:
                self.log(f"hc: {scrub(error, self.token)}")
            except Exception as error:
                self.log(f"Scan failed: {type(error).__name__}: {scrub(error, self.token)}")
            self.store.update(lambda state: state.update({"heartbeat_ms": self.now()}))

    def _event_loop(self) -> None:
        """Events only make a scan happen sooner. Terminals on other machines are found by the scan itself."""
        while not self.stopping.is_set():
            try:
                process = self.hc.events()
                for line in process.stdout:
                    if self.stopping.is_set():
                        break
                    if b'"method":"event"' in line:
                        self.wake.set()
                process.terminate()
            except (HcError, OSError) as error:
                self.log(f"hc events: {scrub(error, self.token)}")
            self.stopping.wait(3)

    def run(self) -> None:
        self.store.update(lambda state: state.update({"heartbeat_ms": self.now()}))
        for loop in (self._scan_loop, self._event_loop):
            threading.Thread(target=loop, daemon=True).start()
        self.wake.set()
        delay = 1
        while not self.stopping.is_set():
            try:
                self.poll_once()
                delay = 1
            except TelegramError:
                self.stopping.wait(delay)
                delay = min(delay * 2, 60)
