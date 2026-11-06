"""Tries the real daemon on a real Claude Code session, with only Telegram faked. It starts its own throwaway Haiku session in a
folder you name, and that session is the only terminal it presses anything in.

    HC_SESSION=<private> python tests/live_check.py <scratch folder>

It refuses to run on the default core, because the daemon in act mode answers every blocked agent it can see. It needs a
private core that holds nothing else, and it stops if it finds any other terminal there. Screens are checked in memory and
never written to a file. A first run in a new folder may stop at Claude Code's trust question: accept that yourself, on a
scratch folder only, then run this again.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))

from harness import FakeTelegram, OWNER, OWNER_CHAT, TOKEN  # noqa: E402

SCRIPT = str(HERE.parent / "mods" / "pageme" / "pageme.py")
NAME = "pageme-live"
DAEMON = "pageme-live-daemon"
results = []


def hc(*args):
    done = subprocess.run(["hc", *args], capture_output=True, timeout=40)
    return done.returncode, done.stdout.decode("utf-8", "replace")


def note(name, passed, detail=""):
    results.append(passed)
    print(f"{'ok  ' if passed else 'FAIL'} {name}{': ' + detail if detail else ''}", flush=True)


class Stop(Exception):
    """A step never happened, so the steps after it mean nothing."""


class Live:
    def __init__(self, folder):
        self.folder = folder
        self.server = FakeTelegram()
        self.home = tempfile.TemporaryDirectory()
        self.update_id = 0
        self.env = {
            **os.environ,
            "PAGEME_HOME": self.home.name,
            "PAGEME_TEST_API_BASE": self.server.base,
            "PAGEME_TEST_CREDENTIAL": f"herdr-pageme-test/live{os.getpid()}",
            "PYTHONIOENCODING": "utf-8",
        }

    def cli(self, *args, stdin=None):
        return subprocess.run([sys.executable, "-B", SCRIPT, *args], env=self.env, capture_output=True, input=stdin, text=True, encoding="utf-8")

    def status(self):
        return json.loads(self.cli("status").stdout)

    def until(self, check, seconds=90):
        end = time.time() + seconds
        while time.time() < end:
            value = check()
            if value:
                return value
            time.sleep(0.5)
        return None

    def push(self, **payload):
        self.update_id += 1
        self.server.queue.append({"update_id": self.update_id, **payload})

    def say(self, text, reply_to=None):
        message = {"message_id": 7000 + self.update_id, "from": OWNER, "chat": OWNER_CHAT, "date": int(time.time()), "text": text}
        if reply_to:
            message["reply_to_message"] = {"message_id": reply_to}
        self.push(message=message)

    def tap(self, body, label):
        button = next(b for row in body["reply_markup"]["inline_keyboard"] for b in row if b["text"] == label)
        self.push(callback_query={"id": f"q{self.update_id}", "from": OWNER, "data": button["callback_data"], "message": {"message_id": body["_id"], "chat": OWNER_CHAT}})

    def messages(self):
        """Sent messages, each with the id the fake server gave it, oldest first."""
        out, next_id = [], 500
        for call in list(self.server.calls):
            if call["method"] == "sendMessage":
                next_id += 1
                out.append({**call["body"], "_id": next_id})
        return out

    def wait_message(self, seen, text):
        def find():
            fresh = self.messages()[seen:]
            return next((m for m in fresh if text in m["text"]), None)

        found = self.until(find)
        if not found:
            note(f"a message saying {text!r} arrives", False)
            raise Stop()
        return found

    def agent(self, task):
        """Sends the throwaway session a task, and checks it started. A send to a session still booting can be dropped."""
        code, out = hc("send", NAME, "--", task)
        if code != 0 or not json.loads(out).get("started"):
            note("the session took the task", False, out[:120])
            raise Stop()

    def state(self):
        _, out = hc("get", NAME, "--json")
        return (json.loads(out).get("status") or {}) if out.strip() else {}

    def idle(self):
        return self.until(lambda: self.state().get("state") in ("done", "idle"))


def main():
    if os.environ.get("HC_SESSION", "default") in ("", "default"):
        sys.exit("Refusing: set HC_SESSION to a private core.")
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        sys.exit("Usage: live_check.py <scratch folder>")
    folder = sys.argv[1]
    _, listed = hc("ls", "--json")
    others = [t["address"] for t in json.loads(listed)["terminals"] if t.get("name") not in (NAME, DAEMON)]
    if others:
        sys.exit(f"Refusing: this core has other terminals: {others}")

    live = Live(folder)
    code, out = hc("run", "--bg", "--json", "--name", NAME, "--cwd", folder, "--", "claude", "--model", "haiku", "--permission-mode", "default")
    if code != 0:
        sys.exit("The throwaway session wouldn't start.")
    live.until(lambda: live.state().get("state") in ("idle", "done"), 40)
    if live.state().get("state") not in ("idle", "done"):
        hc("kill", NAME)
        sys.exit("The session never came up. It may be at the trust question.")
    time.sleep(15)  # Reporting idle comes before it will really take input.

    live.cli("token", stdin=TOKEN + "\n")
    pairing = json.loads(live.cli("pair").stdout)["code"]
    # Started the way the panel starts it, as a kept terminal, so `hc` runs from inside a terminal as it will for real. A new
    # terminal doesn't get this script's environment, so a small launcher in the temp folder sets the test's. It holds no token.
    launcher = Path(live.home.name) / "launch.py"
    wanted = {name: live.env[name] for name in ("PAGEME_HOME", "PAGEME_TEST_API_BASE", "PAGEME_TEST_CREDENTIAL", "PYTHONIOENCODING")}
    launcher.write_text(
        f"import os, runpy, sys\nos.environ.update({wanted!r})\nsys.argv = [{SCRIPT!r}, 'run']\nrunpy.run_path({SCRIPT!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    code, _out = hc(
        "run", "--bg", "--keep", "--no-notify", "--no-parent", "--outlive-parent", "--name", DAEMON, "--label", "pageme=daemon",
        "--cwd", live.home.name, "--", sys.executable, "-B", str(launcher),
    )
    if code != 0:
        hc("kill", NAME)
        sys.exit("The daemon's terminal wouldn't start.")
    try:
        live.say(pairing)
        note("pairs", bool(live.until(lambda: live.status()["paired"], 30)))
        live.cli("finished", "on")

        # A question, answered by a button.
        seen = len(live.messages())
        live.agent("Use the AskUserQuestion tool once, with a single question: pick a pet, options Cat and Dog. Single select. Do nothing else.")
        message = live.wait_message(seen, "has a question")
        labels = [b["text"] for row in (message or {}).get("reply_markup", {}).get("inline_keyboard", []) for b in row]
        note("a question gives one button per option", labels == ["Cat", "Dog"], str(labels))
        live.tap(message, "Dog")
        note("a tap answers it on the real session", bool(live.idle()))
        _, screen = hc("read", NAME, "--lines", "30")
        note("the agent got the answer", "→ Dog" in screen)

        # A permission prompt, with approving off: No is the only button, and a forged Yes presses nothing.
        seen = len(live.messages())
        live.agent('Use the Bash tool to run exactly: python -c "print(6*7)" . Do nothing else.')
        message = live.wait_message(seen, "wants approval")
        labels = [b["text"] for row in (message or {}).get("reply_markup", {}).get("inline_keyboard", []) for b in row]
        note("approving off offers only No", labels == ["No"], str(labels))
        pid = message["reply_markup"]["inline_keyboard"][0][0]["callback_data"].split(":")[0]
        live.push(callback_query={"id": "forged", "from": OWNER, "data": f"{pid}:o1", "message": {"message_id": message["_id"], "chat": OWNER_CHAT}})
        time.sleep(4)
        note("a forged Yes presses nothing", live.state().get("state") == "blocked")
        live.say("1", reply_to=message["_id"])
        time.sleep(4)
        note("a text reply can't approve it", live.state().get("state") == "blocked")
        live.tap(message, "No")
        note("No refuses it on the real session", bool(live.idle()))

        # Approving on, then a Yes.
        live.cli("approvals", "on")
        seen = len(live.messages())
        live.agent('Use the Bash tool to run exactly: python -c "print(8*8)" . Do nothing else.')
        message = live.wait_message(seen, "wants approval")
        labels = [b["text"] for row in (message or {}).get("reply_markup", {}).get("inline_keyboard", []) for b in row]
        note("approving on offers Yes and No and no lasting option", labels == ["Yes", "No"], str(labels))
        live.tap(message, "Yes")
        note("Yes runs it on the real session", bool(live.idle()))
        live.cli("approvals", "off")

        # A two-question wizard, whose second page sends no event.
        seen = len(live.messages())
        live.agent("Use the AskUserQuestion tool once with TWO questions in the same call. Question 1: pick a size, options Small and Large. Question 2: pick a shape, options Round and Square. Single select each. Do nothing else.")
        one = live.wait_message(seen, "size")
        live.tap(one, "Large")
        two = live.wait_message(seen, "shape")
        note("a wizard's next page arrives with no event", bool(two))
        live.tap(two, "Round")
        review = live.wait_message(seen, "Ready to submit")
        note("the review page arrives", bool(review))
        live.tap(review, "Submit answers")
        note("the wizard finishes", bool(live.idle()))

        # A multi-select: ticks stay in the chat, Done presses.
        seen = len(live.messages())
        live.agent("Use the AskUserQuestion tool once, with a single question with multiSelect true: pick toppings, options Cheese, Olives, Basil. Do nothing else.")
        message = live.wait_message(seen, "has a question")
        rows = message["reply_markup"]["inline_keyboard"]
        pid = rows[0][0]["callback_data"].split(":")[0]
        for key in ("t1", "t3"):
            live.push(callback_query={"id": key, "from": OWNER, "data": f"{pid}:{key}", "message": {"message_id": message["_id"], "chat": OWNER_CHAT}})
        time.sleep(3)
        live.push(callback_query={"id": "d", "from": OWNER, "data": f"{pid}:d", "message": {"message_id": message["_id"], "chat": OWNER_CHAT}})
        review = live.wait_message(seen, "Ready to submit")
        note("multi-select reaches the review page", bool(review))
        note("the review shows the picks", bool(review) and "Cheese" in review["text"] and "Basil" in review["text"] and "Olives" not in review["text"].split("Ready")[0].split("→")[-1])
        live.tap(review, "Submit answers")
        note("multi-select finishes", bool(live.idle()))

        # Free text in a question, with the characters keys can't type.
        seen = len(live.messages())
        live.agent("Use the AskUserQuestion tool once, with a single question: pick a name, options Alpha and Beta. Single select. Do nothing else.")
        message = live.wait_message(seen, "has a question")
        text = 'Hello, "world"! $5 é'
        live.say(text, reply_to=message["_id"])
        note("a typed answer reaches the session", bool(live.idle()))
        _, screen = hc("read", NAME, "--lines", "40")
        note("it arrives exactly, with no hc tag", text in screen and "<hc" not in screen)

        # A finished message, a new prompt by reply, and the bang that must not get through.
        seen = len(live.messages())
        live.agent("Reply with the word done and nothing else.")
        message = live.wait_message(seen, "finished")
        note("an agent finishing sends a message", bool(message))
        marker = Path(folder) / "pageme-bang-check.txt"
        marker.unlink(missing_ok=True)
        before = len(live.messages())
        live.say('!python -c "open(\'pageme-bang-check.txt\',\'w\').write(\'x\')"', reply_to=message["_id"])
        refused = live.wait_message(before, "Refused")
        time.sleep(3)
        note("a ! reply is refused and runs nothing", bool(refused) and not marker.exists())
        seen = len(live.messages())
        live.say("Reply with the word again and nothing else.", reply_to=message["_id"])
        note("a reply to a finished agent is a new prompt", bool(live.wait_message(seen, "finished")))

        # Stale: answered at the terminal, then tapped.
        seen = len(live.messages())
        live.agent("Use the AskUserQuestion tool once, with a single question: pick one, options Up and Down. Single select. Do nothing else.")
        message = live.wait_message(seen, "has a question")
        hc("keys", NAME, "1")
        live.idle()
        calls = len(live.server.calls)
        live.tap(message, "Down")
        answered = live.until(lambda: [c for c in live.server.calls[calls:] if c["method"] == "answerCallbackQuery"], 15)
        note("a stale tap gets a plain refusal", bool(answered), answered[0]["body"]["text"] if answered else "")

        everything = json.dumps([call["body"] for call in live.server.calls])
        note("the token was never in a message", TOKEN not in everything)
        audit = (Path(live.home.name) / "audit.jsonl").read_text(encoding="utf-8")
        note("every answer is in the audit log", audit.count('"result": "sent"') >= 8, f"{audit.count(chr(10))} lines")
    except Stop:
        pass
    finally:
        _code, log = hc("read", DAEMON, "--lines", "200")
        hc("kill", DAEMON)
        hc("rm", DAEMON)
        if TOKEN in log:
            note("the daemon's output never had the token", False)
        if not all(results):
            # Headings and the daemon's own lines only. Screen text stays out of this output too.
            print("daemon said:", log[-1500:].replace(TOKEN, "<token>"))
            print("messages:", [m["text"].split("<pre>")[0][:70] for m in live.messages()])
        live.cli("token", "--clear")
        hc("kill", NAME)
        hc("rm", NAME)
        live.server.stop()
    print(f"{sum(results)} of {len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
