"""What the daemon tests share: a local fake Telegram server, a world for the fake hc, and a daemon wired to both. Nothing here
reaches a real core or the real Telegram. The fake server listens on 127.0.0.1 only."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent / "mods" / "pageme"))
sys.path.insert(0, str(HERE))

# Built in two parts so no whole token-shaped string sits in the repo.
TOKEN = "123456789:" + "AAtestonly" + "x" * 26
OWNER = {"id": 1001, "first_name": "Sam", "is_bot": False}
OWNER_CHAT = {"id": 1001, "type": "private"}
STRANGER = {"id": 2002, "first_name": "Eve", "is_bot": False}
STRANGER_CHAT = {"id": 2002, "type": "private"}
NOW = 1_800_000_000_000


class FakeTelegram:
    """Records every call. `queue` holds updates for the next getUpdates. `fail` makes a method answer with an error."""

    def __init__(self):
        self.calls = []
        self.queue = []
        self.fail = {}
        self.next_id = 500
        self.lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                _, bot, method = self.path.split("/", 2)
                reply = outer.handle(bot, method, body)
                data = json.dumps(reply).encode("utf-8")
                self.send_response(reply.get("error_code") or 200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, _request, _address):
                pass  # A client hanging up mid-poll isn't news.

        self.server = Server(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def handle(self, bot, method, body):
        # getUpdates waits, as the real one does, or a daemon's main loop would spin.
        if method == "getUpdates" and body.get("timeout"):
            end = time.time() + min(body["timeout"], 1)
            while not self.queue and time.time() < end:
                time.sleep(0.02)
        with self.lock:
            self.calls.append({"bot": bot, "method": method, "body": body})
            if method in self.fail:
                return self.fail[method]
            if method == "getUpdates":
                updates, self.queue = self.queue, []
                return {"ok": True, "result": updates}
            if method == "sendMessage":
                self.next_id += 1
                return {"ok": True, "result": {"message_id": self.next_id, "chat": {"id": body["chat_id"]}}}
            return {"ok": True, "result": True}

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def sent(self, method="sendMessage"):
        return [call["body"] for call in self.calls if call["method"] == method]

    def last_text(self):
        return self.sent()[-1]["text"]

    def buttons(self, body=None):
        body = body or self.sent()[-1]
        rows = (body.get("reply_markup") or {}).get("inline_keyboard") or []
        return [button for row in rows for button in row]


def term(address, screen, kind="question", app="claude-code", state="blocked", **extra):
    status = {"app": app, "state": state}
    if kind:
        status["kind"] = kind
    terminal = {
        "address": address,
        "state": "live",
        "cwd": "/home/sam/sample-app",
        "created_ms": 111,
        "turn": 4,
        "status_ms": 222,
        "status": status,
        "screen": screen,
    }
    terminal.update(extra)
    return terminal


class DaemonCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.world_path = self.folder / "world.json"
        self.telegram = FakeTelegram()
        self.env = {
            "PAGEME_TEST_API_BASE": self.telegram.base,
            "PAGEME_TEST_HC": json.dumps([sys.executable, "-B", str(HERE / "fake_hc.py")]),
            "FAKE_HC_WORLD": str(self.world_path),
            "PAGEME_HOME": str(self.folder / "home"),
        }
        self.saved = {name: os.environ.get(name) for name in self.env}
        os.environ.update(self.env)
        self.world({})
        self.clock = [NOW]
        self.logged = []
        self.daemon = self.make_daemon()
        self.update_id = 100

    def tearDown(self):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.telegram.stop()
        self.temp.cleanup()

    def make_daemon(self):
        from daemon import Daemon
        from hcli import Hc
        from store import Store
        from telegram import Telegram

        self.store = Store()
        return Daemon(Hc(), Telegram(TOKEN), self.store, token=TOKEN, clock=lambda: self.clock[0], log=self.logged.append, settle_s=0)

    # The world

    def world(self, terminals):
        self.write_world({"terminals": terminals, "journal": []})

    def write_world(self, world):
        self.world_path.write_text(json.dumps(world), encoding="utf-8")

    def read_world(self):
        return json.loads(self.world_path.read_text(encoding="utf-8"))

    def change(self, address, **fields):
        world = self.read_world()
        world["terminals"][address].update(fields)
        self.write_world(world)

    def journal(self, command=None):
        calls = self.read_world()["journal"]
        return [call for call in calls if command is None or call[0] == command]

    def typed(self):
        """Every call that puts something into a terminal."""
        return [call for call in self.journal() if call[0] in ("keys", "send")]

    # Telegram traffic

    def update(self, **payload):
        self.update_id += 1
        return {"update_id": self.update_id, **payload}

    def deliver(self, *updates):
        self.telegram.queue.extend(updates)
        self.daemon.poll_once(wait=0)

    def say(self, text, sender=OWNER, chat=OWNER_CHAT, date=None, **extra):
        message = {"message_id": 9000 + self.update_id, "from": sender, "chat": chat, "date": (date or self.clock[0]) // 1000, "text": text, **extra}
        self.deliver(self.update(message=message))

    def reply(self, message_id, text, sender=OWNER, chat=OWNER_CHAT):
        self.say(text, sender, chat, reply_to_message={"message_id": message_id})

    def tap(self, data, message_id=None, sender=OWNER, chat=OWNER_CHAT):
        if message_id is None:
            message_id = self.telegram.next_id
        query = {"id": f"q{self.update_id}", "from": sender, "data": data, "message": {"message_id": message_id, "chat": chat}}
        self.deliver(self.update(callback_query=query))

    def answers(self):
        return [body["text"] for body in self.telegram.sent("answerCallbackQuery")]

    # Set-ups

    def pair(self):
        import pageme

        code = pageme.make_code(self.store)["code"]
        # make_code uses the wall clock, and tests run on their own.
        self.store.update(lambda state: state["code"].update({"created_ms": self.clock[0], "expires_ms": self.clock[0] + 300_000}))
        self.say(code)
        self.assertTrue(self.store.read()["pair"])
        self.telegram.calls.clear()

    def remote(self):
        def turn_on(state):
            state["settings"]["remote"] = True

        self.store.update(turn_on)

    def blocked(self, address="t1", screen=None, **extra):
        """A paired daemon and one terminal blocked on `screen`, already scanned."""
        import screens

        self.pair()
        self.world({address: term(address, screen or screens.QUESTION, **extra)})
        self.daemon.scan()

    def set(self, **settings):
        self.store.update(lambda state: state["settings"].update(settings))

    def button(self, label):
        return next(button for button in self.telegram.buttons() if button["text"] == label)["callback_data"]

    def pid(self):
        return next(iter(self.store.read()["prompts"]))
