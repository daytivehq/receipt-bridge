"""Private CLI inference server. Run in a separate container with no ledger/bot credentials."""

from __future__ import annotations

import base64
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .ai import run_cli
from .config import valid_runner_token
from .images import jpeg_bytes, load_image


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
    provider = os.environ.get("AI_PROVIDER", "codex")
    home = Path(os.environ.get("AI_HOME", "/ai-home"))
    timeout = int(os.environ.get("AI_TIMEOUT", "180"))
    if provider not in {"codex", "claude", "agy"}:
        raise ValueError("AI runner의 provider를 설정하세요")
    token_path = os.getenv("AI_RUNNER_TOKEN_FILE")
    token = Path(token_path).read_text().strip() if token_path else os.getenv("AI_RUNNER_TOKEN", "")
    if not valid_runner_token(token):
        raise ValueError("AI_RUNNER_TOKEN에는 32자 이상의 전용 토큰이 필요합니다")
    gate = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass

        def do_POST(self):
            if self.path != "/extract":
                self.send_error(404)
                return
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
                self.send_error(401)
                return
            if not gate.acquire(blocking=False):
                self.send_error(503)
                return
            try:
                self.connection.settimeout(30)
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8_000_000:
                    self.send_error(413)
                    return
                body = json.loads(self.rfile.read(size))
                if body.get("provider") != provider:
                    self.send_error(409, "Configured AI provider does not match")
                    return
                model = body.get("model")
                if not isinstance(model, str) or not model.strip() or len(model) > 200:
                    self.send_error(400, "Select an AI model in service settings")
                    return
                ocr_text, data = "", None
                if provider == "agy":
                    ocr_text = body.get("text", "")
                    if not isinstance(ocr_text, str) or not 1 <= len(ocr_text) <= 100_000:
                        raise ValueError("invalid OCR text")
                else:
                    data = base64.b64decode(body["image"], validate=True)
                    data = jpeg_bytes(load_image(data))
                categories = body["categories"]
                if not isinstance(categories, list) or len(categories) > 1000:
                    raise ValueError("invalid categories")
                result = run_cli(provider, model, data, categories, home, timeout, ocr_text=ocr_text)
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
