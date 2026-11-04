from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Protocol

import httpx
from PIL import Image

from .images import jpeg_bytes
from .ledger import RemoteError, retry_delay


class Messenger(Protocol):
    def download(self, file_id: str) -> bytes: ...
    def send(self, chat: int, text: str, image: Path | None = None, buttons: dict | None = None): ...


def identity(update: dict):
    callback = update.get("callback_query")
    if callback:
        message = callback.get("message", {})
        return callback.get("from", {}).get("id"), message.get("chat", {}).get("id")
    message = update.get("message", {})
    return message.get("from", {}).get("id"), message.get("chat", {}).get("id")


class Telegram:
    def __init__(self, token, max_download_mb=20, transport=None):
        self.token = token
        self.limit = max_download_mb * 1024 * 1024
        # Telegram URLs contain a secret. Never log httpx exceptions or request URLs.
        self.http = httpx.Client(timeout=50, transport=transport, trust_env=False, follow_redirects=False)

    def close(self):
        self.http.close()

    def call(self, method, data=None, files=None):
        try:
            response = self.http.post(
                f"https://api.telegram.org/bot{self.token}/{method}", data=data, files=files
            )
        except httpx.HTTPError:
            raise RemoteError("텔레그램") from None
        if not response.is_success:
            raise RemoteError("텔레그램", response.status_code, retry_delay(response))
        try:
            body = response.json()
            if not body.get("ok"):
                raise RemoteError(
                    "텔레그램", body.get("error_code", 500), body.get("parameters", {}).get("retry_after", 0)
                )
            return body["result"]
        except (ValueError, KeyError):
            raise RemoteError("텔레그램 응답 형식") from None

    def poll(self, offset):
        return self.call(
            "getUpdates", {"offset": offset, "timeout": 30, "allowed_updates": '["message","callback_query"]'}
        )

    def answer(self, callback_id, text="접수했습니다"):
        return self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def download(self, file_id):
        file = self.call("getFile", {"file_id": file_id})
        if file.get("file_size", 0) > self.limit:
            raise ValueError("사진은 설정된 수신 크기(최대 20MB) 이하로 보내주세요")
        path = file.get("file_path", "")
        if not path or path.startswith("/") or ".." in path.split("/") or ":" in path:
            raise ValueError("사진 다운로드 경로가 올바르지 않습니다")
        try:
            with self.http.stream("GET", f"https://api.telegram.org/file/bot{self.token}/{path}") as response:
                if not response.is_success:
                    raise RemoteError("텔레그램 다운로드", response.status_code, retry_delay(response))
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > self.limit:
                        raise ValueError("사진 수신 크기를 초과했습니다")
                return bytes(data)
        except httpx.HTTPError:
            raise RemoteError("텔레그램 다운로드") from None

    def send(self, chat, text, image=None, buttons=None):
        data = {"chat_id": chat}
        if buttons:
            data["reply_markup"] = json.dumps(buttons, ensure_ascii=False)
        if image:
            # Telegram sendPhoto has a stricter aspect/side constraint than Ledger.
            with Image.open(image) as source:
                preview = source.convert("RGB")
                preview.thumbnail((1800, 1800))
                if max(preview.size) / min(preview.size) > 19:
                    canvas = Image.new(
                        "RGB",
                        (
                            max(preview.width, preview.height // 19 + 1),
                            max(preview.height, preview.width // 19 + 1),
                        ),
                        "white",
                    )
                    canvas.paste(preview, (0, 0))
                    preview = canvas
                file = io.BytesIO(jpeg_bytes(preview))
            data["caption"] = text[:1000]
            return self.call("sendPhoto", data, files={"photo": ("receipt.jpg", file, "image/jpeg")})
        data["text"] = text[:4000]
        return self.call("sendMessage", data)
