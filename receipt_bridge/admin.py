"""Small local admin server: stdlib HTTP + static assets, no frontend build or web framework."""

from __future__ import annotations

import hmac
import json
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from . import __version__
from .ai import runner_setup
from .auth import password_hash, password_matches
from .config import CREDENTIAL_FIELDS, Settings, configured, telegram_identity, valid_runner_token
from .ledger import RemoteError
from .models import Extraction
from .web_jobs import WebJobs, parse_upload

EDITABLE = {
    "timezone",
    "ledger_url",
    "allowed_users",
    "allowed_chats",
    "user_accounts",
    "chat_accounts",
    "ai_provider",
    "ai_model",
    "allow_external_ai",
    "ollama_url",
    "ai_runner_url",
    "ai_timeout",
    "max_download_mb",
    "max_attempts",
    "retry_seconds",
    "max_amount_minor",
    "auto_save",
    "auto_max_amount_minor",
    "auto_max_age_days",
    "ocr_languages",
}
STATIC = Path(__file__).with_name("static")


def normalize_credentials(values):
    if not isinstance(values, dict) or not values.keys() <= set(CREDENTIAL_FIELDS):
        raise ValueError("접속 키 항목을 확인하세요")
    actual_secrets = {}
    for name, value in values.items():
        if value is None:
            actual_secrets[name] = ""
        elif (
            not isinstance(value, str)
            or len(value) > 4096
            or any(ord(char) < 32 or ord(char) > 126 for char in value)
        ):
            raise ValueError("접속 키 형식과 길이를 확인하세요")
        elif value.strip():
            actual_secrets[name] = value.strip()
    return actual_secrets


def log_time_range(start, end, timezone):
    def parse(value):
        if not value:
            return None
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
            raise ValueError("시작·종료 일시는 YYYY-MM-DDTHH:mm 형식으로 입력하세요")
        try:
            return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(timezone))
        except ValueError:
            raise ValueError("시작·종료 일시가 올바른 날짜와 시간인지 확인하세요") from None

    first, last = parse(start), parse(end)
    if first and last and first > last:
        raise ValueError("시작 일시는 종료 일시보다 늦을 수 없습니다")
    # End minute is inclusive in the UI; SQL uses an exclusive upper bound.
    return (first.timestamp() if first else None, (last + timedelta(minutes=1)).timestamp() if last else None)


class AdminState:
    def __init__(self, base: Settings, store, demo=False):
        self.base, self.store, self.demo = base, store, demo
        self.lock = threading.RLock()
        self.config_lock = threading.RLock()
        self.upload_gate = threading.BoundedSemaphore(1)
        self.started = time.time()
        self.last_poll = None
        self.last_poll_error = None
        self.applied_revision = store.setting("ui_applied_revision", -1)
        applied = store.setting("ui_applied_settings")
        self.current = (
            Settings(**{**base.model_dump(), **store.credentials(applied=True), **applied})
            if applied is not None
            else self.effective()
        )

    def effective(self):
        overrides = self.store.setting("ui_settings", {})
        if not isinstance(overrides, dict) or not overrides.keys() <= EDITABLE:
            raise ValueError("저장된 화면 설정을 확인하세요")
        return Settings(**{**self.base.model_dump(), **self.store.credentials(), **overrides})

    def readiness(self, settings=None):
        settings = settings or self.current
        return settings.readiness()

    def missing_settings(self, settings):
        missing = []
        if not configured(settings.ledger_password):
            missing.append("가계부 연결 → 가계부 앱 비밀번호를 입력하세요.")
        if not configured(settings.telegram_token):
            missing.append("메신저 연결 · Telegram → BotFather에서 받은 봇 토큰을 입력하세요.")
        if not settings.allowed_users:
            missing.append("메신저 연결 · Telegram → 허용 사용자 ID에 Telegram 사람 번호를 입력하세요.")
        if not settings.allowed_chats:
            missing.append("메신저 연결 · Telegram → 허용 채팅 ID에 Telegram 대화방 번호를 입력하세요.")
        if not settings.user_accounts and not settings.chat_accounts:
            missing.append(
                "메신저 연결 · Telegram → 사용자별 또는 대화방별 저장 계좌를 'Telegram ID = 가계부 계좌 ID'로 입력하세요."
            )
        elif settings.allowed_users and settings.allowed_chats:
            for user in settings.allowed_users:
                if any(not settings.account_for(user, chat) for chat in settings.allowed_chats):
                    missing.append(
                        f"메신저 연결 · Telegram → 허용 사용자 {user}의 저장 계좌가 없습니다. 사용자별 계좌 또는 모든 허용 대화방의 계좌를 지정하세요."
                    )
        if not settings.ai_model.strip():
            missing.append("AI 분석 → 선택한 제공자의 모델 이름을 입력하세요.")
        if settings.ai_provider != "ollama" and not settings.allow_external_ai:
            missing.append("AI 분석 → 선택한 CLI를 사용하려면 외부 AI 전송 허용을 켜세요.")
        if settings.ai_provider != "ollama" and not valid_runner_token(
            settings.ai_runner_token.get_secret_value()
        ):
            missing.append(
                "AI 분석 → 분석 서비스의 통신 인증이 준비되지 않았습니다. 최신 Compose의 runner-auth 볼륨 연결을 확인하세요."
            )
        return missing

    def public_settings(self):
        settings = self.effective()
        return {name: getattr(settings, name) for name in sorted(EDITABLE)}

    def status(self):
        with self.lock:
            settings = self.effective()
            checks = self.readiness(settings)
            web_ready = checks["ledger"] and checks["ai"]
            missing = self.missing_settings(settings)
            telegram_missing = [item for item in missing if item.startswith("메신저")]
            return {
                "demo": self.demo,
                "checks": checks,
                "web_ready": web_ready,
                "telegram_ready": all(checks.values()),
                "missing": [item for item in missing if not item.startswith("메신저")]
                if settings.web_enabled
                else missing,
                "telegram_missing": telegram_missing,
                "ready": web_ready if settings.web_enabled else all(checks.values()),
                "paused": self.store.setting("paused", False),
                "started_at": self.started,
                "last_poll": self.last_poll,
                "poll_error": self.last_poll_error,
                "revision": self.store.setting("ui_revision", 0),
                "applied_revision": self.applied_revision,
            }

    def save(self, values):
        with self.config_lock, self.store.tx():
            return self._save(values)

    def _save(self, values):
        if not isinstance(values, dict) or not values.keys() <= EDITABLE | {"secrets"}:
            raise ValueError("변경할 수 없는 설정이 포함되어 있습니다")
        current = self.effective()
        changes = dict(values)
        secret_changes = changes.pop("secrets", {})
        actual_secrets = normalize_credentials(secret_changes)
        candidate = Settings(**{**current.model_dump(), **changes, **actual_secrets})
        self._validate_settings_change(candidate)
        with self.store.tx():
            merged = {key: getattr(candidate, key) for key in EDITABLE}
            self.store.set_credentials(actual_secrets)
            self.store.set_setting("ui_settings", merged)
            self.store.set_setting("ui_revision", self.store.setting("ui_revision", 0) + 1)
            self.store.log("info", "admin", "운영 설정을 저장했습니다")
        return self.public_settings()

    def _validate_settings_change(self, candidate):
        bot_id = telegram_identity(candidate.telegram_token)
        previous_bot = self.store.setting("telegram_bot_id", telegram_identity(self.current.telegram_token))
        if bot_id and previous_bot and bot_id != previous_bot and self.store.has_pending_messages():
            raise ValueError("남아 있는 작업·결과 안내를 마친 뒤 다른 텔레그램 봇으로 변경하세요")
        if candidate.ai_provider != "ollama" and not candidate.allow_external_ai:
            raise ValueError("외부 AI 사용을 먼저 허용하세요")
        if self.ledger_change_blocked(candidate):
            raise ValueError(
                "저장·첨부가 끝나지 않은 작업이 있어 가계부 주소·앱 비밀번호·시간대를 바꿀 수 없습니다"
            )

    def ledger_change_blocked(self, candidate, current=None):
        current = current or self.current
        location_changed = (
            current.ledger_url != candidate.ledger_url or current.timezone != candidate.timezone
        )
        key_changed = current.ledger_password != candidate.ledger_password
        return (location_changed and self.store.has_pending_transactions()) or (
            key_changed and self.store.has_pending_transactions(unposted_only=True)
        )

    def setup_required(self):
        return self.store.setting("admin_auth") is None

    def setup_admin(self, password, confirmation):
        if password != confirmation:
            raise ValueError("비밀번호 확인이 일치하지 않습니다")
        record = password_hash(password)
        with self.store.tx():
            if not self.setup_required():
                return False
            self.store.set_setting("admin_auth", record)
            self.store.log("info", "admin", "초기 관리자 비밀번호 설정 완료")
        return True

    def credential_status(self):
        settings = self.effective()
        return {name: configured(getattr(settings, name)) for name in CREDENTIAL_FIELDS}


def make_server(state: AdminState, host=None, port=None):
    sessions, failures = {}, defaultdict(deque)
    auth_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ReceiptBridge"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass  # Request bodies, URLs, cookies and credentials never go to logs.

        def send_bytes(self, status, data, content_type="application/json; charset=utf-8", cookie=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; "
                "style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
            )
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def json(self, status, data, cookie=None):
            self.send_bytes(status, json.dumps(data, ensure_ascii=False).encode(), cookie=cookie)

        def session(self):
            try:
                cookie = SimpleCookie(self.headers.get("Cookie", ""))
                token = cookie["rb_session"].value if "rb_session" in cookie else ""
            except Exception:
                return None
            with auth_lock:
                session = sessions.get(token)
                if session and session["expires"] > time.time():
                    return token, session
                sessions.pop(token, None)
            return None

        def serve_job_image(self, job, kind):
            target = Path(job[kind]) if job[kind] else None
            root = (state.base.data_dir / "receipts").resolve()
            if not target or not target.resolve().is_relative_to(root) or not target.is_file():
                return self.json(404, {"error": "사진이 없습니다"})
            if kind == "original":
                # Never serve arbitrary received bytes as browser content.
                from .images import jpeg_bytes, load_image

                image = jpeg_bytes(load_image(target.read_bytes()))
            else:
                image = target.read_bytes()
            return self.send_bytes(200, image, "image/jpeg")

        def job_detail(self, job):
            fields = (
                "id",
                "state",
                "revision",
                "account",
                "attempts",
                "error",
                "created_at",
                "updated_at",
                "posting_id",
                "receipt_id",
                "image_warnings",
                "input_kind",
                "input_text",
                "reference_date",
                "batch_size",
                "part",
                "adapter",
            )
            result = {key: job[key] for key in fields}
            result["extraction"] = json.loads(job["extraction"]) if job["extraction"] else None
            result["has_image"], result["has_original"] = (
                bool(job["image"]),
                bool(job["original"]),
            )
            result["events"] = state.store.job_events(job["id"])
            result["warnings"] = (
                Extraction.model_validate_json(job["extraction"]).warnings if job["extraction"] else []
            )
            result["duplicates"] = state.store.duplicates(job["id"], job["fingerprint"], job["image_hash"])
            return result

        def do_GET(self):
            try:
                path = urlsplit(self.path).path
                files = {
                    "/": ("index.html", "text/html; charset=utf-8"),
                    "/settings.js": ("settings.js", "application/javascript; charset=utf-8"),
                    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
                    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
                    "/favicon.ico": ("favicon.svg", "image/svg+xml"),
                    "/style.css": ("style.css", "text/css; charset=utf-8"),
                }
                if path in {"/dashboard", "/jobs", "/logs", "/settings", "/upload"}:
                    path = "/"
                if path in files:
                    name, mime = files[path]
                    body = (STATIC / name).read_bytes()
                    if name == "index.html":
                        body = body.replace(b"__APP_VERSION__", __version__.encode())
                    return self.send_bytes(200, body, mime)
                session = self.session()
                if path == "/api/session":
                    return self.json(
                        200,
                        {
                            "authenticated": bool(session),
                            "csrf": session[1]["csrf"] if session else None,
                            "setup_required": state.setup_required(),
                        },
                    )
                if not session:
                    return self.json(401, {"error": "로그인이 필요합니다"})
                query = parse_qs(urlsplit(self.path).query)

                def arg(key, default=""):
                    return query.get(key, [default])[0][:200]

                page = max(1, min(100000, int(arg("page", "1"))))
                if path == "/api/overview":
                    timezone = ZoneInfo(state.effective().timezone)
                    today = datetime.now(timezone).replace(hour=0, minute=0, second=0, microsecond=0)
                    return self.json(
                        200,
                        {
                            "status": state.status(),
                            "summary": state.store.dashboard(today.timestamp()),
                            "recent": state.store.browse_jobs(),
                            "settings": state.public_settings(),
                        },
                    )
                if path == "/api/accounts":
                    return self.json(
                        200,
                        {
                            "accounts": WebJobs(state.effective(), state.store).accounts(),
                            "status": state.status(),
                        },
                    )
                if path == "/api/jobs":
                    return self.json(200, state.store.browse_jobs(arg("state"), arg("search"), page))
                if path == "/api/logs":
                    timezone = state.effective().timezone
                    first, last = log_time_range(arg("from"), arg("to"), timezone)
                    result = state.store.browse_logs(
                        arg("kind", "service"), arg("level"), arg("search"), page, start_at=first, end_at=last
                    )
                    return self.json(200, {**result, "timezone": timezone})
                if path == "/api/settings":
                    return self.json(
                        200,
                        {
                            "settings": state.public_settings(),
                            "status": state.status(),
                            "secrets": state.credential_status(),
                        },
                    )
                if path.startswith("/api/jobs/"):
                    parts = path.strip("/").split("/")
                    job = state.store.get(parts[2]) if len(parts) >= 3 else None
                    if not job:
                        return self.json(404, {"error": "작업을 찾지 못했습니다"})
                    if len(parts) == 4 and parts[3] == "categories":
                        return self.json(
                            200, {"categories": WebJobs(state.effective(), state.store).categories(job)}
                        )
                    if len(parts) == 4 and parts[3] in {"original", "image"}:
                        return self.serve_job_image(job, parts[3])
                    if len(parts) == 3:
                        return self.json(200, self.job_detail(job))
                self.json(404, {"error": "없는 경로입니다"})
            except ValueError as exc:
                self.json(
                    400,
                    {
                        "error": str(exc)
                        if type(exc) is ValueError and str(exc).startswith(("시작", "종료"))
                        else "요청 값을 확인하세요"
                    },
                )
            except RemoteError:
                self.json(502, {"error": "가계부 연결·앱 비밀번호·계좌 권한을 확인하세요"})
            except KeyError:
                self.json(400, {"error": "요청 값을 확인하세요"})
            except Exception:
                self.json(500, {"error": "화면 정보를 읽지 못했습니다"})

        def login(self, path, data):
            if self.headers.get("X-Receipt-Bridge") != "1":
                return self.json(403, {"error": "올바른 로그인 요청이 아닙니다"})
            address = self.client_address[0]
            with auth_lock:
                now = time.time()
                while failures[address] and failures[address][0] < now - 60:
                    failures[address].popleft()
                if len(failures[address]) >= 5:
                    return self.json(429, {"error": "1분 뒤 다시 로그인하세요"})
                entered = data.get("password", "")
                if path == "/api/setup":
                    if not state.setup_required():
                        return self.json(409, {"error": "초기 설정이 이미 완료됐습니다. 로그인하세요"})
                    failures[address].append(now)
                    if not state.setup_admin(entered, data.get("confirmation")):
                        return self.json(409, {"error": "초기 설정이 이미 완료됐습니다. 로그인하세요"})
                elif state.setup_required():
                    return self.json(409, {"error": "먼저 초기 관리자 비밀번호를 설정하세요"})
                elif not password_matches(entered, state.store.setting("admin_auth")):
                    failures[address].append(now)
                    state.store.log("warning", "admin", "관리 화면 로그인 실패")
                    return self.json(401, {"error": "비밀번호를 확인하세요"})
                for key in list(sessions):
                    if sessions[key]["expires"] <= now:
                        del sessions[key]
                if len(sessions) >= 32:
                    del sessions[next(iter(sessions))]
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                sessions[token] = {"csrf": csrf, "expires": now + 12 * 3600}
                failures.pop(address, None)
            secure = "; Secure" if state.base.web_secure_cookie else ""
            state.store.log("info", "admin", "관리 화면 로그인")
            return self.json(
                200,
                {"csrf": csrf},
                f"rb_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200{secure}",
            )

        def upload(self):
            if self.headers.get("Content-Type", "").split(";")[0] != "multipart/form-data":
                return self.json(415, {"error": "파일 업로드 형식이 필요합니다"})
            settings = state.effective()
            length = int(self.headers.get("Content-Length", "0"))
            if (
                self.headers.get("Transfer-Encoding")
                or not 0 < length <= settings.max_download_mb * 1024 * 1024 + 20000
            ):
                return self.json(413, {"error": "사진 수신 한도를 확인하세요"})
            if not state.upload_gate.acquire(blocking=False):
                return self.json(429, {"error": "다른 사진을 업로드 중입니다. 잠시 후 다시 시도하세요"})
            try:
                self.connection.settimeout(30)
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("사진 업로드가 완료되지 않았습니다")
                fields = parse_upload(self.headers["Content-Type"], body)
                # Serialize with credential changes so an accepted upload uses one config snapshot.
                with state.config_lock:
                    job = WebJobs(state.effective(), state.store).upload(
                        self.headers.get("Idempotency-Key", ""),
                        fields["file"],
                        fields["account"],
                        fields.get("caption", ""),
                    )
                return self.json(200, {"id": job["id"], "state": job["state"]})
            finally:
                state.upload_gate.release()

        def do_POST(self):
            try:
                origin = self.headers.get("Origin")
                if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                    return self.json(403, {"error": "다른 사이트의 요청은 허용하지 않습니다"})
                if self.headers.get("Sec-Fetch-Site") == "cross-site":
                    return self.json(403, {"error": "다른 사이트의 요청은 허용하지 않습니다"})
                path = urlsplit(self.path).path
                if path == "/api/uploads":
                    session = self.session()
                    if not session:
                        return self.json(401, {"error": "로그인이 필요합니다"})
                    if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session[1]["csrf"]):
                        return self.json(403, {"error": "화면을 새로고침하고 다시 시도하세요"})
                    return self.upload()
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self.json(415, {"error": "JSON 요청이 필요합니다"})
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32000:
                    return self.json(413, {"error": "요청 크기를 확인하세요"})
                self.connection.settimeout(10)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    return self.json(400, {"error": "JSON 객체가 필요합니다"})
                path = urlsplit(self.path).path
                if path in {"/api/login", "/api/setup"}:
                    return self.login(path, data)
                session = self.session()
                if not session:
                    return self.json(401, {"error": "로그인이 필요합니다"})
                if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session[1]["csrf"]):
                    return self.json(403, {"error": "화면을 새로고침하고 다시 시도하세요"})
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "control":
                    with state.config_lock:
                        job = WebJobs(state.effective(), state.store).control(parts[2], data)
                        return self.json(200, self.job_detail(job))
                if path == "/api/logout":
                    with auth_lock:
                        sessions.pop(session[0], None)
                    return self.json(
                        200, {"ok": True}, "rb_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
                    )
                if path == "/api/ai/check":
                    return self.json(200, runner_setup(state.effective(), "check"))
                if path == "/api/ai/credentials":
                    runner_setup(state.effective(), "credentials", data.get("key"))
                    return self.json(200, {"ok": True})
                if path == "/api/settings/reveal-secret":
                    key = data.get("key")
                    if not isinstance(key, str) or key not in CREDENTIAL_FIELDS:
                        return self.json(400, {"error": "확인할 접속 키를 선택하세요"})
                    return self.json(200, {"value": getattr(state.effective(), key).get_secret_value()})
                if path == "/api/settings":
                    return self.json(200, {"settings": state.save(data)})
                if path == "/api/control":
                    if type(data.get("paused")) is not bool:
                        raise ValueError("일시정지 상태를 확인하세요")
                    state.store.set_setting("paused", data["paused"])
                    state.store.log("info", "admin", "처리 일시정지" if data["paused"] else "처리 재개")
                    return self.json(200, state.status())
                self.json(404, {"error": "없는 경로입니다"})
            except RemoteError:
                self.json(502, {"error": "가계부 연결·앱 비밀번호·계좌 권한을 확인하세요"})
            except ValidationError as exc:
                fields = ", ".join(
                    ".".join(map(str, error["loc"])) for error in exc.errors(include_input=False)
                )
                self.json(400, {"error": "설정 값의 형식·범위를 확인하세요: " + fields})
            except ValueError as exc:
                self.json(400, {"error": str(exc) if type(exc) is ValueError else "요청 형식을 확인하세요"})
            except Exception:
                self.json(500, {"error": "설정을 저장하지 못했습니다"})

    server = ThreadingHTTPServer(
        (host or state.base.web_host, state.base.web_port if port is None else port), Handler
    )
    server.daemon_threads = True
    return server
