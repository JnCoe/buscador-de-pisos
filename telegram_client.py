import mimetypes
import os
import time
from dataclasses import dataclass
from typing import Optional

import requests


class TelegramError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramClient:
    bot_token: str
    chat_id: str
    api_base: str = "https://api.telegram.org"

    @classmethod
    def from_env(cls) -> "TelegramClient":
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not bot_token or not chat_id:
            raise TelegramError(
                "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID environment variable"
            )
        return cls(bot_token=bot_token, chat_id=chat_id)

    def _url(self, method: str) -> str:
        return f"{self.api_base}/bot{self.bot_token}/{method}"

    def send_message(self, text: str, *, parse_mode: Optional[str] = None) -> None:
        # Telegram message limit is 4096 chars. Keep it safe.
        if len(text) > 3900:
            text = text[:3900] + "\n\n[truncated]"

        payload = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
        if parse_mode:
            payload["parse_mode"] = parse_mode

        self._post_with_retry("sendMessage", data=payload, timeout=6.0)

    def send_file(self, *, path: str, filename: Optional[str] = None) -> None:
        # Prefer sendPhoto for common image types to get inline preview.
        content_type, _ = mimetypes.guess_type(filename or path)
        is_image = bool(content_type and content_type.startswith("image/"))
        method = "sendPhoto" if is_image else "sendDocument"
        field = "photo" if is_image else "document"

        with open(path, "rb") as f:
            files = {field: (filename or os.path.basename(path), f)}
            data = {"chat_id": self.chat_id}
            self._post_with_retry(method, data=data, files=files, timeout=20.0)

    def _post_with_retry(
        self,
        method: str,
        *,
        data: dict,
        files: Optional[dict] = None,
        timeout: float,
    ) -> None:
        url = self._url(method)

        # Two attempts with short backoff keeps webhook fast but resilient.
        last_exc: Optional[Exception] = None
        for attempt in range(2):
            try:
                resp = requests.post(url, data=data, files=files, timeout=timeout)
                if resp.status_code != 200:
                    raise TelegramError(
                        f"Telegram API error ({resp.status_code}): {resp.text}"
                    )
                return
            except (requests.RequestException, TelegramError) as exc:
                last_exc = exc
                if attempt == 0:
                    time.sleep(0.6)
                    continue
                break

        raise TelegramError(str(last_exc))

