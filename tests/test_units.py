"""The smaller parts: redaction, the Telegram client's limits, the store, the credential store and the commands."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import harness
from harness import HERE, TOKEN, DaemonCase, FakeTelegram, term

import credential
import policy
import redact
import screens
import telegram
import pageme
from prompts import parse
from store import SingleDaemon, Store, empty_state

SCRIPT = str(HERE.parent / "mods" / "pageme" / "pageme.py")


def joined(*parts):
    """Builds a secret-shaped string at run time, so none sits whole in the repo."""
    return "".join(parts)


class Redaction(unittest.TestCase):
    def assertGone(self, secret, text=None):
        out = redact.safe(text if text is not None else f"before {secret} after", 5000)
        self.assertNotIn(secret, out)

    def test_known_shapes(self):
        for secret in [
            joined("sk-ant-", "abcdefghij0123456789"),
            joined("sk-proj-", "abcdefghij0123456789"),
            joined("ghp_", "a1b2c3d4e5f6a1b2c3d4e5f6"),
            joined("github_pat_", "11ABCDEFG0abcdefghij_klmnop"),
            joined("glpat-", "abcdefghij012345"),
            joined("npm_", "abcdefghij0123456789abcd"),
            joined("xoxb-", "1234567890-abcdefghij"),
            joined("sk_live_", "abcdefghij0123456789"),
            joined("AKIA", "ABCDEFGHIJ012345"),
            joined("AIza", "abcdefghij0123456789abcdefghij012"),
            joined("eyJhbGciOiJIUzI1NiJ9", ".", "eyJzdWIiOiIxMjM0In0", ".", "abcdefghij"),
            TOKEN,
        ]:
            self.assertGone(secret)

    def test_private_key_block(self):
        block = joined("-----BEGIN RSA ", "PRIVATE KEY-----\nabc\ndef\n-----END RSA ", "PRIVATE KEY-----")
        self.assertEqual(redact.safe(block, 500), redact.HIDDEN)

    def test_a_cut_off_private_key_is_still_hidden(self):
        self.assertNotIn("abc", redact.safe(joined("-----BEGIN ", "PRIVATE KEY-----\nabc\ndef"), 500))

    def test_password_lines_go_whole(self):
        out = redact.safe("first\nmy password: hunter2 ok\nlast", 500)
        self.assertEqual(out, f"first\n{redact.LINE_HIDDEN}\nlast")

    def test_assigned_values(self):
        for line in ['API_KEY=abc123', 'secret: "open sesame"', "auth_token = 'zzz'", '"client_secret": "zzz999"', "GH_TOKEN=abc"]:
            out = redact.safe(line, 500)
            self.assertIn(redact.HIDDEN, out, line)
            for word in ("abc123", "open sesame", "zzz"):
                self.assertNotIn(word, out)

    def test_bearer_and_url_logins(self):
        self.assertGone("abcdefghij0123456789", "Authorization: Bearer abcdefghij0123456789")
        self.assertGone("s3cret", "postgres://sam:s3cret@db.example.org/sample")

    def test_long_random_words(self):
        self.assertGone("q8Zr2Lk9Wm4Tn7Xv1Bc6Hy3Jd5Pf0Sg")

    def test_a_plain_long_word_stays(self):
        word = "supercalifragilisticexpialidocious"
        self.assertIn(word, redact.safe(word, 500))

    def test_ordinary_text_stays(self):
        text = "Which pet should I draw?\nnode -e sum\nsrc/lib/sample.ts"
        self.assertEqual(redact.safe(text, 500), text)

    def test_known_secrets(self):
        self.assertEqual(redact.safe("a hello b", 500, known=["hello"]), f"a {redact.HIDDEN} b")

    def test_it_redacts_before_it_cuts(self):
        secret = joined("ghp_", "a1b2c3d4e5f6a1b2c3d4e5f6")
        out = redact.safe("x" * 10 + secret, 20)
        self.assertNotIn("ghp_", out)

    def test_cap(self):
        self.assertEqual(len(redact.safe("word " * 500, 100)), 100)

    def test_controls_go(self):
        self.assertEqual(redact.strip_controls("a\x1b[31mb\x07c‮d​e\n"), "abcde\n")

    def test_osc_sequences_go(self):
        self.assertEqual(redact.strip_controls("a\x1b]7501;blocked\x07b"), "ab")


class Policy(unittest.TestCase):
    def test_keys_are_digits_or_right(self):
        for key in ("1", "9", "right"):
            self.assertTrue(policy.PRESSABLE.match(key))
        for key in ("0", "10", "enter", "esc", "y", "ctrl+c", "1 2", "", "up"):
            self.assertFalse(policy.PRESSABLE.match(key), key)

    def test_addresses(self):
        for address in ("t1", "t1b", "mac/t4", "my-box.local/t11q"):
            self.assertTrue(policy.ADDRESS.match(address))
        for address in ("", "--force", "t1 t2", "../t1", "-t1", "mac/t4/x", "mac/--force"):
            self.assertFalse(policy.ADDRESS.match(address), address)

    def test_reply_refusals(self):
        self.assertIsNone(policy.reply_refusal("Please go on"))
        self.assertIsNotNone(policy.reply_refusal("!ls"))
        self.assertIsNotNone(policy.reply_refusal("/model"))
        self.assertIsNotNone(policy.reply_refusal(""))

    def test_type_rule(self):
        question = parse(screens.QUESTION, {"kind": "question"})
        multi = parse(screens.MULTI, {"kind": "question"})
        permission = parse(screens.BASH, {"kind": "permission"})
        unknown = parse(screens.UNKNOWN, {})
        self.assertTrue(policy.may_type(question, "question"))
        self.assertFalse(policy.may_type(multi, "question"))
        self.assertFalse(policy.may_type(permission, "permission"))
        self.assertFalse(policy.may_type(unknown, None))
        self.assertFalse(policy.may_type(unknown, "permission"))
        self.assertTrue(policy.may_type(unknown, "question"))


class TelegramClient(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.pop("PAGEME_TEST_API_BASE", None)

    def tearDown(self):
        os.environ.pop("PAGEME_TEST_API_BASE", None)
        if self.saved:
            os.environ["PAGEME_TEST_API_BASE"] = self.saved

    def test_the_address_is_telegrams_by_default(self):
        self.assertEqual(telegram.base_url(), "https://api.telegram.org")

    def test_a_test_address_must_be_local(self):
        for base in ("https://evil.example", "http://127.0.0.1.evil.example:80", "http://localhost:1", "http://127.0.0.1:80/x", "http://10.0.0.1:80"):
            os.environ["PAGEME_TEST_API_BASE"] = base
            with self.assertRaises(SystemExit):
                telegram.base_url()

    def test_a_local_test_address_is_taken(self):
        os.environ["PAGEME_TEST_API_BASE"] = "http://127.0.0.1:8123"
        self.assertEqual(telegram.base_url(), "http://127.0.0.1:8123")

    def test_other_methods_are_refused(self):
        client = telegram.Telegram(TOKEN)
        for method in ("deleteWebhook", "setWebhook", "getFile", "getMe"):
            with self.assertRaises(ValueError):
                client.call(method, {})

    def test_errors_never_carry_the_token(self):
        self.assertNotIn(TOKEN, telegram.scrub(f"failed at https://api.telegram.org/bot{TOKEN}/sendMessage"))

    def test_redirects_are_not_followed(self):
        import http.server

        hits = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                hits.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/stolen")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        os.environ["PAGEME_TEST_API_BASE"] = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with self.assertRaises(telegram.TelegramError):
                telegram.Telegram(TOKEN).call("sendMessage", {})
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(len(hits), 1)


class Storing(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_starts_empty_unpaired_and_safe(self):
        state = self.store.read()
        self.assertIsNone(state["pair"])
        self.assertEqual(state["settings"], {"paused": False, "mode": "act", "approvals": False, "finished": False, "remote": False})

    def test_a_corrupt_file_means_unpaired(self):
        self.store.update(lambda s: s.update({"pair": {"user_id": 1, "chat_id": 1, "name": "x", "ms": 1}}))
        self.store.path.write_text("{ not json", encoding="utf-8")
        self.assertIsNone(self.store.read()["pair"])

    def test_a_moment_of_lost_file_access_is_not_damage(self):
        self.store.update(lambda s: s.update({"pair": {"user_id": 1, "chat_id": 1, "name": "x", "ms": 1}}))
        real_open, failures = open, [0]

        def flaky(path, *args, **kwargs):
            if str(path) == str(self.store.path) and failures[0] < 3:
                failures[0] += 1
                raise PermissionError("in use")
            return real_open(path, *args, **kwargs)

        with mock.patch("builtins.open", flaky):
            self.assertEqual(self.store.read()["pair"]["user_id"], 1)
        self.assertEqual(failures[0], 3)
        self.assertEqual([p for p in self.store.folder.iterdir() if "corrupt" in p.name], [])

    def test_a_file_that_stays_unreadable_raises_and_wipes_nothing(self):
        self.store.update(lambda s: s.update({"pair": {"user_id": 1, "chat_id": 1, "name": "x", "ms": 1}}))
        real_open = open

        def stuck(path, *args, **kwargs):
            if str(path) == str(self.store.path):
                raise PermissionError("in use")
            return real_open(path, *args, **kwargs)

        with mock.patch("builtins.open", stuck), mock.patch("store.time.sleep"):
            with self.assertRaises(PermissionError):
                self.store.read()
        self.assertEqual(self.store.read()["pair"]["user_id"], 1)

    def test_changes_from_two_processes_do_not_lose_each_other(self):
        code = (
            "import sys; sys.dont_write_bytecode=True; sys.path.insert(0, sys.argv[1]);"
            "from store import Store; from pathlib import Path; s=Store(Path(sys.argv[2]));"
            "[s.update(lambda st: st.update({'offset': st['offset']+1})) for _ in range(40)]"
        )
        folder = str(HERE.parent / "mods" / "pageme")
        runs = [subprocess.Popen([sys.executable, "-B", "-c", code, folder, self.temp.name]) for _ in range(3)]
        for run in runs:
            self.assertEqual(run.wait(), 0)
        self.assertEqual(self.store.read()["offset"], 120)

    def test_recent_is_bounded(self):
        for n in range(50):
            self.store.update(lambda s: self.store.add_recent(s, n, "asked", "t1", "x"))
        self.assertEqual(len(self.store.read()["recent"]), 30)

    def test_one_daemon_at_a_time(self):
        first, second = SingleDaemon(self.store.folder), SingleDaemon(self.store.folder)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        self.assertTrue(second.acquire())
        second.release()

    @unittest.skipIf(sys.platform == "win32", "Windows files use the profile folder's access list")
    def test_files_are_private(self):
        self.store.update(lambda s: None)
        self.store.audit({"x": 1})
        for path in (self.store.path, self.store.audit_path):
            self.assertEqual(path.stat().st_mode & 0o077, 0)
        self.assertEqual(self.store.folder.stat().st_mode & 0o077, 0)


class Credentials(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["PAGEME_HOME"] = self.temp.name
        os.environ["PAGEME_TEST_CREDENTIAL"] = f"herdr-pageme-test/{os.getpid()}"

    def tearDown(self):
        credential.clear()
        os.environ.pop("PAGEME_TEST_CREDENTIAL", None)
        os.environ.pop("PAGEME_HOME", None)
        self.temp.cleanup()

    def test_a_token_goes_in_and_comes_out_of_the_system_store(self):
        if sys.platform not in ("win32", "linux"):
            self.skipTest("the macOS path needs a real keychain")
        self.assertIsNone(credential.load())
        credential.save(TOKEN)
        self.assertEqual(credential.load(), TOKEN)
        credential.clear()
        self.assertIsNone(credential.load())

    def test_clearing_nothing_is_fine(self):
        credential.clear()

    def test_a_bad_token_is_refused(self):
        for token in ("", "abc", "123:short", TOKEN + " ", 'x" -w "y'):
            with self.assertRaises(ValueError):
                credential.save(token)

    def test_no_token_on_disk_on_windows(self):
        if sys.platform != "win32":
            self.skipTest("Windows only")
        credential.save(TOKEN)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_the_mac_path_uses_stdin_not_argv(self):
        with mock.patch.object(credential.sys, "platform", "darwin"), mock.patch.object(credential.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=b"")
            credential.save(TOKEN)
        argv, kwargs = run.call_args[0][0], run.call_args[1]
        self.assertEqual(argv, ["security", "-i"])
        self.assertIn(TOKEN.encode(), kwargs["input"])

    def test_the_file_path_writes_a_private_file(self):
        real_platform = sys.platform  # The patch below changes the one shared sys module.
        with mock.patch.object(credential.sys, "platform", "linux"):
            credential.save(TOKEN)
            self.assertEqual(credential.load(), TOKEN)
            path = Path(self.temp.name) / "token"
            if real_platform != "win32":
                self.assertEqual(path.stat().st_mode & 0o077, 0)
            credential.clear()
            self.assertFalse(path.exists())


class Commands(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "PAGEME_HOME": self.temp.name, "PAGEME_TEST_CREDENTIAL": f"herdr-pageme-test/cmd{os.getpid()}", "PYTHONIOENCODING": "utf-8"}

    def tearDown(self):
        subprocess.run([sys.executable, "-B", SCRIPT, "token", "--clear"], env=self.env, capture_output=True)
        self.temp.cleanup()

    def pageme(self, *args, stdin=None):
        return subprocess.run([sys.executable, "-B", SCRIPT, *args], env=self.env, capture_output=True, input=stdin, text=True, encoding="utf-8")

    def status(self):
        return json.loads(self.pageme("status").stdout)

    def test_status_with_nothing_set_up(self):
        status = self.status()
        self.assertEqual((status["token"], status["running"], status["connected"], status["paired"], status["approvals"]), (False, False, False, None, False))

    def test_a_token_from_a_pipe(self):
        done = self.pageme("token", stdin=TOKEN + "\n")
        self.assertEqual(done.returncode, 0)
        self.assertNotIn(TOKEN, done.stdout + done.stderr)
        self.assertTrue(self.status()["token"])

    def test_a_bad_token_from_a_pipe(self):
        self.assertEqual(self.pageme("token", stdin="nonsense\n").returncode, 1)
        self.assertFalse(self.status()["token"])

    def test_pair_shows_a_code_in_status(self):
        code = json.loads(self.pageme("pair").stdout)["code"]
        status = self.status()
        self.assertEqual(status["code"]["value"], code)
        self.assertGreater(status["code"]["seconds"], 280)

    def test_settings(self):
        self.pageme("approvals", "on")
        self.pageme("finished", "on")
        self.pageme("pause")
        self.pageme("mode", "watch")
        status = self.status()
        self.assertEqual((status["approvals"], status["finished"], status["paused"], status["mode"]), (True, True, True, "watch"))

    def test_approvals_take_only_on_or_off(self):
        self.assertNotEqual(self.pageme("approvals", "maybe").returncode, 0)

    def test_run_with_no_token_says_so(self):
        done = self.pageme("run")
        self.assertEqual(done.returncode, 1)
        self.assertIn("No bot token", done.stdout)

    def test_demo_status_has_made_up_data(self):
        status = json.loads(self.pageme("status", "--demo").stdout)
        self.assertTrue(status["demo"])
        self.assertGreater(len(status["recent"]), 3)
        self.assertEqual(status["latest"]["state"], "open")

    def test_a_named_demo(self):
        self.assertTrue(json.loads(self.pageme("status", "--demo", "paused").stdout)["paused"])

    def test_status_has_the_page_and_todays_numbers(self):
        status = json.loads(self.pageme("status").stdout)
        self.assertIsNone(status["latest"])
        self.assertEqual(status["today"]["pages"], 0)
        self.assertEqual(status["today"]["hours"], [0] * 24)


class PanelData(unittest.TestCase):
    """What `status` adds for the panel. It reads the state and nothing else."""

    NOW = 1_800_000_000_000

    def record(self, ms, state="open", place="t1 · app", **more):
        return {"pid": str(ms), "ms": ms, "place": place, "kind": "question", "state": state, **more}

    def state(self, records, recent=()):
        return {**empty_state(), "prompts": {r["pid"]: r for r in records}, "recent": list(recent)}

    def test_no_questions_means_no_page(self):
        self.assertIsNone(pageme.latest_page(self.state([])))

    def test_the_newest_question_is_the_page(self):
        older = self.record(1, asked="Old?", labels=["A"], agent="codex")
        newer = self.record(2, asked="Which pet?", labels=["Cat", "Dog"], agent="claude-code")
        page = pageme.latest_page(self.state([newer, older]))
        self.assertEqual(page["text"], "Which pet?")
        self.assertEqual(page["options"], ["Cat", "Dog"])
        self.assertEqual(page["lead"], "Claude Code has a question")
        self.assertEqual(page["state"], "open")
        self.assertIsNone(page["answer"])

    def test_a_used_page_names_the_nearest_answer_after_it(self):
        recent = [
            {"ms": 30, "kind": "answered", "where": "t1 · app", "text": "Later"},
            {"ms": 20, "kind": "answered", "where": "t1 · app", "text": "Dog"},
            {"ms": 15, "kind": "answered", "where": "t2 · other", "text": "Elsewhere"},
            {"ms": 5, "kind": "answered", "where": "t1 · app", "text": "Before"},
        ]
        page = pageme.latest_page(self.state([self.record(10, "used", asked="Which pet?")], recent))
        self.assertEqual(page["answer"], "Dog")

    def test_a_record_from_an_older_daemon_still_shows(self):
        recent = [{"ms": 10, "kind": "asked", "where": "t1 · app", "text": "From recent"}]
        page = pageme.latest_page(self.state([self.record(10)], recent))
        self.assertEqual(page["text"], "From recent")
        self.assertEqual(page["options"], [])
        self.assertEqual(page["lead"], "An agent has a question")

    def test_today_counts_only_today(self):
        start = pageme.day_start(self.NOW)
        records = [self.record(start - 1, "used"), self.record(start, "used"), self.record(start + 1), self.record(start + 2, "expired")]
        stats = pageme.day_stats(self.state(records), self.NOW)
        self.assertEqual(stats["pages"], 3)
        self.assertEqual(stats["answered"], 1)

    def test_reply_time_is_the_middle_gap(self):
        start = pageme.day_start(self.NOW)
        records = [self.record(start + i * 1000, "used", place=f"t{i}") for i in range(3)]
        recent = [{"ms": start + i * 1000 + (i + 1) * 100, "kind": "answered", "where": f"t{i}", "text": "x"} for i in range(3)]
        self.assertEqual(pageme.day_stats(self.state(records, recent), self.NOW)["reply_ms"], 200)

    def test_no_answers_means_no_reply_time(self):
        self.assertIsNone(pageme.day_stats(self.state([]), self.NOW)["reply_ms"])

    def test_hours_are_the_last_24_oldest_first(self):
        hour = pageme.HOUR_MS
        records = [self.record(self.NOW - 1), self.record(self.NOW - 2), self.record(self.NOW - 23 * hour - 1), self.record(self.NOW - 24 * hour - 1)]
        hours = pageme.day_stats(self.state(records), self.NOW)["hours"]
        self.assertEqual(len(hours), 24)
        self.assertEqual(hours[23], 2)
        self.assertEqual(hours[0], 1)
        self.assertEqual(sum(hours), 3)

    def test_every_demo_has_what_the_panel_reads(self):
        from sample import DEMOS, demo_status

        for name in DEMOS:
            status = demo_status(self.NOW, name)
            for key in ("token", "running", "connected", "paired", "code", "paused", "recent", "latest", "today"):
                self.assertIn(key, status, name)
            self.assertEqual(len(status["today"]["hours"]), 24, name)
        self.assertTrue(demo_status(self.NOW, "paused")["paused"])
        self.assertFalse(demo_status(self.NOW, "offline")["connected"])
        self.assertIsNone(demo_status(self.NOW, "quiet")["latest"])
        self.assertFalse(demo_status(self.NOW, "no-token")["token"])
        self.assertEqual(demo_status(self.NOW, "answered")["latest"]["answer"], "Green")
        self.assertIsNotNone(demo_status(self.NOW, "pairing")["code"])


class WholeDaemon(unittest.TestCase):
    """The real program, with its threads, against the fake hc and the fake server."""

    def test_pair_tap_and_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            server = FakeTelegram()
            world = Path(folder) / "world.json"
            world.write_text(json.dumps({"terminals": {"t1": term("t1", screens.QUESTION)}, "journal": []}), encoding="utf-8")
            env = {
                **os.environ,
                "PAGEME_HOME": folder,
                "PAGEME_TEST_API_BASE": server.base,
                "PAGEME_TEST_HC": json.dumps([sys.executable, "-B", str(HERE / "fake_hc.py")]),
                "PAGEME_TEST_CREDENTIAL": f"herdr-pageme-test/run{os.getpid()}",
                "FAKE_HC_WORLD": str(world),
                "PYTHONIOENCODING": "utf-8",
            }

            def cli(*args, stdin=None):
                return subprocess.run([sys.executable, "-B", SCRIPT, *args], env=env, capture_output=True, input=stdin, text=True, encoding="utf-8")

            self.assertEqual(cli("token", stdin=TOKEN + "\n").returncode, 0)
            code = json.loads(cli("pair").stdout)["code"]
            process = subprocess.Popen([sys.executable, "-B", SCRIPT, "run"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            try:
                import time as clock

                def until(check, what):
                    for _ in range(400):
                        if check():
                            return
                        clock.sleep(0.05)
                    self.fail(f"never saw: {what}")

                now = int(clock.time())
                server.queue.append({"update_id": 1, "message": {"message_id": 1, "from": harness.OWNER, "chat": harness.OWNER_CHAT, "date": now, "text": code}})
                until(lambda: json.loads(cli("status").stdout)["paired"], "paired")
                until(lambda: any(call["method"] == "sendMessage" and "reply_markup" in call["body"] for call in server.calls), "the question")
                body = next(call["body"] for call in server.calls if call["method"] == "sendMessage" and "reply_markup" in call["body"])
                data = body["reply_markup"]["inline_keyboard"][1][0]["callback_data"]
                server.queue.append({"update_id": 2, "callback_query": {"id": "q", "from": harness.OWNER, "data": data, "message": {"message_id": server.next_id, "chat": harness.OWNER_CHAT}}})

                def pressed():
                    journal = json.loads(world.read_text(encoding="utf-8"))["journal"]
                    return ["keys", "t1", "2"] in journal

                until(pressed, "the key press")
                status = json.loads(cli("status").stdout)
                self.assertTrue(status["running"])
                self.assertTrue(status["connected"])
                self.assertEqual(status["recent"][0]["text"], "Dog")
            finally:
                process.terminate()
                process.wait(timeout=10)
                output = process.stdout.read().decode("utf-8", "replace")
                process.stdout.close()
                cli("token", "--clear")
                server.stop()
            self.assertNotIn(TOKEN, output)


if __name__ == "__main__":
    unittest.main()
