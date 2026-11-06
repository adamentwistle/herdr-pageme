"""Keeps the bot token in the system's credential store: Credential Manager on Windows through its own API, the login keychain
on macOS through `security`. Elsewhere, a file only this user can read. The token never goes in argv: Windows needs no program,
and `security -i` takes its command on stdin."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from store import private_write, state_dir

TOKEN_SHAPE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")
SERVICE = "herdr-pageme"
ACCOUNT = "bot-token"


def target() -> str:
    """The credential's name. A test sets its own, so it can never read or replace a real token."""
    return os.environ.get("PAGEME_TEST_CREDENTIAL") or f"{SERVICE}/{ACCOUNT}"


def where() -> str:
    if sys.platform == "win32":
        return "Windows Credential Manager"
    if sys.platform == "darwin":
        return "macOS keychain"
    return "a private file"


def valid(token: str) -> bool:
    return bool(TOKEN_SHAPE.match(token))


def save(token: str) -> None:
    if not valid(token):
        raise ValueError("That doesn't look like a bot token.")
    if sys.platform == "win32":
        _windows_save(token)
    elif sys.platform == "darwin":
        _mac_run(f'add-generic-password -U -a "{ACCOUNT}" -s "{target()}" -w "{token}"\n')
    else:
        _file().parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_write(_file(), token.encode("ascii"))


def load() -> Optional[str]:
    if sys.platform == "win32":
        return _windows_load()
    if sys.platform == "darwin":
        done = subprocess.run(
            ["security", "find-generic-password", "-a", ACCOUNT, "-s", target(), "-w"],
            capture_output=True, timeout=15,
        )
        return done.stdout.decode("ascii", "replace").strip() or None if done.returncode == 0 else None
    try:
        return _file().read_text("ascii").strip() or None
    except OSError:
        return None


def clear() -> None:
    if sys.platform == "win32":
        _windows_clear()
    elif sys.platform == "darwin":
        subprocess.run(["security", "delete-generic-password", "-a", ACCOUNT, "-s", target()], capture_output=True, timeout=15)
    else:
        try:
            _file().unlink()
        except OSError:
            pass


def _file() -> Path:
    return state_dir() / "token"


def _mac_run(command: str) -> None:
    done = subprocess.run(["security", "-i"], input=command.encode("ascii"), capture_output=True, timeout=15)
    if done.returncode != 0:
        raise OSError("The keychain refused the token.")


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Credential(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2
    _ERROR_NOT_FOUND = 1168
    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _advapi.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    _advapi.CredWriteW.restype = wintypes.BOOL
    _advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_Credential))]
    _advapi.CredReadW.restype = wintypes.BOOL
    _advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _advapi.CredDeleteW.restype = wintypes.BOOL
    _advapi.CredFree.argtypes = [ctypes.c_void_p]
    _advapi.CredFree.restype = None

    def _windows_save(token: str) -> None:
        blob = token.encode("ascii")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _Credential()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = target()
        credential.UserName = ACCOUNT
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        if not _advapi.CredWriteW(ctypes.byref(credential), 0):
            raise OSError(f"Credential Manager refused the token: {ctypes.get_last_error()}")

    def _windows_load() -> Optional[str]:
        found = ctypes.POINTER(_Credential)()
        if not _advapi.CredReadW(target(), _CRED_TYPE_GENERIC, 0, ctypes.byref(found)):
            return None
        try:
            size = found.contents.CredentialBlobSize
            return bytes(found.contents.CredentialBlob[:size]).decode("ascii", "replace")
        finally:
            _advapi.CredFree(found)

    def _windows_clear() -> None:
        if not _advapi.CredDeleteW(target(), _CRED_TYPE_GENERIC, 0) and ctypes.get_last_error() != _ERROR_NOT_FOUND:
            raise OSError("Credential Manager wouldn't remove the token.")
