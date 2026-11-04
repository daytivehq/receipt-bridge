"""Synthetic images and adapters used exclusively by automated tests."""

from __future__ import annotations

import io
import json
from datetime import date

import httpx
from PIL import Image, ImageDraw

from receipt_bridge.models import Extraction

ACCOUNT = {"id": "test-account", "currency": "KRW", "scale": 0, "archived": False, "role": "owner"}
CATEGORIES = [{"code": "food", "name": "식비", "kind": "expense", "hidden": False}]


def sample_image():
    image = Image.new("RGB", (800, 1200), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (80, 120),
        f"TEST RECEIPT - NOT REAL\nSample Store\n{date.today()} 12:30\nTotal KRW 12000",
        fill="black",
        spacing=25,
        font_size=32,
    )
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def sample_extraction(**changes):
    data = {
        "merchant": "테스트 식당",
        "date": date.today().isoformat(),
        "time": "12:30",
        "amount": "12000",
        "currency": "KRW",
        "category": "food",
        "subtotal": None,
        "tax": None,
        "total_evidence": "Total KRW 12000",
        "date_evidence": date.today().isoformat(),
        "warnings": [],
    }
    data.update(changes)
    return Extraction(**data)


class DemoMessenger:
    def __init__(self):
        self.messages = []
        self.downloads = 0

    def download(self, file_id):
        self.downloads += 1
        return sample_image()

    def send(self, chat, text, image=None, buttons=None):
        self.messages.append((chat, text, image, buttons))

    def answer(self, callback_id, text="접수했습니다"):
        pass


class DemoAI:
    def extract(self, image, categories):
        return sample_extraction()


class DemoLedgerAPI:
    def __init__(self):
        self.posts = []
        self.uploads = []
        self.keys = {}
        self.fail_create_after_commit = False
        self.fail_attach = False
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        assert request.headers["Authorization"] == "Bearer TEST_ONLY"
        if request.url.path == "/api/v1/accounts":
            return httpx.Response(200, json=[ACCOUNT])
        if request.url.path == "/api/v1/categories":
            assert request.url.params["account"] == ACCOUNT["id"]
            assert request.url.params["kind"] == "expense"
            return httpx.Response(200, json=CATEGORIES)
        if request.url.path == "/api/v1/transactions":
            payload = json.loads(request.content)
            key = request.headers["Idempotency-Key"]
            self.posts.append((key, payload))
            if key in self.keys:
                assert self.keys[key] == payload
                return httpx.Response(200, json={"id": "test-posting"})
            self.keys[key] = payload
            if self.fail_create_after_commit:
                self.fail_create_after_commit = False
                raise httpx.ReadTimeout("simulated lost response")
            return httpx.Response(201, json={"id": "test-posting"})
        if request.url.path == "/api/v1/transactions/test-posting/receipts":
            self.uploads.append(request.content)
            assert b'name="file"' in request.content
            assert b"image/jpeg" in request.content
            if self.fail_attach:
                return httpx.Response(503, headers={"Retry-After": "1"}, json={"error": "busy"})
            return httpx.Response(201, json={"id": "test-receipt"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")


def photo_update(update_id=1, message=10, user=1, chat=1):
    return {
        "update_id": update_id,
        "message": {
            "message_id": message,
            "from": {"id": user},
            "chat": {"id": chat},
            "photo": [{"file_id": "TEST_IMAGE"}],
        },
    }
