"""One group of tests for each finding of the second security review, written before the fix to prove the finding was real."""
import json
import unittest

from harness import DaemonCase, term

import policy
import screens
from prompts import fingerprint, parse

PERMISSION = {"app": "claude-code", "kind": "permission", "state": "blocked"}
QUESTION = {"app": "claude-code", "kind": "question", "state": "blocked"}
TICK = "✔"


class RemoteOff(DaemonCase):
    """Finding 1: with remote off, a terminal on another machine is never read or pressed, by any path."""

    def touched(self):
        """Every call since the last clear that reached the other machine."""
        return [call for call in self.journal() if any("mac/" in str(part) for part in call)]

    def clear_journal(self):
        world = self.read_world()
        world["journal"] = []
        self.write_world(world)

    def paged(self, **extra):
        self.pair()
        self.remote()
        self.world({"mac/t4": term("mac/t4", screens.QUESTION, **extra)})
        self.daemon.scan()
        self.assertTrue(self.telegram.buttons())

    def finished(self):
        self.pair()
        self.remote()
        self.set(finished=True)
        self.world({"mac/t4": term("mac/t4", "", kind=None, state="working")})
        self.daemon.scan()
        self.change("mac/t4", status={"app": "claude-code", "state": "done"})
        self.daemon.scan()

    def test_an_old_button_reads_and_presses_nothing(self):
        self.paged()
        data = self.button("Dog")
        self.set(remote=False)
        self.clear_journal()
        self.tap(data)
        self.assertEqual(self.touched(), [])
        self.assertIn("other machines", self.answers()[-1].lower())

    def test_a_multi_select_tick_reads_nothing(self):
        self.paged()
        self.world({"mac/t4": term("mac/t4", screens.MULTI, status_ms=9)})
        self.daemon.scan()
        pid = next(p for p, r in self.store.read()["prompts"].items() if r["state"] == "open")
        message = self.store.read()["prompts"][pid]["message_id"]
        self.set(remote=False)
        self.clear_journal()
        self.tap(f"{pid}:t1", message_id=message)
        self.tap(f"{pid}:d", message_id=message)
        self.assertEqual(self.touched(), [])

    def test_a_reply_to_a_question_reads_and_types_nothing(self):
        self.paged()
        self.set(remote=False)
        self.clear_journal()
        self.reply(self.telegram.next_id, "my own answer")
        self.assertEqual(self.touched(), [])

    def test_a_reply_to_a_finished_message_reads_and_sends_nothing(self):
        self.finished()
        self.set(remote=False)
        self.clear_journal()
        self.reply(self.telegram.next_id, "Now reverse it")
        self.assertEqual(self.touched(), [])
        self.assertIn('"result": "refused"', self.store.audit_path.read_text(encoding="utf-8"))

    def test_turning_it_off_during_a_tap_stops_the_press(self):
        self.paged()
        data = self.button("Dog")
        real = self.daemon._fresh

        def fresh(record):
            result = real(record)
            self.set(remote=False)
            return result

        self.daemon._fresh = fresh
        self.tap(data)
        self.assertEqual(self.journal("keys"), [])

    def test_turning_it_off_between_the_field_and_the_paste_stops_the_paste(self):
        self.paged()
        self.change("mac/t4", next={"screen": screens.QUESTION_TYPING})
        real = self.daemon.hc.keys

        def keys(address, pressed):
            real(address, pressed)
            self.set(remote=False)

        self.daemon.hc.keys = keys
        self.reply(self.telegram.next_id, "my own answer")
        self.assertEqual(self.journal("send"), [])

    def test_the_hc_layer_itself_refuses(self):
        from hcli import HcError

        self.paged()
        self.set(remote=False)
        self.clear_journal()
        hc = self.daemon.hc
        for call in (lambda: hc.get("mac/t4"), lambda: hc.read("mac/t4"), lambda: hc.keys("mac/t4", ["1"]), lambda: hc.send("mac/t4", "x")):
            with self.assertRaises(HcError):
                call()
        self.assertEqual(self.touched(), [])

    def test_this_machine_is_unaffected(self):
        self.blocked("t1")
        self.tap(self.button("Dog"))
        self.assertEqual(self.typed(), [["keys", "t1", "2"]])

    def test_with_remote_on_the_other_machine_still_works(self):
        self.paged()
        self.tap(self.button("Dog"))
        self.assertEqual(self.typed(), [["keys", "mac/t4", "2"]])


def long_command(first_line):
    lines = "\n".join(f" line {n}" for n in range(60))
    return screens.BASH.replace(' node -e "console.log(2+2)"\n', f" {first_line}\n{lines}\n")


class WholeQuestion(unittest.TestCase):
    """Finding 2: a change anywhere in the dialog changes the hash, however long the dialog is."""

    terminal = {"address": "t1", "created_ms": 1, "turn": 3, "status_ms": 50, "status": PERMISSION}

    def mark(self, screen):
        return fingerprint(parse(screen, PERMISSION), self.terminal)

    def test_a_step_above_a_solid_rule_in_the_question_is_still_hashed(self):
        ruled = screens.PLAN.replace("   2. Remove the blank rows.", f"  {screens.RULE}\n   2. Remove the blank rows.")
        changed = ruled.replace("1. Sort the sample list.", "1. Delete the sample list.")
        self.assertNotEqual(ruled, changed)
        self.assertNotEqual(self.mark(ruled), self.mark(changed))

    def test_a_change_far_above_the_menu_counts(self):
        self.assertNotEqual(self.mark(long_command("echo safe")), self.mark(long_command("rm -rf ~")))

    def test_a_long_codex_prompt_counts_too(self):
        filler = "\n".join(f"  line {n}" for n in range(60))
        one = screens.CODEX.replace("  $ echo 4 > sum.txt", f"  $ echo safe\n{filler}")
        two = screens.CODEX.replace("  $ echo 4 > sum.txt", f"  $ rm -rf ~\n{filler}")
        codex = {"app": "codex", "state": "blocked"}
        terminal = {**self.terminal, "status": codex}
        self.assertNotEqual(fingerprint(parse(one, codex), terminal), fingerprint(parse(two, codex), terminal))

    def test_the_message_stays_short(self):
        self.assertLessEqual(len(parse(long_command("echo safe"), PERMISSION).body), 40)

    def test_the_menu_is_still_read(self):
        prompt = parse(long_command("echo safe"), PERMISSION)
        self.assertEqual([option.key for option in prompt.buttons(True)], ["1", "4"])


class SwappedLongCommand(DaemonCase):
    def test_an_old_yes_can_not_approve_it(self):
        self.pair()
        self.set(approvals=True)
        self.world({"t1": term("t1", long_command("echo safe"), kind="permission")})
        self.daemon.scan()
        data = self.button("Yes")
        self.change("t1", screen=long_command("rm -rf ~"))
        self.tap(data)
        self.assertEqual(self.typed(), [])


class HiddenTicks(DaemonCase):
    """Finding 3: Done must send what the chat shows, and nothing the chat can't show."""

    def test_a_ticked_hidden_option_refuses_done(self):
        screen = screens.MULTI.replace("[ ] Basil", f"[{TICK}] Always allow")
        self.blocked(screen=screen)
        self.tap(self.button("☐ Cheese"))
        self.tap(f"{self.pid()}:d")
        self.assertEqual(self.typed(), [])
        self.assertIn("keyboard", self.answers()[-1])

    def test_a_ticked_answer_field_refuses_done(self):
        self.blocked(screen=screens.MULTI.replace("[ ] Type something", f"[{TICK}] Type something"))
        self.tap(self.button("☐ Cheese"))
        self.tap(f"{self.pid()}:d")
        self.assertEqual(self.typed(), [])

    def test_a_visible_tick_shows_in_the_chat(self):
        self.blocked(screen=screens.MULTI.replace("[ ] Olives", f"[{TICK}] Olives"))
        self.assertEqual([b["text"] for b in self.telegram.buttons()], ["☐ Cheese", "☑ Olives", "☐ Basil", "Done"])

    def test_keeping_a_tick_presses_nothing_for_it(self):
        self.blocked(screen=screens.MULTI.replace("[ ] Olives", f"[{TICK}] Olives"))
        self.tap(f"{self.pid()}:t1")
        self.tap(f"{self.pid()}:d")
        self.assertEqual(self.typed(), [["keys", "t1", "1", "right"]])

    def test_clearing_a_tick_presses_its_key(self):
        self.blocked(screen=screens.MULTI.replace("[ ] Olives", f"[{TICK}] Olives"))
        self.tap(f"{self.pid()}:t1")
        self.tap(f"{self.pid()}:t2")
        self.tap(f"{self.pid()}:d")
        self.assertEqual(self.typed(), [["keys", "t1", "1", "2", "right"]])

    def test_the_confirmation_names_what_ends_up_ticked(self):
        self.blocked(screen=screens.MULTI.replace("[ ] Olives", f"[{TICK}] Olives"))
        self.tap(f"{self.pid()}:t3")
        self.tap(f"{self.pid()}:d")
        self.assertIn("Answered: Olives, Basil", self.telegram.sent("editMessageText")[-1]["text"])


class WrappedLabels(unittest.TestCase):
    """Finding 4: a label is all its lines."""

    def labels(self, prompt, approvals=True):
        return [option.label for option in prompt.buttons(approvals)]

    def test_a_question_label_split_across_lines(self):
        screen = screens.QUESTION.replace("2. Dog\n     Barks at the postman.", "2. Yes, and don't\n     ask again")
        self.assertEqual(self.labels(parse(screen, QUESTION)), ["Cat", "Fish"])

    def test_a_curly_quote_on_the_second_line(self):
        screen = screens.QUESTION.replace("2. Dog\n     Barks at the postman.", "2. Yes, and\n     don’t ask again")
        self.assertEqual(self.labels(parse(screen, QUESTION)), ["Cat", "Fish"])

    def test_auto_mode_split_across_lines(self):
        screen = screens.QUESTION.replace("2. Dog\n     Barks at the postman.", "2. Switch to auto\n     mode")
        self.assertEqual(self.labels(parse(screen, QUESTION)), ["Cat", "Fish"])

    def test_the_review_example_on_a_permission_prompt(self):
        screen = screens.BASH.replace("   3. Yes, and switch to auto mode · auto mode handles these prompts for you\n", "   3. Yes, and don't\n      ask again\n")
        self.assertEqual(self.labels(parse(screen, PERMISSION)), ["Yes", "No"])

    def test_an_exact_yes_with_more_below_it_is_not_exact(self):
        screen = screens.BASH.replace(" ❯ 1. Yes\n", " ❯ 1. Yes\n      and don't ask again\n")
        self.assertEqual(self.labels(parse(screen, PERMISSION)), ["No"])

    def test_a_codex_yes_with_more_below_it_is_not_exact(self):
        screen = screens.CODEX.replace("› 1. Yes, proceed (y)\n", "› 1. Yes, proceed (y)\n     for this whole session\n")
        self.assertEqual(self.labels(parse(screen, {"app": "codex", "state": "blocked"})), ["No, and tell Codex what to do differently"])

    def test_multi_select_labels_too(self):
        screen = screens.MULTI.replace("[ ] Olives\n         Salty.", "[ ] Don't\n         ask again")
        self.assertEqual(self.labels(parse(screen, QUESTION)), ["Cheese", "Basil"])

    def test_ordinary_descriptions_keep_their_buttons(self):
        self.assertEqual(self.labels(parse(screens.QUESTION, QUESTION)), ["Cat", "Dog", "Fish"])


class CommandPrefixes(DaemonCase):
    """Finding 5: no reply starts with ! or /, on any path."""

    TEXTS = ["/permissions", "!rm notes.txt", "  /permissions", "\n!rm notes.txt", "​/permissions", "﻿!rm", "͏!rm", "ㅤ/model", " !rm", "！rm", "／model"]

    def test_a_question_field_refuses_them(self):
        self.blocked()
        self.change("t1", next={"screen": screens.QUESTION_TYPING})
        message = self.telegram.next_id  # Each refusal is a new message, which moves next_id.
        for text in self.TEXTS:
            self.reply(message, text)
        self.assertEqual(self.typed(), [])
        self.assertEqual(self.store.audit_path.read_text(encoding="utf-8").count('"result": "refused"'), len(self.TEXTS))

    def test_an_unread_question_refuses_them(self):
        self.blocked(screen=screens.UNKNOWN, kind="question", app="other")
        message = self.telegram.next_id
        for text in self.TEXTS:
            self.reply(message, text + " and some more words")
        self.assertEqual(self.typed(), [])
        self.assertEqual(self.store.audit_path.read_text(encoding="utf-8").count('"result": "refused"'), len(self.TEXTS))

    def test_a_finished_message_refuses_them(self):
        self.pair()
        self.set(finished=True)
        self.world({"t1": term("t1", "", kind=None, state="working")})
        self.daemon.scan()
        self.change("t1", status={"app": "claude-code", "state": "done"})
        self.daemon.scan()
        message = self.telegram.next_id
        for text in self.TEXTS:
            self.reply(message, text)
        self.assertEqual(self.typed(), [])
        self.assertEqual(self.store.audit_path.read_text(encoding="utf-8").count('"result": "refused"'), len(self.TEXTS))

    def test_the_refusal_is_audited(self):
        self.blocked()
        self.reply(self.telegram.next_id, "/permissions")
        self.assertIn('"result": "refused"', self.store.audit_path.read_text(encoding="utf-8"))

    def test_the_marks_are_fine_later_in_a_sentence(self):
        self.assertIsNone(policy.reply_refusal("Use src/lib, it works!"))


class RawAgentName(DaemonCase):
    """Finding 6: an agent's own report of its name is untrusted text."""

    SECRET = "sk-" + "abcdefghij" * 3

    def test_an_unknown_name_never_reaches_the_state_file(self):
        self.pair()
        self.world({"t1": term("t1", screens.QUESTION, app=self.SECRET)})
        self.daemon.scan()
        self.assertTrue(self.store.read()["prompts"])
        self.assertNotIn(self.SECRET, self.store.path.read_text(encoding="utf-8"))
        self.assertNotIn(self.SECRET, json.dumps([call["body"] for call in self.telegram.calls]))

    def test_known_names_are_kept(self):
        self.blocked(app="codex")
        record = next(iter(self.store.read()["prompts"].values()))
        self.assertEqual(record["agent"], "codex")

    def test_anything_else_is_just_an_agent(self):
        self.assertEqual(parse(screens.QUESTION, {"app": "something-else", "kind": "question"}).agent, "agent")


if __name__ == "__main__":
    unittest.main()
