"""The Telegram Bot API, long polling only, with the four calls PageMe uses. No webhook, so no port is opened.

The token is part of every URL, so a URL is never logged and no error text leaves here unscrubbed. Redirects are refused, or a
redirect could carry the token to another host. The address is fixed. Tests may point it at a local server and nowhere else."""
from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request
from typing import Optional

API = "https://api.telegram.org"
METHODS = {"getUpdates", "sendMessage", "editMessageText", "answerCallbackQuery"}
LOCAL_TEST_BASE = re.compile(r"^http://127\.0\.0\.1:\d{1,5}$")
TOKEN_IN_TEXT = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,}")
POLL_SECONDS = 50


class TelegramError(Exception):
    def __init__(self, description: str, code: int = 0, retry_after: int = 0):
        super().__init__(description)
        self.description = description
        self.code = code
        self.retry_after = retry_after


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def base_url() -> str:
    override = os.environ.get("PAGEME_TEST_API_BASE")
    if override is None:
        return API
    if not LOCAL_TEST_BASE.match(override):
        raise SystemExit("PAGEME_TEST_API_BASE is for tests and must be http://127.0.0.1:<port>.")
    return override


def scrub(text: object, token: str = "") -> str:
    text = str(text)
    if token:
        text = text.replace(token, "<token>")
    return TOKEN_IN_TEXT.sub("<token>", text)


class Telegram:
    def __init__(self, token: str):
        self.token = token
        self.base = base_url()
        self.opener = urllib.request.build_opener(_NoRedirect)

    def call(self, method: str, params: dict, timeout: float = 20):
        if method not in METHODS:
            raise ValueError(f"PageMe doesn't call {method}")
        request = urllib.request.Request(
            f"{self.base}/bot{self.token}/{method}",
            data=json.dumps(params).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            body = error.read()
            if not body:
                raise TelegramError(f"HTTP {error.code}", error.code) from None
        except (urllib.error.URLError, socket.timeout, OSError) as error:
            raise TelegramError(scrub(getattr(error, "reason", error), self.token)) from None
        try:
            reply = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            raise TelegramError("Telegram sent something that isn't JSON.") from None
        if not reply.get("ok"):
            parameters = reply.get("parameters") or {}
            raise TelegramError(
                scrub(reply.get("description", "Telegram said no."), self.token),
                int(reply.get("error_code") or 0),
                int(parameters.get("retry_after") or 0),
            )
        return reply.get("result")

    def updates(self, offset: int, wait: int = POLL_SECONDS) -> list:
        params = {"offset": offset, "timeout": wait, "allowed_updates": ["message", "callback_query"]}
        return self.call("getUpdates", params, timeout=wait + 15) or []

    def send(self, chat_id: int, text: str, keyboard: Optional[list] = None) -> dict:
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}}
        if keyboard:
            params["reply_markup"] = {"inline_keyboard": keyboard}
        return self.call("sendMessage", params)

    def edit(self, chat_id: int, message_id: int, text: str, keyboard: Optional[list] = None) -> None:
        params = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "reply_markup": {"inline_keyboard": keyboard or []},
        }
        try:
            self.call("editMessageText", params)
        except TelegramError as error:
            # Telegram calls an edit that changes nothing an error. It isn't one here.
            if "not modified" not in error.description:
                raise

    def answer(self, callback_id: str, text: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190]})
