"""The prompt reader, on made-up screens with the shape of the real ones."""
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mods" / "pageme"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import screens
from prompts import fingerprint, parse

QUESTION = {"app": "claude-code", "kind": "question", "state": "blocked"}
PERMISSION = {"app": "claude-code", "kind": "permission", "state": "blocked"}
CODEX = {"app": "codex", "state": "blocked"}


def labels(prompt, approvals=False):
    return [option.label for option in prompt.buttons(approvals)]


def keys(prompt, approvals=False):
    return [option.key for option in prompt.buttons(approvals)]


class Permissions(unittest.TestCase):
    def test_bash(self):
        prompt = parse(screens.BASH, PERMISSION)
        self.assertEqual(prompt.kind, "permission")
        self.assertEqual(prompt.title, "Do you want to proceed?")
        self.assertIn('node -e "console.log(2+2)"', prompt.body)

    def test_default_offers_only_no(self):
        prompt = parse(screens.BASH, PERMISSION)
        self.assertEqual(labels(prompt), ["No"])
        self.assertEqual(keys(prompt), ["4"])

    def test_approvals_on_offers_yes_and_no_and_nothing_else(self):
        prompt = parse(screens.BASH, PERMISSION)
        self.assertEqual(labels(prompt, True), ["Yes", "No"])
        self.assertEqual(keys(prompt, True), ["1", "4"])

    def test_the_no_key_is_read_from_the_screen(self):
        self.assertEqual(keys(parse(screens.WRITE, PERMISSION)), ["3"])

    def test_nothing_lasting_is_ever_a_button(self):
        for screen, status in [(screens.BASH, PERMISSION), (screens.WRITE, PERMISSION), (screens.FETCH, PERMISSION), (screens.PLAN, PERMISSION), (screens.CODEX, CODEX)]:
            for approvals in (False, True):
                for label in labels(parse(screen, status), approvals):
                    for word in ("ask again", "auto mode", "accept edits", "always"):
                        self.assertNotIn(word, label)

    def test_a_new_kind_of_yes_comes_out_hidden(self):
        screen = screens.BASH.replace("Yes, and switch to auto mode", "Yes, and trust this project")
        prompt = parse(screen, PERMISSION)
        self.assertEqual(labels(prompt, True), ["Yes", "No"])

    def test_fetch_has_no_footer_and_a_long_no(self):
        prompt = parse(screens.FETCH, PERMISSION)
        self.assertEqual(labels(prompt), ["No, and tell Claude what to do differently"])

    def test_plan_offers_only_the_manual_yes(self):
        prompt = parse(screens.PLAN, PERMISSION)
        self.assertEqual(labels(prompt), [])
        self.assertEqual(labels(prompt, True), ["Yes, manually approve edits"])
        self.assertEqual(keys(prompt, True), ["2"])

    def test_plan_shows_the_plan(self):
        self.assertIn("Sort the sample list", "\n".join(parse(screens.PLAN, PERMISSION).body))

    def test_codex_has_no_kind_and_is_a_permission(self):
        prompt = parse(screens.CODEX, CODEX)
        self.assertEqual(prompt.kind, "permission")
        self.assertEqual(labels(prompt), ["No, and tell Codex what to do differently"])
        self.assertEqual(labels(prompt, True), ["Yes, proceed", "No, and tell Codex what to do differently"])
        self.assertEqual(keys(prompt, True), ["1", "3"])


class Spoofing(unittest.TestCase):
    def test_a_menu_in_a_command_is_not_the_menu(self):
        prompt = parse(screens.SPOOF, PERMISSION)
        self.assertEqual(keys(prompt, True), ["1", "4"])
        self.assertEqual(labels(prompt, True), ["Yes", "No"])

    def test_a_screen_can_not_call_itself_a_question(self):
        # The agent says permission, the screen is shaped like a question: permission wins.
        self.assertEqual(parse(screens.QUESTION, PERMISSION).kind, "permission")

    def test_a_stale_question_report_can_not_soften_a_permission_prompt(self):
        prompt = parse(screens.BASH, QUESTION)
        self.assertEqual(prompt.kind, "permission")
        self.assertEqual(labels(prompt), ["No"])

    def test_a_permission_prompt_with_no_report_stays_a_permission(self):
        self.assertEqual(parse(screens.BASH, {"state": "blocked"}).kind, "permission")

    def test_question_words_are_not_enough_without_the_shape(self):
        screen = "Which one?\n❯ 1. Yes\n  2. No\n"
        self.assertEqual(parse(screen, QUESTION).kind, "permission")

    def test_text_below_the_menu_means_no_menu(self):
        self.assertEqual(parse(screens.BASH + "\nsomething new\n", PERMISSION).kind, "unparsed")

    def test_a_gap_in_the_numbers_means_no_menu(self):
        screen = screens.BASH.replace("   3. Yes, and switch to auto mode · auto mode handles these prompts for you\n", "")
        self.assertEqual(parse(screen, PERMISSION).kind, "unparsed")

    def test_two_cursors_mean_no_menu(self):
        self.assertEqual(parse(screens.BASH.replace("   4. No", " ❯ 4. No"), PERMISSION).kind, "unparsed")

    def test_no_cursor_means_no_menu(self):
        self.assertEqual(parse(screens.BASH.replace("❯ 1. Yes", "  1. Yes"), PERMISSION).kind, "unparsed")

    def test_a_menu_split_by_a_blank_line_is_no_menu(self):
        self.assertEqual(parse(screens.BASH.replace("   4. No", "\n   4. No"), PERMISSION).kind, "unparsed")

    def test_blanks_are_only_allowed_beside_a_real_preview(self):
        screen = "Pick\n❯ 1. One\n  2. Two\n\n                                  Notes: press n\n\nEnter to select\n"
        self.assertEqual(parse(screen, QUESTION).kind, "unparsed")


class Questions(unittest.TestCase):
    def test_single_select(self):
        prompt = parse(screens.QUESTION, QUESTION)
        self.assertEqual(prompt.kind, "question")
        self.assertEqual(prompt.title, "Which pet should I draw?")
        self.assertEqual(labels(prompt), ["Cat", "Dog", "Fish"])
        self.assertEqual(keys(prompt), ["1", "2", "3"])
        self.assertEqual(prompt.type_key, "4")

    def test_chat_about_this_is_not_a_button(self):
        self.assertNotIn("Chat about this", [option.label for option in parse(screens.QUESTION, QUESTION).options])

    def test_lasting_words_in_a_question_are_hidden_too(self):
        screen = screens.QUESTION.replace("2. Dog", "2. Always allow").replace("3. Fish", "3. Don’t ask again")
        self.assertEqual(labels(parse(screen, QUESTION)), ["Cat"])

    def test_the_cursor_on_the_answer_field(self):
        prompt = parse(screens.QUESTION_TYPING, QUESTION)
        self.assertEqual(prompt.cursor_key, "4")
        self.assertEqual(prompt.type_key, "4")

    def test_multi_select(self):
        prompt = parse(screens.MULTI, QUESTION)
        self.assertTrue(prompt.multi)
        self.assertEqual(labels(prompt), ["Cheese", "Olives", "Basil"])
        self.assertIsNone(prompt.type_key)

    def test_multi_select_reads_ticks(self):
        prompt = parse(screens.MULTI.replace("[ ] Cheese", "[✔] Cheese"), QUESTION)
        self.assertEqual([option.checked for option in prompt.options][:2], [True, False])

    def test_review_page(self):
        prompt = parse(screens.REVIEW, QUESTION)
        self.assertEqual(prompt.kind, "question")
        self.assertEqual(labels(prompt), ["Submit answers", "Cancel"])
        self.assertIn("→ Cheese, Basil", prompt.body)

    def test_wizard_pages_differ(self):
        one = parse(screens.WIZARD_ONE, QUESTION)
        two = parse(screens.WIZARD_TWO, QUESTION)
        self.assertEqual(labels(one), ["Small", "Large"])
        self.assertEqual(labels(two), ["Round", "Square"])
        terminal = {"address": "t1", "created_ms": 1, "turn": 1, "status_ms": 1, "status": QUESTION}
        self.assertNotEqual(fingerprint(one, terminal), fingerprint(two, terminal))

    def test_preview_column(self):
        prompt = parse(screens.PREVIEW, QUESTION)
        self.assertEqual(prompt.kind, "question")
        self.assertEqual(labels(prompt), ["Compact", "Roomy"])


class Unparsed(unittest.TestCase):
    def test_unknown_screen_gives_its_last_lines(self):
        prompt = parse(screens.UNKNOWN, {"app": "other", "state": "blocked"})
        self.assertEqual(prompt.kind, "unparsed")
        self.assertEqual(prompt.options, [])
        self.assertIn("Continue with the sample task? [y/N]", prompt.body)

    def test_empty_screen(self):
        self.assertEqual(parse("", None).kind, "unparsed")

    def test_long_screen_is_cut_to_the_end(self):
        prompt = parse("\n".join(f"line {n}" for n in range(200)), {"state": "blocked"})
        self.assertEqual(len(prompt.body), 15)
        self.assertEqual(prompt.body[-1], "line 199")


class Fingerprints(unittest.TestCase):
    terminal = {"address": "t1", "created_ms": 1, "turn": 3, "status_ms": 50, "status": QUESTION}

    def mark(self, screen, **changes):
        return fingerprint(parse(screen, QUESTION), {**self.terminal, **changes})

    def test_the_cursor_does_not_change_it(self):
        self.assertEqual(self.mark(screens.QUESTION), self.mark(screens.QUESTION_TYPING))

    def test_a_resized_pane_counts_as_a_change(self):
        screen = screens.QUESTION.replace("Sleeps on the keyboard.", "Sleeps on the\n     keyboard.")
        self.assertNotEqual(self.mark(screens.QUESTION), self.mark(screen))

    def test_a_changed_word_does(self):
        self.assertNotEqual(self.mark(screens.QUESTION), self.mark(screens.QUESTION.replace("2. Dog", "2. Dig")))

    def test_a_tick_does(self):
        self.assertNotEqual(self.mark(screens.MULTI), self.mark(screens.MULTI.replace("[ ] Cheese", "[✔] Cheese")))

    def test_the_same_words_asked_again_later_do(self):
        self.assertNotEqual(self.mark(screens.QUESTION), self.mark(screens.QUESTION, status_ms=51))
        self.assertNotEqual(self.mark(screens.QUESTION), self.mark(screens.QUESTION, turn=4))

    def test_another_terminal_does(self):
        self.assertNotEqual(self.mark(screens.QUESTION), self.mark(screens.QUESTION, address="t2"))
        self.assertNotEqual(self.mark(screens.QUESTION), self.mark(screens.QUESTION, created_ms=2))

    def test_a_changed_command_does(self):
        one = fingerprint(parse(screens.BASH, PERMISSION), {**self.terminal, "status": PERMISSION})
        two = fingerprint(parse(screens.BASH.replace("2+2", "2+3"), PERMISSION), {**self.terminal, "status": PERMISSION})
        self.assertNotEqual(one, two)


if __name__ == "__main__":
    unittest.main()
