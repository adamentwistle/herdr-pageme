# PageMe threat model

PageMe lets a phone press keys in a terminal where an agent is running. That is dangerous on purpose, so this says what it protects, what it doesn't, and which code holds each line.

## What's at stake

- **Approval.** A permission prompt is the last check before an agent runs something. Anything that can answer it can run commands on your machine.
- **Screen text.** It can hold source code, paths, tokens and customer data, and PageMe sends some of it to Telegram.
- **The bot token.** With it, someone can read what the bot receives and post as the bot.

## Who we assume is trying

| Attacker | Can do | Can't do |
| --- | --- | --- |
| Hostile text: a web page, a file or command output the agent read | Write nearly anything onto the screen, and steer the agent into asking a misleading question | Reach the bottom of the screen below the real menu, or set the status the agent reports |
| A stranger who finds the bot | Send it messages and button payloads | Get any reply, or reach anything past the pairing check |
| Someone holding your unlocked phone or Telegram account | Everything the paired user can do | Turn approving on, unless it's already on |
| Telegram itself, or anyone who can read bot traffic | Read everything PageMe sends, and forge what it receives | Read what PageMe never sent |
| Someone who stole the bot token | Read new updates, post as the bot, and take updates before the daemon does | Tap as you: a tap needs your user id, from Telegram, and a random button id |

## The rules, and where each is held

**Pairing** (`daemon.py`, `_try_pairing`). A code of 8 characters from a 31 character alphabet, made by `secrets`, works once, for 5 minutes. Five wrong guesses burn it. It must come as typed text in a private chat, not forwarded, not from a bot, and not older than the code. It binds one user id and one chat id. While paired, a second pairing is refused. Everyone else is ignored with no reply: `_is_paired` runs before anything else in `_tap` and `_message`, and an unanswered tap doesn't even stop Telegram's spinner. Unpairing drops the user and every open question at once.

**The default** (`store.py`, `policy.py`). Notify plus answering questions. Approving is off. It can only be turned on from this machine, and the panel asks twice. PageMe says so in the chat whenever approving turns on or off, and whenever a daemon starts with it on. No Telegram command changes it.

**Options that last are never buttons** (`prompts.py`). Permission prompts use a list of exact labels. Everything else is `hidden`, in every mode, including wordings that don't exist yet. A denylist wouldn't do: real prompts already say "Yes, and switch to auto mode", "Yes, and switch to accept edits" and "Yes, and use auto mode", and none says "always". Question options go through a word list as well, because they are the agent's own text. A narrow pane wraps a label, and a wrapped line looks just like a description, so every line under an option counts as part of it: an exact `Yes` with anything below it is not exact, and the word list reads the whole option. An option can lose its button over a harmless description, which is the safe way to be wrong.

**A permission prompt can't pass as a question** (`prompts.py`, `parse`). A prompt is a question only if the agent reports `kind: question` and the screen has a question dialog's shape: a footer line starting `Enter to select` below the menu, or the exact review page. Words inside an option or a description don't count, and an option is never taken for a footer. If either disagrees it is a permission prompt, so a stale report or a hostile screen fails towards the stricter side. Codex reports no `kind` at all, so a missing `kind` counts as a permission.

**A tap is checked at the moment of the tap** (`daemon.py`, `_tap`, `_fresh`). In order: the sender is the paired user in the paired chat; the button id is known and belongs to that message; the prompt is unused and unexpired; PageMe isn't paused or in watch mode; the terminal is live, blocked, and was created at the same time as before; the hash of what's on screen now matches. Then the option is read again from the fresh screen and judged by today's settings. Nothing about it is trusted from the chat. The time limit is 15 minutes. Spending the prompt then asks the saved state once more, under its lock: the pairing, the pause, the mode, the expiry and whether approving is still on. The panel is another process, so its changes can land during these checks.

**The hash** (`prompts.py`, `fingerprint`) covers the address, the terminal's start time, the turn, `status_ms`, the reported kind and message, and every character of the dialog, spaces and line breaks included, leaving out only the cursor. So identical words asked again later get a new hash, an old button can't answer them, and `/tmp /cache` can't pass for `/tmp/cache`. A resized pane counts as a change, which refuses the tap and sends the question again. It covers the whole dialog, however long, up to the top of the screen where there is no rule, as with Codex. Only the copy shown on a phone is cut.

**Other machines are off by default** (`daemon.py`, `hcli.py`). With the setting off, a terminal with a machine prefix is never listed, read or pressed. A scan leaves it out. A tap, a reply and a reply to a finished message each check the setting before reading anything, and spending a prompt checks it again under the lock. Behind those, `Hc` itself refuses `get`, `read`, `keys` and `send` on such an address, asking the saved state on every call, and it refuses until the daemon has told it how to ask. So a button or reply from before the setting went off does nothing, and a path nobody thought of can't reach another machine.

**A multi-select submits what the chat shows** (`daemon.py`, `_tap`). Ticks already on the screen show in the chat, and Done presses only the digits that differ, because a digit toggles. If an option with no button is ticked, Done refuses and says to answer at the keyboard, since a phone can neither see nor clear it.

**Each button works once** (`daemon.py`, `_take`). The first accepted press spends the whole prompt, saved under a lock before the key is pressed. A saved update offset means an update is never handled twice after a crash. It can be lost instead, which is the safe way round.

**Screen text never becomes a command.** A button holds a random id and an option number. The terminal and key are looked up on this machine. `hc` is run with a list of arguments and no shell. `hcli.py` refuses any key but `1` to `9` and `right`, and any address that isn't one. Parsing reads only the menu at the very bottom of the screen, walking up, and needs options numbered 1 to n with one cursor, so a menu-shaped block higher up is just text. Anything unknown below the menu means no menu, and no buttons.

**Screen text is escaped.** It's stripped of escape sequences, control characters and invisible or direction-changing characters, before it's parsed as well as before it's shown, so a word is judged as it will look. Then it's HTML-escaped and put in a `<pre>` block, so it can't make links, mentions or look like PageMe's own words. Button labels are plain text in Telegram and go through the same cleaning.

**Free text is the risky path** (`policy.py`, `may_type`). Pasted text could be a `1` or a `y`, so:

- Keys can't carry real text: `hc keys` lower-cases letters and refuses most punctuation. So text uses `hc send --force`, the one place PageMe forces anything.
- It's allowed on a question with an answer field. PageMe presses that row's digit, reads the screen again, and pastes only if the cursor is on that field of the same question.
- It's never allowed on a parsed permission prompt, in any mode.
- No reply on any path may start with `!` or `/`, judged by the first character a person would see, past whitespace, invisible characters and blank letters, and with wide forms such as `！` read as plain ones.
- On a screen it can't read, it's allowed only if the agent reports `kind: question`, nothing on the screen is shaped like a menu, and the reply is over 3 characters. On a menu, a typed `2` could pick "don't ask again", which no setting allows, so turning approving on doesn't open this path. A screen with no `kind` may be a Codex approval, so it takes no text. Everything else shows its last lines and says it can't be answered from here.
- A reply goes only to the terminal saved with the message replied to. Nothing in the text can name another.
- Control characters are removed, and newlines become spaces in a dialog so a reply can't press Enter early.
- After the digit, the saved state is asked again before the paste, so unpairing or pausing in that moment stops it.

**A reply to a finished agent is a new prompt** (`policy.py`, `reply_refusal`). This is off unless finished messages are on, lasts an hour, and needs the same terminal on the same turn, not blocked. A leading `!` is refused in every mode and on every reply path, dialogs included: pasted into a real Claude Code session, it ran a shell command with no permission prompt at all, even in manual mode. A leading `/` is refused too, because slash commands can change the permission mode.

**Redaction** (`redact.py`) runs on everything from a screen before it's capped: known token shapes, private key blocks, password-looking lines including names such as `DB_PASSWORD`, assigned values such as `API_KEY=...`, logins in URLs, and long random words. It runs before the cut, so a cut can't expose half a secret. It also runs on the audit log, and on what a closed message says was picked.

**The token** (`credential.py`, `telegram.py`). It sits in Windows Credential Manager through its own API, or the macOS keychain through `security -i` on stdin, or elsewhere in a file only you can read. It's never in argv, logs or the repo. The panel never handles it: it's typed into its own terminal with echo off. It is in every request's URL, so URLs are never logged, errors are scrubbed, and redirects are refused. The API address is fixed. Tests can change it only to `http://127.0.0.1:<port>`.

**An agent's own name is untrusted** (`prompts.py`, `known_agent`). `status.app` is whatever the terminal reported. Only `claude-code` and `codex` go any further, and anything else is stored and shown as "agent", so nothing from it reaches `state.json` or a message.

**Flooding.** 20 messages a minute at most, Telegram's `retry_after` is obeyed, and a screen that won't hold still sends at most one message per 20 seconds.

**The audit log** (`audit.jsonl`) has one line per answer given or refused for a known terminal: the time, terminal, what was pressed or typed with secrets hidden, the hash, the user, the result and why. Taps and replies from anyone else aren't logged, and nor is a reply to a message PageMe doesn't know.

## What it doesn't protect

- **Telegram can read everything sent.** Bot chats aren't end-to-end encrypted. Secret chats don't exist for bots.
- **Redaction misses things.** A secret with no recognisable shape goes through, and so can one split across wrapped lines.
- **A question can lie.** The agent writes its own question, so hostile text can steer it into asking something misleading. PageMe shows who asked and where, but can't tell you the words are honest. A question dialog can't approve a tool call, but your answer still steers the agent.
- **The approving prompt shows what the screen shows.** With approving on, you're approving from a small screen, on text an attacker may have shaped. A long command can be cut off. Read it at the terminal when it matters.
- **Replies are prompts.** With finished messages on, whoever holds your Telegram account can give your agents new work. If an agent runs in auto mode, nothing asks anyone. Leave finished messages off if that's not acceptable.
- **Anything running as you beats this.** A process with your user's rights can read the state file and the token, or turn approving on. An agent with shell access is such a process. PageMe tells the chat when approving turns on, which is a warning and not a lock.
- **What isn't on the screen isn't hashed.** While an agent is blocked, `hc read` gives only the visible screen, so a dialog taller than the terminal has parts neither you nor the hash can see. The agent's reported message and `status_ms` are still in the hash. Read a long command at the terminal.
- **The hash starts at the topmost solid rule on the screen.** A rule inside a question can't shorten it. Text above that rule isn't covered, and with no rule at all, as with Codex, the whole screen is, so anything moving there makes a tap read as stale. That's the safe way to be wrong.
- **There's a small gap after the check.** `hc keys` waits for a person to stop typing, up to about 3 seconds, and the screen could change in that time. A digit then lands on whatever is showing. This needs someone at the keyboard at the same moment as the tap. Unpairing, or turning approving or other machines off, in the same instant can also lose the race, though for other machines `Hc` checks once more as the press goes out: the last check and the press are two steps, because holding the state's lock across a press could block the panel for seconds.
- **Look-alike letters beat the word list.** A Cyrillic letter in "Always" gets past the check on question options. Wide letters and invisible characters don't. A question option can't approve a tool call, so this is a limit on tidiness and not on approval.
- **Status can be faked by a program.** Anything writing to a terminal can send a status report. It could fake `blocked` or `question`, but the shape check still has to pass, and a key press only reaches that same program.
- **A stolen token can steal updates.** It can't tap as you, but it can stop PageMe hearing you. Replace the token with @BotFather if you suspect that.
- **A trust dialog isn't reported as blocked**, so a session stopped there sends nothing.
- **Windows files rely on the profile folder's access list.** The state folder is not given its own.
