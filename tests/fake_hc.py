"""A stand-in for `hc`, run as a real program so the daemon's arguments are tested too. It reads its terminals from the JSON
file named by FAKE_HC_WORLD and writes every call to the journal in that file. Like the real core, it refuses `send` to a blocked
terminal unless forced, with exit code 9. `next` holds what a terminal becomes after its next key press."""
import json
import os
import sys
import time


def load(path):
    for _ in range(100):
        try:
            with open(path, encoding="utf-8") as source:
                return json.load(source)
        except (ValueError, PermissionError):
            time.sleep(0.01)
    raise SystemExit("world unreadable")


def save(path, world):
    temp = f"{path}.{os.getpid()}"
    with open(temp, "w", encoding="utf-8") as out:
        json.dump(world, out)
    for _ in range(100):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            time.sleep(0.01)


def fail(kind, message, code):
    sys.stderr.write(json.dumps({"error": {"kind": kind, "message": message}}))
    return code


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    path = os.environ["FAKE_HC_WORLD"]
    world = load(path)
    args = sys.argv[1:]
    world["journal"].append(args)
    command = args[0]
    terminals = world["terminals"]
    code = 0
    if command == "ls":
        rows = []
        for t in terminals.values():
            status = t.get("status")
            rows.append({"address": t["address"], "cwd": t.get("cwd"), "state": t["state"], "turn": t.get("turn"), "status": status["state"] if status else None})
        print(json.dumps({"terminals": rows}))
    elif command == "get":
        t = terminals.get(args[1])
        if t:
            print(json.dumps({k: v for k, v in t.items() if k not in ("screen", "next")}))
        else:
            code = fail("not_found", "no such terminal", 3)
    elif command == "read":
        t = terminals.get(args[1])
        if t:
            sys.stdout.write(t["screen"])
        else:
            code = fail("not_found", "no such terminal", 3)
    elif command == "keys":
        t = terminals.get(args[1])
        if not t:
            code = fail("not_found", "no such terminal", 3)
        else:
            print(json.dumps({"status": "blocked"}))
            if t.get("next"):
                t.update(t.pop("next"))
    elif command == "send":
        rest = args[1:]
        force = "--force" in rest
        if force:
            rest.remove("--force")
        address = rest[0]
        t = terminals.get(address)
        if not t:
            code = fail("not_found", "no such terminal", 3)
        elif (t.get("status") or {}).get("state") == "blocked" and not force:
            code = fail("blocked", "is blocked", 9)
        else:
            print(json.dumps({"started": True}))
    elif command == "events":
        time.sleep(float(os.environ.get("FAKE_HC_EVENTS_S", "30")))
    else:
        code = fail("invalid_params", f"unknown {command}", 2)
    save(path, world)
    return code


if __name__ == "__main__":
    sys.exit(main())
