"""Talks to herdr-core through `hc`. No shell anywhere: arguments are a list, so text from a phone or a screen is only ever one
argument. Keys are checked here as the last step before anything is pressed."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

from policy import ADDRESS, PRESSABLE, REMOTE_OFF, is_remote

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class HcError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def _base() -> List[str]:
    test = os.environ.get("PAGEME_TEST_HC")
    if test:
        return json.loads(test)
    found = shutil.which("hc")
    if not found:
        raise HcError("hc isn't on PATH.")
    return [found]


def _env() -> dict:
    # Inside a terminal, hc adds a <hc from=...> tag to what it sends. A person's answer should arrive as they wrote it.
    env = dict(os.environ)
    env.pop("HC_TERMINAL_ID", None)
    return env


class Hc:
    def __init__(self):
        self.base = _base()
        # The last word on other machines, asked on every call that touches one terminal. Off until the daemon says how to
        # ask, so a path nobody thought of can't reach another machine.
        self.remote_allowed = lambda: False

    def _check(self, address: str) -> None:
        _check(address)
        if is_remote(address) and not self.remote_allowed():
            raise HcError(REMOTE_OFF)

    def run(self, args: List[str], timeout: float = 15) -> Tuple[int, str, str]:
        try:
            done = subprocess.run(self.base + args, capture_output=True, timeout=timeout, env=_env(), creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise HcError(f"hc {args[0]} took too long.") from None
        except OSError as error:
            raise HcError(f"hc wouldn't start: {error}") from None
        return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")

    def _json(self, args: List[str]) -> dict:
        code, out, err = self.run(args)
        if code != 0:
            raise HcError(_message(err) or f"hc {args[0]} failed.", code)
        try:
            return json.loads(out)
        except ValueError:
            raise HcError(f"hc {args[0]} printed something that isn't JSON.") from None

    def ls(self) -> List[dict]:
        return self._json(["ls", "--json"]).get("terminals", [])

    def get(self, address: str) -> dict:
        self._check(address)
        return self._json(["get", address, "--json"])

    def read(self, address: str, lines: int = 0) -> str:
        self._check(address)
        code, out, err = self.run(["read", address, "--lines", str(lines)])
        if code != 0:
            raise HcError(_message(err) or "hc read failed.", code)
        return out

    def keys(self, address: str, keys: List[str]) -> None:
        self._check(address)
        for key in keys:
            if not PRESSABLE.match(key):
                raise ValueError(f"PageMe doesn't press {key!r}")
        code, _out, err = self.run(["keys", address, *keys], timeout=30)
        if code != 0:
            raise HcError(_message(err) or "hc keys failed.", code)

    def send(self, address: str, text: str, force: bool = False) -> None:
        self._check(address)
        args = ["send"] + (["--force"] if force else []) + [address, "--", text]
        code, _out, err = self.run(args, timeout=30)
        if code != 0:
            raise HcError(_message(err) or "hc send failed.", code)

    def events(self) -> Optional[subprocess.Popen]:
        return subprocess.Popen(
            self.base + ["events", "--json"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_env(), creationflags=NO_WINDOW
        )


def _check(address: str) -> None:
    if not ADDRESS.match(address):
        raise ValueError("Not a terminal address.")


def _message(stderr: str) -> str:
    try:
        return json.loads(stderr)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return stderr.strip()[:200]
