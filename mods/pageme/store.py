"""PageMe's files. All of it lives in its own folder, so a reinstall of the mod keeps the pairing, and a write here doesn't
reload the mod. The daemon and the panel's short commands both change the same state, so every change takes a lock and swaps
the file in whole."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

RECENT_MAX = 30
LOCK_WAIT_S = 10


def state_dir() -> Path:
    override = os.environ.get("PAGEME_HOME")
    return Path(override) if override else Path.home() / ".config" / "herdr-pageme"


def empty_state() -> dict:
    return {
        "version": 1,
        "pair": None,
        "code": None,
        "settings": {"paused": False, "mode": "act", "approvals": False, "finished": False, "remote": False},
        "offset": 0,
        "prompts": {},
        "finished": {},
        "recent": [],
        "telegram": {"ok": False, "ms": 0, "error": None},
        "heartbeat_ms": 0,
    }


def private_write(path: Path, data: bytes) -> None:
    """Writes a file only this user can read, by swapping it in whole."""
    handle, temp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.chmod(temp, 0o600)
        for attempt in range(40):
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                # Windows refuses a swap while another process has the file open for a moment.
                if attempt == 39:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Store:
    def __init__(self, folder: Optional[Path] = None):
        self.folder = Path(folder) if folder else state_dir()
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.folder, 0o700)
        except OSError:
            pass
        self.path = self.folder / "state.json"
        self.audit_path = self.folder / "audit.jsonl"
        self.lock_path = self.folder / "state.lock"

    def _load(self) -> Optional[dict]:
        """The file's contents, or None if there's none yet. On Windows a read can lose a moment's race with a swap, and that
        is not damage: treating it as damage would wipe the pairing."""
        for attempt in range(40):
            try:
                with open(self.path, "r", encoding="utf-8") as source:
                    return json.load(source)
            except FileNotFoundError:
                return None
            except OSError:
                if attempt == 39:
                    raise
                time.sleep(0.05)
        return None

    def read(self) -> dict:
        try:
            data = self._load()
        except ValueError:
            # A file that can't be understood is treated as never paired: nothing answers until someone pairs again.
            try:
                os.replace(self.path, str(self.path) + f".corrupt-{int(time.time())}")
            except OSError:
                pass
            return empty_state()
        if data is None:
            return empty_state()
        merged = empty_state()
        merged.update(data)
        merged["settings"] = {**empty_state()["settings"], **data.get("settings", {})}
        return merged

    @contextmanager
    def _locked(self):
        with open(self.lock_path, "a+b") as lock:
            deadline = time.time() + LOCK_WAIT_S
            while True:
                try:
                    _lock(lock)
                    break
                except OSError:
                    if time.time() > deadline:
                        raise TimeoutError("state.lock is held by something else")
                    time.sleep(0.02)
            try:
                yield
            finally:
                _unlock(lock)

    def update(self, change: Callable[[dict], object]):
        """Runs `change` on a fresh copy of the state and saves it. Returns what `change` returned."""
        with self._locked():
            state = self.read()
            result = change(state)
            private_write(self.path, json.dumps(state, ensure_ascii=False, indent=1).encode("utf-8"))
            return result

    def add_recent(self, state: dict, ms: int, kind: str, where: str, text: str) -> None:
        state["recent"].insert(0, {"ms": ms, "kind": kind, "where": where, "text": text})
        del state["recent"][RECENT_MAX:]

    def audit(self, entry: dict) -> None:
        """One line per answer given. Opened for appending with the private mode, so a new file starts private."""
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        handle = os.open(str(self.audit_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(handle, "a", encoding="utf-8") as out:
            out.write(line)


if sys.platform == "win32":
    import msvcrt

    def _lock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class SingleDaemon:
    """Holds a lock for as long as the daemon runs. Two daemons would fight over Telegram's updates."""

    def __init__(self, folder: Path):
        self.path = Path(folder) / "daemon.lock"
        self.handle = None

    def acquire(self) -> bool:
        self.handle = open(self.path, "a+b")
        try:
            _lock(self.handle)
            return True
        except OSError:
            self.handle.close()
            self.handle = None
            return False

    def release(self) -> None:
        if self.handle:
            _unlock(self.handle)
            self.handle.close()
            self.handle = None
