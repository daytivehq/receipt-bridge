"""Private CLI inference server. Run in a separate container with no ledger/bot credentials."""

from __future__ import annotations

import base64
import hmac
import json
import os
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .ai import run_cli
from .config import valid_runner_token
from .images import atomic_write, jpeg_bytes, load_image
from .runner_auth import runner_token
from .runner_setup import PROVIDERS, check_provider


class RunnerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args):
        self.connections = threading.BoundedSemaphore(8)
        super().__init__(*args)

    def process_request(self, request, address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.connections.release()


def serve():
    if any(
        os.getenv(key)
        for key in (
            "DUET_APP_PASSWORD",
            "DUET_APP_PASSWORD_FILE",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_BOT_TOKEN_FILE",
        )
    ):
        raise ValueError("AI runner에는 가계부·텔레그램 인증 정보를 설정하지 마세요")
    home = Path(os.environ.get("AI_HOME", "/ai-home"))
    timeout = int(os.environ.get("AI_TIMEOUT", "180"))
    # The bridge creates the shared secret; the runner mounts that volume read-only.
    for attempt in range(60):
        try:
            token = runner_token()
            if valid_runner_token(token):
                break
        except FileNotFoundError:
            token = ""
        if not os.getenv("AI_RUNNER_AUTH_DIR"):
            break
        time.sleep(0.5)
    if not valid_runner_token(token):
        raise ValueError("AI_RUNNER_TOKEN에는 32자 이상의 전용 토큰이 필요합니다")
    gate = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass

        def authorized(self):
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
                self.send_error(401)
                return False
            return True

        def json(self, value):
            output = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(output)))
            self.end_headers()
            self.wfile.write(output)

        def do_GET(self):
            if self.path != "/status":
                self.send_error(404)
                return
            if self.authorized():
                import shutil

                self.json({"providers": {name: bool(shutil.which(name)) for name in PROVIDERS}})

        def do_POST(self):
            if self.path not in {"/extract", "/check", "/credentials"}:
                self.send_error(404)
                return
            if not self.authorized():
                return
            if not gate.acquire(blocking=False):
                self.send_error(503)
                return
            try:
                self.connection.settimeout(30)
                size = int(self.headers.get("Content-Length", "0"))
                limit = 8_000_000 if self.path == "/extract" else 8192
                if not 0 < size <= limit:
                    self.send_error(413)
                    return
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict) or body.get("provider") not in PROVIDERS:
                    self.send_error(400, "Unsupported AI provider")
                    return
                provider = body["provider"]
                if self.path == "/check":
                    self.json(check_provider(provider, home))
                    return
                if self.path == "/credentials":
                    key = body.get("key")
                    if (
                        provider != "claude"
                        or not isinstance(key, str)
                        or not 1 <= len(key) <= 4096
                        or any(not 33 <= ord(char) <= 126 for char in key)
                    ):
                        self.send_error(400, "Invalid API key")
                        return
                    atomic_write(home / "anthropic-api-key", key.encode())
                    self.json({"ok": True})
                    return
                request_timeout = body.get("timeout", timeout)
                if type(request_timeout) is not int or not 10 <= request_timeout <= 1800:
                    self.send_error(400, "Invalid timeout")
                    return
                model = body.get("model")
                if not isinstance(model, str) or not model.strip() or len(model) > 200:
                    self.send_error(400, "Select an AI model in service settings")
                    return
                ocr_text, data = "", None
                text_only = body.get("mode", "image") == "text"
                if body.get("mode", "image") not in {"image", "text"}:
                    raise ValueError("invalid mode")
                if provider == "agy" or text_only:
                    ocr_text = body.get("text", "")
                    if not isinstance(ocr_text, str) or not 1 <= len(ocr_text) <= 100_000:
                        raise ValueError("invalid OCR text")
                else:
                    data = base64.b64decode(body["image"], validate=True)
                    data = jpeg_bytes(load_image(data))
                categories = body["categories"]
                if not isinstance(categories, list) or len(categories) > 1000:
                    raise ValueError("invalid categories")
                options = {}
                if text_only:
                    reference = body.get("reference_date")
                    currency = body.get("currency")
                    annotation = body.get("annotation", False)
                    if (
                        not isinstance(reference, str)
                        or date.fromisoformat(reference).isoformat() != reference
                    ):
                        raise ValueError("invalid reference date")
                    if (
                        not isinstance(currency, str)
                        or len(currency) != 3
                        or not currency.isascii()
                        or not currency.isalpha()
                    ):
                        raise ValueError("invalid currency")
                    if type(annotation) is not bool or len(ocr_text) > 4096:
                        raise ValueError("invalid text metadata")
                    options = {
                        "text_only": True,
                        "reference_date": reference,
                        "currency": currency,
                        "annotation": annotation,
                    }
                result = run_cli(
                    provider, model, data, categories, home, request_timeout, ocr_text=ocr_text, **options
                )
                output = result.model_dump_json().encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                self.wfile.write(output)
            except Exception:
                self.send_error(502, "AI extraction failed")
            finally:
                gate.release()

    server = RunnerServer(("0.0.0.0", 8090), Handler)
    server.serve_forever()
