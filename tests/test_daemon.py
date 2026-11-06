"""The daemon end to end, against the fake hc and the local fake Telegram server. Most of these are the security rules."""
import json
import unittest

import harness
from harness import NOW, OWNER, OWNER_CHAT, STRANGER, STRANGER_CHAT, TOKEN, DaemonCase, term

import policy
import screens
import pageme


class Pairing(DaemonCase):
    def code(self):
        code = pageme.make_code(self.store)["code"]
        self.store.update(lambda state: state["code"].update({"created_ms": self.clock[0], "expires_ms": self.clock[0] + 300_000}))
        return code

    def test_a_code_binds_one_user_and_chat(self):
        self.say(self.code())
        pair = self.store.read()["pair"]
        self.assertEqual((pair["user_id"], pair["chat_id"]), (1001, 1001))
        self.assertIn("Paired", self.telegram.last_text())

    def test_the_code_is_eight_unambiguous_characters(self):
        code = self.code()
        self.assertRegex(code, r"^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{8}$")

    def test_lower_case_and_spaces_still_pair(self):
        self.say("  " + self.code().lower() + " ")
        self.assertTrue(self.store.read()["pair"])

    def test_a_wrong_code_gets_no_reply(self):
        self.code()
        self.say("ZZZZZZZZ", STRANGER, STRANGER_CHAT)
        self.assertFalse(self.store.read()["pair"])
        self.assertEqual(self.telegram.sent(), [])

    def test_any_other_message_gets_no_reply(self):
        self.code()
        self.say("/start", STRANGER, STRANGER_CHAT)
        self.say("hello", STRANGER, STRANGER_CHAT)
        self.assertEqual(self.telegram.sent(), [])

    def test_a_code_works_only_once(self):
        code = self.code()
        self.say(code)
        self.say(code, STRANGER, STRANGER_CHAT)
        self.assertEqual(self.store.read()["pair"]["user_id"], 1001)

    def test_a_code_expires(self):
        code = self.code()
        self.clock[0] += 300_001
        self.say(code)
        self.assertFalse(self.store.read()["pair"])
        self.assertEqual(self.telegram.sent(), [])

    def test_a_group_can_not_pair(self):
        self.say(self.code(), OWNER, {"id": -5, "type": "group"})
        self.assertFalse(self.store.read()["pair"])

    def test_a_forwarded_code_can_not_pair(self):
        self.say(self.code(), forward_origin={"type": "user"})
        self.assertFalse(self.store.read()["pair"])

    def test_a_bot_can_not_pair(self):
        self.say(self.code(), {"id": 7, "is_bot": True}, {"id": 7, "type": "private"})
        self.assertFalse(self.store.read()["pair"])

    def test_a_message_older_than_the_code_can_not_pair(self):
        self.say(self.code(), date=NOW - 60_000)
        self.assertFalse(self.store.read()["pair"])

    def test_five_wrong_guesses_burn_the_code(self):
        code = self.code()
        for _ in range(5):
            self.say("ZZZZZZZZ", STRANGER, STRANGER_CHAT)
        self.say(code)
        self.assertFalse(self.store.read()["pair"])

    def test_a_second_pairing_is_refused_while_paired(self):
        self.pair()
        self.assertIn("error", pageme.make_code(self.store))

    def test_pairing_survives_a_restart(self):
        self.pair()
        self.daemon = self.make_daemon()
        self.world({"t1": term("t1", screens.QUESTION)})
        self.daemon.scan()
        self.assertEqual(self.telegram.sent()[-1]["chat_id"], 1001)

    def test_unpairing_is_one_action_and_kills_old_buttons(self):
        self.blocked()
        data = self.button("Cat")
        self.store.update(pageme.unpair)
        self.tap(data)
        self.assertEqual(self.typed(), [])
        self.assertEqual(self.answers(), [])

    def test_unpairing_is_said_in_the_old_chat(self):
        self.blocked()
        self.store.update(pageme.unpair)
        self.daemon.scan()
        self.assertEqual(self.telegram.last_text(), "Unpaired.")


class Strangers(DaemonCase):
    def test_a_strangers_tap_does_nothing_and_gets_no_answer(self):
        self.blocked()
        self.tap(self.button("Cat"), sender=STRANGER, chat=STRANGER_CHAT)
        self.assertEqual(self.typed(), [])
        self.assertEqual(self.answers(), [])

    def test_the_right_user_in_the_wrong_chat_is_a_stranger(self):
        self.blocked()
        self.tap(self.button("Cat"), chat={"id": -5, "type": "group"})
        self.assertEqual(self.typed(), [])

    def test_a_strangers_message_gets_no_reply(self):
        self.pair()
        self.say("/agents", STRANGER, STRANGER_CHAT)
        self.assertEqual(self.telegram.sent(), [])

    def test_a_strangers_reply_does_nothing(self):
        self.blocked()
        self.reply(self.telegram.next_id, "my answer", STRANGER, STRANGER_CHAT)
        self.assertEqual(self.typed(), [])


class Questions(DaemonCase):
    def test_one_message_with_where_it_is_the_question_and_a_button_each(self):
        self.remote()
        self.blocked("mac/t4")
        self.assertEqual(len(self.telegram.sent()), 1)
        text = self.telegram.last_text()
        self.assertIn("mac/t4 · sample-app", text)
        self.assertIn("Which pet should I draw?", text)
        self.assertEqual([b["text"] for b in self.telegram.buttons()], ["Cat", "Dog", "Fish"])

    def test_the_panel_gets_the_same_words_and_buttons_the_phone_got(self):
        self.remote()
        self.blocked("mac/t4")
        page = pageme.latest_page(self.daemon.store.read())
        self.assertEqual(page["options"], [b["text"] for b in self.telegram.buttons()])
        self.assertIn(page["text"], self.telegram.last_text())
        self.assertEqual(page["where"], "mac/t4 · sample-app")
        self.assertEqual(page["state"], "open")

    def test_a_scan_does_not_send_it_twice(self):
        self.blocked()
        self.daemon.scan()
        self.assertEqual(len(self.telegram.sent()), 1)

    def test_a_tap_presses_only_that_options_key(self):
        self.blocked()
        self.tap(self.button("Dog"))
        self.assertEqual(self.typed(), [["keys", "t1", "2"]])
        self.assertEqual(self.answers(), ["Sent."])

    def test_another_machine_is_left_out_until_turned_on(self):
        self.blocked("mac/t4")
        self.assertEqual(self.telegram.sent(), [])

    def test_it_works_on_another_machine(self):
        self.remote()
        self.blocked("mac/t4")
        self.tap(self.button("Dog"))
        self.assertEqual(self.typed(), [["keys", "mac/t4", "2"]])

    def test_the_message_loses_its_buttons_and_says_what_was_picked(self):
        self.blocked()
        self.tap(self.button("Dog"))
        edit = self.telegram.sent("editMessageText")[-1]
        self.assertIn("Answered: Dog", edit["text"])
        self.assertEqual(edit["reply_markup"]["inline_keyboard"], [])

    def test_each_answer_is_written_to_the_audit_log(self):
        self.blocked()
        self.tap(self.button("Dog"))
        lines = self.store.audit_path.read_text(encoding="utf-8").strip().split("\n")
        entry = json.loads(lines[-1])
        self.assertEqual((entry["terminal"], entry["answer"], entry["keys"], entry["result"], entry["user"]), ("t1", "Dog", ["2"], "sent", 1001))

    def test_a_button_works_once(self):
        self.blocked()
        data = self.button("Dog")
        self.tap(data)
        self.tap(data)
        self.assertEqual(len(self.typed()), 1)
        self.assertEqual(self.answers()[-1], "That was already answered.")

    def test_a_second_button_on_the_same_question_is_also_spent(self):
        self.blocked()
        one, two = self.button("Dog"), self.button("Cat")
        self.tap(one)
        self.tap(two)
        self.assertEqual(len(self.typed()), 1)

    def test_a_tap_after_the_limit_is_refused(self):
        self.blocked()
        self.clock[0] += policy.PROMPT_TTL_MS + 1
        self.tap(self.button("Dog"))
        self.assertEqual(self.typed(), [])
        self.assertIn("expired", self.answers()[-1])

    def test_a_tap_after_the_agent_moved_on_is_refused(self):
        self.blocked()
        data = self.button("Dog")
        self.change("t1", status={"app": "claude-code", "state": "working"})
        self.tap(data)
        self.assertEqual(self.typed(), [])
        self.assertEqual(self.answers()[-1], "That question has gone.")

    def test_a_tap_on_a_changed_screen_is_refused(self):
        self.blocked()
        data = self.button("Dog")
        self.change("t1", screen=screens.QUESTION.replace("2. Dog", "2. Delete everything"))
        self.tap(data)
        self.assertEqual(self.typed(), [])
        self.assertIn("changed", self.answers()[-1])

    def test_an_old_button_can_not_answer_the_same_words_asked_again(self):
        self.blocked()
        data = self.button("Dog")
        self.change("t1", status_ms=999)
        self.tap(data)
        self.assertEqual(self.typed(), [])

    def test_a_new_terminal_at_the_same_address_is_refused(self):
        self.blocked()
        data = self.button("Dog")
        self.change("t1", created_ms=555)
        self.tap(data)
        self.assertEqual(self.typed(), [])

    def test_a_terminal_that_ended_is_refused(self):
        self.blocked()
        data = self.button("Dog")
        self.world({})
        self.tap(data)
        self.assertEqual(self.typed(), [])

    def test_a_made_up_button_is_refused(self):
        self.blocked()
        self.tap("AAAAAAAAAAAA:o1")
        self.tap("not a button")
        self.assertEqual(self.typed(), [])

    def test_a_real_button_from_another_message_is_refused(self):
        self.blocked()
        self.tap(self.button("Dog"), message_id=1)
        self.assertEqual(self.typed(), [])

    def test_a_button_can_not_ask_for_an_option_that_is_not_there(self):
        self.blocked()
        pid = self.pid()
        self.tap(f"{pid}:o9")
        self.assertEqual(self.typed(), [])

    def test_a_forged_tap_on_type_something_is_refused(self):
        self.blocked()
        self.tap(f"{self.pid()}:o4")
        self.assertEqual(self.typed(), [])

    def test_a_key_that_fails_lets_the_question_come_again(self):
        self.blocked()
        data = self.button("Dog")
        world = self.read_world()
        address = world["terminals"].pop("t1")
        world["terminals"]["t1"] = address
        self.write_world(world)
        import hcli

        original = hcli.Hc.keys

        def broken(_self, _address, _keys):
            raise hcli.HcError("no")

        hcli.Hc.keys = broken
        try:
            self.tap(data)
        finally:
            hcli.Hc.keys = original
        self.assertEqual(self.answers()[-1], "That didn't go through.")
        self.daemon.scan()
        self.assertEqual(len(self.telegram.sent()), 2)

    def test_answering_at_the_keyboard_takes_the_buttons_away(self):
        self.blocked()
        self.change("t1", status={"app": "claude-code", "state": "working"})
        self.daemon.scan()
        edit = self.telegram.sent("editMessageText")[-1]
        self.assertIn("Answered somewhere else", edit["text"])
        self.assertEqual(edit["reply_markup"]["inline_keyboard"], [])

    def test_an_expired_question_says_so_and_agents_brings_it_back(self):
        self.blocked()
        self.clock[0] += policy.PROMPT_TTL_MS + 1
        self.daemon.scan()
        self.assertIn("Expired", self.telegram.sent("editMessageText")[-1]["text"])
        self.assertEqual(len(self.telegram.sent()), 1)
        self.say("/agents")
        self.daemon.scan()
        self.assertEqual([b["text"] for b in self.telegram.buttons()], ["Cat", "Dog", "Fish"])


class Wizards(DaemonCase):
    def test_a_page_turn_with_no_event_is_a_new_message(self):
        self.blocked(screen=screens.WIZARD_ONE)
        self.change("t1", next={"screen": screens.WIZARD_TWO})
        self.tap(self.button("Large"))
        self.daemon.scan()
        self.assertEqual([b["text"] for b in self.telegram.buttons()], ["Round", "Square"])
        self.tap(self.button("Round"))
        self.assertEqual(self.typed(), [["keys", "t1", "2"], ["keys", "t1", "1"]])

    def test_multi_select_ticks_press_nothing_and_done_presses_once(self):
        self.blocked(screen=screens.MULTI)
        self.tap(self.button("☐ Cheese"))
        self.tap(f"{self.pid()}:t3")
        self.assertEqual(self.typed(), [])
        marks = [b["text"] for b in self.telegram.buttons(self.telegram.sent("editMessageText")[-1])]
        self.assertEqual(marks, ["☑ Cheese", "☐ Olives", "☑ Basil", "Done"])
        self.tap(f"{self.pid()}:d")
        self.assertEqual(self.typed(), [["keys", "t1", "1", "3", "right"]])

    def test_multi_select_needs_a_pick(self):
        self.blocked(screen=screens.MULTI)
        self.tap(f"{self.pid()}:d")
        self.assertEqual(self.typed(), [])

    def test_done_refuses_a_screen_ticked_at_the_keyboard(self):
        self.blocked(screen=screens.MULTI)
        self.tap(f"{self.pid()}:t1")
        self.change("t1", screen=screens.MULTI.replace("[ ] Basil", "[✔] Basil"))
        self.tap(f"{self.pid()}:d")
        self.assertEqual(self.typed(), [])


class Permissions(DaemonCase):
    def block(self, screen=screens.BASH, **extra):
        self.blocked(screen=screen, kind=extra.pop("kind", "permission"), **extra)

    def test_default_shows_no_and_says_approving_is_off(self):
        self.block()
        self.assertEqual([b["text"] for b in self.telegram.buttons()], ["No"])
        self.assertIn("Approving from Telegram is off", self.telegram.last_text())

    def test_no_presses_the_no_key(self):
        self.block()
        self.tap(self.button("No"))
        self.assertEqual(self.typed(), [["keys", "t1", "4"]])

    def test_a_forged_yes_is_refused_when_approvals_are_off(self):
        self.block()
        self.tap(f"{self.pid()}:o1")
        self.assertEqual(self.typed(), [])

    def test_approvals_on_offers_yes(self):
        self.pair()
        self.set(approvals=True)
        self.world({"t1": term("t1", screens.BASH, kind="permission")})
        self.daemon.scan()
        self.assertEqual([b["text"] for b in self.telegram.buttons()], ["Yes", "No"])
        self.tap(self.button("Yes"))
        self.assertEqual(self.typed(), [["keys", "t1", "1"]])

    def test_turning_approvals_on_is_said_in_the_chat(self):
        self.pair()
        self.daemon.scan()
        self.set(approvals=True)
        self.daemon.scan()
        self.assertIn("is on", self.telegram.last_text())

    def test_a_daemon_starting_with_approvals_on_says_so(self):
        self.pair()
        self.set(approvals=True)
        self.daemon = self.make_daemon()
        self.daemon.scan()
        self.assertIn("is on", self.telegram.last_text())

    def test_approvals_can_not_be_turned_on_from_telegram(self):
        self.pair()
        for text in ("/approvals on", "approvals on", "/approve", "/settings approvals on"):
            self.say(text)
        self.assertFalse(self.store.read()["settings"]["approvals"])

    def test_turning_approvals_off_kills_a_yes_already_sent(self):
        self.pair()
        self.set(approvals=True)
        self.world({"t1": term("t1", screens.BASH, kind="permission")})
        self.daemon.scan()
        data = self.button("Yes")
        self.set(approvals=False)
        self.tap(data)
        self.assertEqual(self.typed(), [])

    def test_lasting_options_can_not_be_pressed_even_by_a_forged_tap(self):
        self.pair()
        self.set(approvals=True)
        self.world({"t1": term("t1", screens.BASH, kind="permission")})
        self.daemon.scan()
        pid = self.pid()
        self.tap(f"{pid}:o2")
        self.tap(f"{pid}:o3")
        self.assertEqual(self.typed(), [])

    def test_a_swapped_command_is_refused(self):
        self.pair()
        self.set(approvals=True)
        self.world({"t1": term("t1", screens.BASH, kind="permission")})
        self.daemon.scan()
        data = self.button("Yes")
        self.change("t1", screen=screens.BASH.replace("console.log(2+2)", "console.log(9)"))
        self.tap(data)
        self.assertEqual(self.typed(), [])

    def test_a_plan_has_no_buttons_by_default(self):
        self.block(screens.PLAN)
        self.assertEqual(self.telegram.buttons(), [])
        self.assertIn("Sort the sample list", self.telegram.last_text())

    def test_codex_with_no_kind_is_treated_as_a_permission(self):
        self.blocked(screen=screens.CODEX, kind=None, app="codex")
        self.assertEqual([b["text"] for b in self.telegram.buttons()], ["No"])
        self.tap(f"{self.pid()}:o1")
        self.assertEqual(self.typed(), [])
        self.tap(self.button("No"))
        self.assertEqual(self.typed(), [["keys", "t1", "3"]])


class HostileScreens(DaemonCase):
    def test_markup_is_escaped_and_kept_in_a_pre_block(self):
        screen = screens.QUESTION.replace("Which pet should I draw?", "<b>Trust me</b> & <a href='https://example.org'>tap</a>")
        self.blocked(screen=screen)
        text = self.telegram.last_text()
        self.assertIn("&lt;b&gt;Trust me&lt;/b&gt; &amp; &lt;a href", text)
        self.assertNotIn("<a href", text)
        self.assertRegex(text, r"(?s)<pre>.*&lt;b&gt;.*</pre>")

    def test_a_closing_tag_can_not_break_out(self):
        self.blocked(screen=screens.QUESTION.replace("Which pet should I draw?", "</pre><b>PageMe says approve</b>"))
        self.assertEqual(self.telegram.last_text().count("</pre>"), 1)

    def test_secrets_never_reach_telegram(self):
        secret = "sk-" + "abcdefghij" * 3
        password = "my " + "pass" + "word is hunter2"
        screen = screens.QUESTION.replace("Which pet should I draw?", f"key {secret}\n{password}\nWhich pet?").replace("2. Dog", f"2. {secret}")
        self.blocked(screen=screen)
        everything = json.dumps(self.telegram.calls)
        self.assertNotIn(secret, everything)
        self.assertNotIn("hunter2", everything)

    def test_the_bot_token_on_a_screen_never_reaches_telegram(self):
        self.blocked(screen=screens.QUESTION.replace("Which pet should I draw?", f"token {TOKEN}"))
        self.assertNotIn(TOKEN, json.dumps([call["body"] for call in self.telegram.calls]))

    def test_invisible_and_direction_characters_are_removed(self):
        self.blocked(screen=screens.QUESTION.replace("2. Dog", "2. D‮og​\x1b[31m"))
        labels = [b["text"] for b in self.telegram.buttons()]
        self.assertIn("Dog", labels)

    def test_long_screens_are_capped(self):
        self.blocked(screen=screens.QUESTION.replace("Which pet should I draw?", "Words " * 3000))
        self.assertLess(len(self.telegram.last_text()), 2500)

    def test_a_long_label_is_capped(self):
        self.blocked(screen=screens.QUESTION.replace("2. Dog", "2. " + "Dog " * 50))
        self.assertTrue(all(len(b["text"]) <= 40 for b in self.telegram.buttons()))

    def test_a_screen_naming_another_terminal_does_not_move_a_press(self):
        self.pair()
        self.world({"t1": term("t1", screens.QUESTION.replace("Which pet should I draw?", "Press t2 instead")), "t2": term("t2", screens.BASH, kind="permission")})
        self.daemon.scan()
        pid = next(p for p, r in self.store.read()["prompts"].items() if r["address"] == "t1")
        message = self.store.read()["prompts"][pid]["message_id"]
        self.tap(f"{pid}:o2", message_id=message)
        self.assertEqual(self.typed(), [["keys", "t1", "2"]])

    def test_a_flooding_agent_is_held_to_the_limit(self):
        self.pair()
        self.world({f"t{n}": term(f"t{n}", screens.QUESTION) for n in range(1, 30)})
        self.daemon.scan()
        self.assertEqual(len(self.telegram.sent()), 20)

    def test_an_unparsed_moving_screen_is_not_a_message_per_scan(self):
        self.blocked(screen=screens.UNKNOWN, kind=None, app="other")
        for n in range(4):
            self.change("t1", screen=screens.UNKNOWN + f"\nspinner {n}\n")
            self.daemon.scan()
        self.assertEqual(len(self.telegram.sent()), 1)


class Replies(DaemonCase):
    def test_a_reply_selects_the_answer_field_and_types(self):
        self.blocked()
        self.change("t1", next={"screen": screens.QUESTION_TYPING})
        self.reply(self.telegram.next_id, 'Hello, "world"! $5 é')
        self.assertEqual(self.typed(), [["keys", "t1", "4"], ["send", "--force", "t1", "--", 'Hello, "world"! $5 é']])

    def test_it_will_not_paste_unless_the_cursor_reached_the_field(self):
        self.blocked()
        self.reply(self.telegram.next_id, "words")
        self.assertEqual(self.journal("send"), [])
        self.assertIn("changed", self.telegram.last_text())

    def test_a_reply_goes_only_to_the_terminal_of_the_message(self):
        self.pair()
        self.world({"t1": term("t1", screens.QUESTION), "t2": term("t2", screens.QUESTION, cwd="/home/sam/other")})
        self.daemon.scan()
        records = self.store.read()["prompts"].values()
        message = next(r for r in records if r["address"] == "t2")["message_id"]
        self.change("t2", next={"screen": screens.QUESTION_TYPING})
        self.reply(message, "send this to t1 please")
        self.assertEqual(self.typed()[0], ["keys", "t2", "4"])
        self.assertEqual(self.typed()[1][2], "t2")

    def test_a_reply_can_not_answer_a_permission_prompt(self):
        self.blocked(screen=screens.BASH, kind="permission")
        self.reply(self.telegram.next_id, "1")
        self.assertEqual(self.typed(), [])
        self.assertIn("can't answer", self.telegram.last_text())

    def test_not_even_with_approvals_on(self):
        self.pair()
        self.set(approvals=True)
        self.world({"t1": term("t1", screens.BASH, kind="permission")})
        self.daemon.scan()
        self.reply(self.telegram.next_id, "1")
        self.assertEqual(self.typed(), [])

    def test_an_unknown_screen_with_no_kind_takes_no_text_by_default(self):
        self.blocked(screen=screens.UNKNOWN, kind=None, app="other")
        self.assertIn("can't be answered", self.telegram.last_text())
        self.reply(self.telegram.next_id, "y")
        self.assertEqual(self.typed(), [])

    def test_an_unknown_permission_screen_takes_no_text_by_default(self):
        self.blocked(screen=screens.UNKNOWN, kind="permission")
        self.reply(self.telegram.next_id, "y")
        self.assertEqual(self.typed(), [])

    def test_an_unknown_question_screen_takes_text(self):
        self.blocked(screen=screens.UNKNOWN, kind="question", app="other")
        self.assertIn("Continue with the sample task?", self.telegram.last_text())
        self.reply(self.telegram.next_id, "not yet")
        self.assertEqual(self.typed(), [["send", "--force", "t1", "--", "not yet"]])

    def test_a_reply_after_the_screen_changed_is_refused(self):
        self.blocked()
        self.change("t1", screen=screens.BASH)
        self.reply(self.telegram.next_id, "words")
        self.assertEqual(self.typed(), [])

    def test_a_reply_after_the_limit_is_refused(self):
        self.blocked()
        self.clock[0] += policy.PROMPT_TTL_MS + 1
        self.reply(self.telegram.next_id, "words")
        self.assertEqual(self.typed(), [])

    def test_a_reply_uses_the_question_up(self):
        self.blocked()
        data = self.button("Dog")
        self.change("t1", next={"screen": screens.QUESTION_TYPING})
        self.reply(self.telegram.next_id, "words")
        self.tap(data)
        self.assertEqual(len(self.journal("keys")), 1)

    def test_newlines_and_controls_can_not_press_keys(self):
        self.blocked()
        self.change("t1", next={"screen": screens.QUESTION_TYPING})
        self.reply(self.telegram.next_id, "one\ntwo\x1b[A\x03")
        self.assertEqual(self.journal("send")[0][-1], "one two")

    def test_a_reply_to_some_other_message_goes_nowhere(self):
        self.blocked()
        self.reply(1, "words")
        self.assertEqual(self.typed(), [])

    def test_a_reply_is_written_to_the_audit_log_with_secrets_hidden(self):
        self.blocked()
        self.change("t1", next={"screen": screens.QUESTION_TYPING})
        secret = "sk-" + "abcdefghij" * 3
        self.reply(self.telegram.next_id, f"use {secret}")
        log = self.store.audit_path.read_text(encoding="utf-8")
        self.assertIn('"how": "type"', log)
        self.assertNotIn(secret, log)


class Finished(DaemonCase):
    def finish(self):
        self.pair()
        self.set(finished=True)
        self.world({"t1": term("t1", "", kind=None, state="working")})
        self.daemon.scan()
        self.change("t1", status={"app": "claude-code", "state": "done", "msg": "Sorted the sample list"})
        self.daemon.scan()

    def test_off_by_default(self):
        self.pair()
        self.world({"t1": term("t1", "", kind=None, state="working")})
        self.daemon.scan()
        self.change("t1", status={"app": "claude-code", "state": "done"})
        self.daemon.scan()
        self.assertEqual(self.telegram.sent(), [])

    def test_on_it_says_what_finished(self):
        self.finish()
        self.assertIn("finished", self.telegram.last_text())
        self.assertIn("Sorted the sample list", self.telegram.last_text())

    def test_it_says_so_once(self):
        self.finish()
        self.daemon.scan()
        self.assertEqual(len(self.telegram.sent()), 1)

    def test_a_reply_is_a_new_prompt_with_no_force(self):
        self.finish()
        self.reply(self.telegram.next_id, "Now reverse it")
        self.assertEqual(self.typed(), [["send", "t1", "--", "Now reverse it"]])

    def test_a_reply_may_have_more_than_one_line(self):
        self.finish()
        self.reply(self.telegram.next_id, "One\nTwo")
        self.assertEqual(self.journal("send")[0][-1], "One\nTwo")

    def test_a_bang_is_refused_because_it_skips_approval(self):
        self.finish()
        message = self.telegram.next_id  # Each refusal is a new message, which moves next_id.
        for text in ("!rm notes.txt", "  !rm notes.txt", "​!rm notes.txt", "\n!rm notes.txt"):
            self.reply(message, text)
        self.assertEqual(self.typed(), [])
        self.assertEqual(self.store.audit_path.read_text(encoding="utf-8").count('"result": "refused"'), 4)

    def test_a_slash_command_is_refused(self):
        self.finish()
        self.reply(self.telegram.next_id, "/permissions")
        self.assertEqual(self.typed(), [])

    def test_a_refused_reply_is_in_the_audit_log(self):
        self.finish()
        self.reply(self.telegram.next_id, "!rm notes.txt")
        self.assertIn('"result": "refused"', self.store.audit_path.read_text(encoding="utf-8"))

    def test_a_reply_after_the_agent_moved_on_is_refused(self):
        self.finish()
        self.change("t1", turn=5)
        self.reply(self.telegram.next_id, "words")
        self.assertEqual(self.typed(), [])

    def test_a_reply_to_a_working_agent_is_refused(self):
        self.finish()
        self.change("t1", status={"app": "claude-code", "state": "working"})
        self.reply(self.telegram.next_id, "words")
        self.assertEqual(self.typed(), [])

    def test_a_reply_after_the_limit_is_refused(self):
        self.finish()
        self.clock[0] += policy.FINISHED_TTL_MS + 1
        self.reply(self.telegram.next_id, "words")
        self.assertEqual(self.typed(), [])

    def test_a_reply_with_finished_messages_off_is_refused(self):
        self.finish()
        self.set(finished=False)
        self.reply(self.telegram.next_id, "words")
        self.assertEqual(self.typed(), [])

    def test_a_too_long_reply_is_refused(self):
        self.finish()
        self.reply(self.telegram.next_id, "x" * (policy.MAX_REPLY + 1))
        self.assertEqual(self.typed(), [])


class Commands(DaemonCase):
    def test_agents_lists_blocked_first_and_only_agents(self):
        self.pair()
        self.world({
            "t1": term("t1", "", kind=None, state="idle", cwd="/home/sam/toy-api"),
            "t2": term("t2", screens.QUESTION, cwd="/home/sam/demo-site"),
            "t3": {"address": "t3", "state": "live", "cwd": "/home/sam", "status": None, "screen": ""},
        })
        self.say("/agents")
        text = self.telegram.last_text()
        self.assertLess(text.index("demo-site"), text.index("toy-api"))
        self.assertNotIn("t3", text)

    def test_no_agents(self):
        self.pair()
        self.say("/agents")
        self.assertEqual(self.telegram.last_text(), "No agents.")

    def test_a_folder_name_is_escaped(self):
        self.pair()
        self.world({"t1": term("t1", screens.QUESTION, cwd="/home/sam/<b>x</b>&")})
        self.say("/agents")
        self.assertNotIn("<b>x", self.telegram.last_text())

    def test_a_loose_message_gets_a_pointer(self):
        self.pair()
        self.say("hello")
        self.assertIn("/agents", self.telegram.last_text())


class PauseAndWatch(DaemonCase):
    def test_paused_sends_nothing(self):
        self.pair()
        self.set(paused=True)
        self.world({"t1": term("t1", screens.QUESTION)})
        self.daemon.scan()
        self.assertEqual(self.telegram.sent(), [])

    def test_paused_refuses_a_tap(self):
        self.blocked()
        data = self.button("Dog")
        self.set(paused=True)
        self.tap(data)
        self.assertEqual(self.typed(), [])
        self.assertEqual(self.answers()[-1], "PageMe is paused.")

    def test_resuming_sends_what_is_waiting(self):
        self.pair()
        self.set(paused=True)
        self.world({"t1": term("t1", screens.QUESTION)})
        self.daemon.scan()
        self.say("/resume")
        self.daemon.scan()
        self.assertIn("Which pet", self.telegram.last_text())

    def test_pause_works_from_telegram(self):
        self.pair()
        self.say("/pause")
        self.assertTrue(self.store.read()["settings"]["paused"])

    def test_watch_mode_shows_no_buttons(self):
        self.pair()
        self.set(mode="watch")
        self.world({"t1": term("t1", screens.QUESTION)})
        self.daemon.scan()
        self.assertEqual(self.telegram.buttons(), [])
        self.assertIn("watch mode", self.telegram.last_text())

    def test_watch_mode_presses_and_types_nothing_whatever_arrives(self):
        self.pair()
        self.set(mode="watch", finished=True)
        self.world({"t1": term("t1", screens.QUESTION)})
        self.daemon.scan()
        pid, message = self.pid(), self.telegram.next_id
        self.tap(f"{pid}:o1", message_id=message)
        self.reply(message, "words")
        self.assertEqual(self.typed(), [])


class Secrecy(DaemonCase):
    def test_the_token_is_only_ever_in_the_url(self):
        self.blocked()
        self.tap(self.button("Dog"))
        for call in self.telegram.calls:
            self.assertEqual(call["bot"], f"bot{TOKEN}")
            self.assertNotIn(TOKEN, json.dumps(call["body"]))

    def test_the_token_is_not_in_argv_files_or_logs(self):
        self.blocked()
        self.tap(self.button("Dog"))
        self.telegram.fail["sendMessage"] = {"ok": False, "error_code": 400, "description": f"bad {TOKEN} here"}
        self.say("/agents")
        self.assertNotIn(TOKEN, json.dumps(self.journal()))
        self.assertNotIn(TOKEN, "\n".join(self.logged))
        for path in self.store.folder.iterdir():
            self.assertNotIn(TOKEN.encode(), path.read_bytes())

    def test_only_the_four_calls_are_used(self):
        self.blocked()
        self.tap(self.button("Dog"))
        self.assertLessEqual({call["method"] for call in self.telegram.calls}, {"getUpdates", "sendMessage", "editMessageText", "answerCallbackQuery"})

    def test_a_429_holds_sending(self):
        self.pair()
        self.world({"t1": term("t1", screens.QUESTION)})
        self.telegram.fail["sendMessage"] = {"ok": False, "error_code": 429, "description": "Too many", "parameters": {"retry_after": 30}}
        self.daemon.scan()
        del self.telegram.fail["sendMessage"]
        self.daemon.scan()
        self.assertEqual(len(self.telegram.sent()), 1)
        self.clock[0] += 31_000
        self.daemon.scan()
        self.assertEqual(len(self.telegram.sent()), 2)

    def test_an_update_is_never_handled_twice_after_a_restart(self):
        self.blocked()
        offset_before = self.store.read()["offset"]
        self.tap(self.button("Dog"))
        self.assertGreater(self.store.read()["offset"], offset_before)
        self.assertEqual(self.telegram.calls[-1]["method"], "editMessageText")


if __name__ == "__main__":
    unittest.main()
