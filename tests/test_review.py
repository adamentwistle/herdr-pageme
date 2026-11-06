"""One test or more for each finding of the independent security review, written before the fix to prove the finding was real."""
import json
import unittest

from harness import DaemonCase, term

import policy
import redact
import screens
import pageme
from prompts import fingerprint, parse

PERMISSION = {"app": "claude-code", "kind": "permission", "state": "blocked"}
QUESTION = {"app": "claude-code", "kind": "question", "state": "blocked"}
NO_CURSOR = screens.BASH.replace("❯ 1. Yes", "  1. Yes")
SECRET = "sk-" + "abcdefghij" * 3


class TextOnUnreadScreens(DaemonCase):
    """Finding 1: a typed digit on a menu PageMe couldn't read would pick any option, the lasting ones included."""

    def test_a_reported_permission_takes_no_text_with_approvals_on(self):
        self.pair()
        self.set(approvals=True)
        self.world({"t1": term("t1", NO_CURSOR, kind="permission")})
        self.daemon.scan()
        self.reply(self.telegram.next_id, "please choose the second one")
        self.assertEqual(self.typed(), [])

    def test_an_unread_menu_takes_no_text_on_a_stale_question_report(self):
        self.blocked(screen=NO_CURSOR, kind="question")
        self.reply(self.telegram.next_id, "please choose the second one")
        self.assertEqual(self.typed(), [])

    def test_no_kind_takes_no_text_even_with_approvals_on(self):
        self.pair()
        self.set(approvals=True)
        self.world({"t1": term("t1", screens.UNKNOWN, kind=None, app="other")})
        self.daemon.scan()
        self.reply(self.telegram.next_id, "carry on with it")
        self.assertEqual(self.typed(), [])

    def test_a_single_key_answer_is_refused_on_an_unread_question(self):
        self.blocked(screen=screens.UNKNOWN, kind="question", app="other")
        message = self.telegram.next_id  # Each refusal is a new message, which moves next_id.
        for text in ("y", "2", "yes", "a"):
            self.reply(message, text)
        self.assertEqual(self.typed(), [])
        self.assertEqual(self.store.audit_path.read_text(encoding="utf-8").count('"result": "refused"'), 4)

    def test_a_real_sentence_still_goes_to_an_unread_question(self):
        self.blocked(screen=screens.UNKNOWN, kind="question", app="other")
        self.reply(self.telegram.next_id, "not until the tests pass")
        self.assertEqual(self.typed(), [["send", "--force", "t1", "--", "not until the tests pass"]])


class MultiSelectConfirmation(DaemonCase):
    """Finding 2: Done joined raw labels into the confirmation, after the buttons had hidden them."""

    def test_a_secret_in_a_label_stays_hidden_after_done(self):
        self.blocked(screen=screens.MULTI.replace("[ ] Cheese", f"[ ] {SECRET}"))
        pid = self.pid()
        self.tap(f"{pid}:t1")
        self.tap(f"{pid}:d")
        self.assertEqual(len(self.journal("keys")), 1)
        self.assertNotIn(SECRET, json.dumps([call["body"] for call in self.telegram.calls]))
        self.assertNotIn(SECRET, self.store.audit_path.read_text(encoding="utf-8"))
        self.assertNotIn(SECRET, json.dumps(self.store.read()))

    def test_markup_in_a_label_stays_escaped_after_done(self):
        self.blocked(screen=screens.MULTI.replace("[ ] Cheese", "[ ] <b>x</b>"))
        pid = self.pid()
        self.tap(f"{pid}:t1")
        self.tap(f"{pid}:d")
        self.assertNotIn("<b>x</b>", self.telegram.sent("editMessageText")[-1]["text"])


class QuestionShape(unittest.TestCase):
    """Finding 3: words inside an option must not count as the dialog's footer."""

    def test_option_text_can_not_make_a_permission_a_question(self):
        screen = screens.BASH.replace("node *", 'echo "enter to select"')
        prompt = parse(screen, QUESTION)
        self.assertEqual(prompt.kind, "permission")
        self.assertEqual([option.label for option in prompt.buttons(False)], ["No"])

    def test_a_description_can_not_either(self):
        screen = "Run it?\n❯ 1. Yes\n     enter to select\n  2. No\n"
        self.assertEqual(parse(screen, QUESTION).kind, "permission")

    def test_an_option_with_footer_words_is_not_skipped_as_a_footer(self):
        screen = "Run it?\n❯ 1. Yes\n  2. No\n  3. Esc to cancel it all\n"
        prompt = parse(screen, PERMISSION)
        self.assertEqual([option.key for option in prompt.options], ["1", "2", "3"])

    def test_real_footers_still_count(self):
        self.assertEqual(parse(screens.QUESTION, QUESTION).kind, "question")
        self.assertEqual(parse(screens.WIZARD_ONE, QUESTION).kind, "question")
        self.assertEqual(parse(screens.PREVIEW, QUESTION).kind, "question")


class Hashing(unittest.TestCase):
    """Finding 4: a command is more than its letters."""

    terminal = {"address": "t1", "created_ms": 1, "turn": 3, "status_ms": 50, "status": PERMISSION}

    def mark(self, screen):
        return fingerprint(parse(screen, PERMISSION), self.terminal)

    def test_a_space_in_a_command_counts(self):
        one = screens.BASH.replace("console.log(2+2)", "rm -rf /tmp/cache")
        two = screens.BASH.replace("console.log(2+2)", "rm -rf /tmp /cache")
        self.assertNotEqual(self.mark(one), self.mark(two))

    def test_a_line_break_in_a_command_counts(self):
        one = screens.BASH.replace("console.log(2+2)", "echo a #b")
        two = screens.BASH.replace("console.log(2+2)", "echo a #\n b")
        self.assertNotEqual(self.mark(one), self.mark(two))

    def test_the_cursor_still_does_not(self):
        moved = screens.BASH.replace("❯ 1. Yes", "  1. Yes").replace("   4. No", " ❯ 4. No")
        self.assertEqual(self.mark(screens.BASH), self.mark(moved))


class Revocation(DaemonCase):
    """Finding 5: the panel is another process, so its changes can land between the check and the press."""

    def during(self, change):
        """Runs `change` straight after the daemon's fresh look at the terminal."""
        real = self.daemon._fresh

        def fresh(record):
            result = real(record)
            change()
            return result

        self.daemon._fresh = fresh

    def test_turning_approvals_off_during_a_tap_stops_it(self):
        self.pair()
        self.set(approvals=True)
        self.world({"t1": term("t1", screens.BASH, kind="permission")})
        self.daemon.scan()
        data = self.button("Yes")
        self.during(lambda: self.set(approvals=False))
        self.tap(data)
        self.assertEqual(self.typed(), [])

    def test_unpairing_during_a_tap_stops_it(self):
        self.blocked()
        data = self.button("Dog")
        self.during(lambda: self.store.update(pageme.unpair))
        self.tap(data)
        self.assertEqual(self.typed(), [])

    def test_pausing_during_a_tap_stops_it(self):
        self.blocked()
        data = self.button("Dog")
        self.during(lambda: self.set(paused=True))
        self.tap(data)
        self.assertEqual(self.typed(), [])

    def test_unpairing_between_the_field_and_the_paste_stops_the_paste(self):
        self.blocked()
        self.change("t1", next={"screen": screens.QUESTION_TYPING})
        real = self.daemon.hc.keys

        def keys(address, pressed):
            real(address, pressed)
            self.store.update(pageme.unpair)

        self.daemon.hc.keys = keys
        self.reply(self.telegram.next_id, "my own answer")
        self.assertEqual(self.journal("send"), [])


class Passwords(unittest.TestCase):
    """Finding 6."""

    def test_underscored_password_names_are_hidden(self):
        for line in ("DB_PASSWORD=hunter2", "MYSQL_PWD=shortsecret", "export PG_PASSPHRASE=hunter2", "smtp_passwd: hunter2", "x.password = 'hunter2'"):
            out = redact.safe(line, 500)
            for word in ("hunter2", "shortsecret"):
                self.assertNotIn(word, out, line)

    def test_ordinary_words_stay(self):
        text = "Compass bearing\nThe bypass road\nPassing the tests"
        self.assertEqual(redact.safe(text, 500), text)


class InvisibleCharacters(unittest.TestCase):
    """Finding 7: a word split by something invisible must be judged as it will look."""

    def test_a_split_word_is_still_hidden(self):
        for label in ("Alwa​ys allow", "auto‍ mode", "Don’t­ ask again"):
            prompt = parse(screens.QUESTION.replace("2. Dog", f"2. {label}"), QUESTION)
            self.assertEqual([option.label for option in prompt.buttons(True)], ["Cat", "Fish"], label)

    def test_wide_letters_are_judged_as_plain_ones(self):
        prompt = parse(screens.QUESTION.replace("2. Dog", "2. Ａｌｗａｙｓ allow"), QUESTION)
        self.assertEqual([option.label for option in prompt.buttons(True)], ["Cat", "Fish"])


class Audit(DaemonCase):
    """Finding 8: a refused answer is an answer someone tried to give."""

    def entries(self):
        return [json.loads(line) for line in self.store.audit_path.read_text(encoding="utf-8").splitlines()]

    def test_text_on_a_permission_prompt(self):
        self.blocked(screen=screens.BASH, kind="permission")
        self.reply(self.telegram.next_id, "1")
        entry = self.entries()[-1]
        self.assertEqual((entry["result"], entry["answer"], entry["user"], entry["terminal"]), ("refused", "1", 1001, "t1"))
        self.assertTrue(entry["why"])

    def test_a_reply_after_the_limit(self):
        self.blocked()
        self.clock[0] += policy.PROMPT_TTL_MS + 1
        self.reply(self.telegram.next_id, "too late words")
        self.assertEqual(self.entries()[-1]["result"], "refused")

    def test_a_refused_tap_names_the_user_and_the_answer(self):
        self.blocked(screen=screens.BASH, kind="permission")
        self.tap(f"{self.pid()}:o1")
        entry = self.entries()[-1]
        self.assertEqual((entry["result"], entry["user"], entry["attempt"]), ("refused", 1001, "o1"))

    def test_a_reply_to_an_agent_that_moved_on(self):
        self.pair()
        self.set(finished=True)
        self.world({"t1": term("t1", "", kind=None, state="working")})
        self.daemon.scan()
        self.change("t1", status={"app": "claude-code", "state": "done"})
        self.daemon.scan()
        self.change("t1", turn=5)
        self.reply(self.telegram.next_id, "words here")
        self.assertEqual(self.entries()[-1]["result"], "refused")


if __name__ == "__main__":
    unittest.main()
