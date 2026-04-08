import mimetypes
import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

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

    def send_photo(
        self,
        *,
        path: str,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> None:
        with open(path, "rb") as f:
            files = {"photo": (filename or os.path.basename(path), f)}
            data = {"chat_id": self.chat_id}
            if caption:
                # Telegram caption limit is ~1024 chars for photos; keep it safe.
                if len(caption) > 950:
                    caption = caption[:950] + "\n\n[truncated]"
                data["caption"] = caption
            if parse_mode:
                data["parse_mode"] = parse_mode
            self._post_with_retry("sendPhoto", data=data, files=files, timeout=20.0)

    def download_to_tmp(self, url: str, *, filename_hint: str, timeout: float = 5.0) -> str:
        """
        Downloads a remote file to /tmp and returns the local path.
        Uses a short timeout to avoid hanging the webhook on Fly.io.
        """
        parsed = urlparse(url)
        ext = os.path.splitext(parsed.path)[1]
        if not ext or len(ext) > 8:
            ext = ".bin"
        safe_hint = "".join(ch for ch in filename_hint if ch.isalnum() or ch in ("-", "_"))[:64]
        if not safe_hint:
            safe_hint = "download"
        out_path = os.path.join("/tmp", f"{safe_hint}{ext}")

        resp = requests.get(url, timeout=(min(3.0, timeout), timeout), stream=True)
        if resp.status_code != 200:
            raise TelegramError(f"download failed ({resp.status_code})")
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
        return out_path

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

