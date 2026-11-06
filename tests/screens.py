"""Made-up screens with the same shape as the real ones. Every shape here was first seen on a real throwaway session in a scratch
folder, but the words are invented: no real command, file or folder is in this repo."""

RULE = "─" * 60
DASH = "╌" * 60

BASH = f"""
● Printing a sum
  ⎿  $ node -e "console.log(2+2)"

{RULE}
 Bash command
 Tip: auto mode handles these prompts for you, choose "switch to auto mode" below

 Print a sum

{DASH}
 node -e "console.log(2+2)"
{DASH}
 This command requires approval

 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, and don’t ask again for: node *
   3. Yes, and switch to auto mode · auto mode handles these prompts for you
   4. No

 Esc to cancel · Tab to amend
"""

WRITE = f"""
● Write(todo.txt)

{RULE}
 Create file
 todo.txt
{DASH}
  1 buy milk
{DASH}
 Do you want to create todo.txt?
 ❯ 1. Yes
   2. Yes, and switch to accept edits (auto-approve file edits and common file commands) for this session (shift+tab)
   3. No

 Esc to cancel · Tab to amend
"""

FETCH = f"""
● Fetch(https://example.org)

{RULE}
 Fetch
 Claude wants to fetch content from example.org
{DASH}
 url: https://example.org/
 prompt: What is the title of this page?
{DASH}
 Do you want to allow Claude to fetch this content?
 ❯ 1. Yes
   2. Yes, and don't ask again for example.org
   3. No, and tell Claude what to do differently (esc)
"""

# A command that prints a menu of its own. The real one is below it.
SPOOF = f"""
● Printing a menu
  ⎿  $ node -e "print the menu"
     ❯ 1. No
     2. Yes

{RULE}
 Bash command

 Printing a menu

{DASH}
 │ node -e "print the menu
 │  ❯ 1. No
 │    2. Yes
 │ "
{DASH}
 This command requires approval

 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, and don’t ask again for: node *
   3. Yes, and switch to auto mode · auto mode handles these prompts for you
   4. No

 Esc to cancel · Tab to amend
"""

PLAN = f"""
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
  {RULE}
   Ready to code?

   Here is Claude's plan:
  {DASH}
   Plan: tidy the sample list

   Step

   1. Sort the sample list.
   2. Remove the blank rows.
  {DASH}

  {RULE}
   Claude has written up a plan and is ready to execute. Would you like to proceed?

   ❯ 1. Yes, and use auto mode
     2. Yes, manually approve edits
     3. Tell Claude what to change
        shift+tab to approve with this feedback

   ctrl+g to edit in Notepad · ~\\plans\\sample-plan.md
"""

QUESTION = f"""
❯ Ask me which pet to draw
{RULE}
 ☐ Pet

Which pet should I draw?

❯ 1. Cat
     Sleeps on the keyboard.
  2. Dog
     Barks at the postman.
  3. Fish
     Says very little.
  4. Type something.
{RULE}
  5. Chat about this

Enter to select · ↑/↓ to navigate · Esc to cancel
"""

QUESTION_TYPING = QUESTION.replace("❯ 1. Cat", "  1. Cat").replace("  4. Type something.", "❯ 4. Type something.")

MULTI = f"""
❯ Ask me which toppings
{RULE}
←  ☐ Toppings  ✔ Submit  →

Which toppings do you want?

❯ 1. [ ] Cheese
         Melts well.
  2. [ ] Olives
         Salty.
  3. [ ] Basil
         Fresh.
  4. [ ] Type something
     Submit
{RULE}
  5. Chat about this

Enter to select · ↑/↓ to navigate · Esc to cancel
"""

REVIEW = f"""
❯ Ask me which toppings
{RULE}
←  ☒ Toppings  ✔ Submit  →

Review your answers

 ● Which toppings do you want?
   → Cheese, Basil

Ready to submit your answers?

❯ 1. Submit answers
  2. Cancel
"""

WIZARD_ONE = f"""
❯ Ask me two things
{RULE}
←  ☐ Size  ☐ Shape  ✔ Submit  →

Which size do you want?

❯ 1. Small
     Fits in a pocket.
  2. Large
     Does not.
  3. Type something.
{RULE}
  4. Chat about this

Enter to select · Tab/Arrow keys to navigate · Esc to cancel
"""

WIZARD_TWO = WIZARD_ONE.replace("☐ Size", "☒ Size").replace("Which size", "Which shape").replace("Small", "Round").replace("Large", "Square")

PREVIEW = f"""
❯ Ask me which layout
{RULE}
 ☐ Layout

Which layout do you want?

❯ 1. Compact                      ┌{"─" * 40}┐
  2. Roomy                        │ +-----------+                          │
                                  │ | Title     |                          │
                                  │ | Item Item |                          │
                                  └{"─" * 40}┘

                                  Notes: press n to add notes

{RULE}
  Chat about this

Enter to select · ↑/↓ to navigate · n to add notes · Esc to cancel
"""

CODEX = """
  >_ OpenAI Codex

› Write the sum to a file

• Running echo 4 > sum.txt

  Would you like to run the following command?

  Environment: local

  Reason: May I run `echo 4 > sum.txt` outside the sandbox?

  $ echo 4 > sum.txt


› 1. Yes, proceed (y)
  2. Yes, and don't ask again for commands that start with `echo 4 > sum.txt` (p)
  3. No, and tell Codex what to do differently (esc)

  Press enter to confirm or esc to cancel
"""

# Something PageMe has never seen.
UNKNOWN = """
  The sample tool needs your attention.

  Continue with the sample task? [y/N]
"""
