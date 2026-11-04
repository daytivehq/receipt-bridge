import io
import json
from http.client import HTTPResponse

import pytest

from receipt_bridge.admin import AdminState, make_server
from receipt_bridge.store import Store
from tests.fakes import photo_update


class Socket:
    def __init__(self, data):
        self.input = io.BytesIO(data)
        self.output = bytearray()

    def makefile(self, *args, **kwargs):
        return self.input

    def sendall(self, data):
        self.output.extend(data)

    def settimeout(self, timeout):
        pass


@pytest.fixture
def admin(rig):
    service, store, _, _ = rig
    settings = service.settings.model_copy()
    state = AdminState(settings, store)
    state.setup_admin("TEST_ADMIN_PASSWORD", "TEST_ADMIN_PASSWORD")
    server = make_server(state, port=0)
    yield state, server
    server.server_close()


def request(server, path, body=None, headers=None):
    method = "GET" if body is None else "POST"
    data = json.dumps(body).encode() if body is not None else b""
    all_headers = {
        "Host": "localhost",
        "Content-Length": str(len(data)),
        "Content-Type": "application/json",
        **(headers or {}),
    }
    wire = f"{method} {path} HTTP/1.0\r\n".encode()
    wire += "".join(f"{key}: {value}\r\n" for key, value in all_headers.items()).encode() + b"\r\n" + data
    socket = Socket(wire)
    server.RequestHandlerClass(socket, ("127.0.0.1", 12345), server)
    result = HTTPResponse(Socket(bytes(socket.output)))
    result.begin()
    raw = result.read()
    return (
        result.status,
        result.headers,
        json.loads(raw) if "application/json" in result.headers.get("Content-Type", "") else raw,
    )


def login(server):
    status, headers, body = request(
        server, "/api/login", {"password": "TEST_ADMIN_PASSWORD"}, {"X-Receipt-Bridge": "1"}
    )
    assert status == 200
    return {"Cookie": headers["Set-Cookie"].split(";")[0], "X-CSRF-Token": body["csrf"]}


def test_admin_assets_public_data_requires_login_and_security_headers(admin):
    _, server = admin
    status, headers, body = request(server, "/")
    assert status == 200 and "운영 관리".encode() in body
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"
    for path in ("/api/overview", "/api/jobs", "/api/settings", "/api/logs", "/api/jobs/anything/image"):
        assert request(server, path)[0] == 401
    assert request(server, "/app.js")[0] == 200
    assert request(server, "/settings.js")[0] == 200
    assert request(server, "/style.css")[0] == 200


def test_login_csrf_origin_logout_and_rate_limiting(admin):
    _, server = admin
    assert request(server, "/api/login", {"password": "TEST_ADMIN_PASSWORD"})[0] == 403
    auth = login(server)
    assert request(server, "/api/control", {"paused": True}, {"Cookie": auth["Cookie"]})[0] == 403
    assert (
        request(server, "/api/control", {"paused": True}, {**auth, "Origin": "https://evil.invalid"})[0]
        == 403
    )
    assert request(server, "/api/control", {"paused": True}, auth)[0] == 200
    assert request(server, "/api/session", headers=auth)[2]["authenticated"]
    assert request(server, "/api/logout", {}, auth)[0] == 200
    assert request(server, "/api/jobs", headers=auth)[0] == 401
    for _ in range(5):
        assert request(server, "/api/login", {"password": "WRONG"}, {"X-Receipt-Bridge": "1"})[0] == 401
    assert (
        request(server, "/api/login", {"password": "TEST_ADMIN_PASSWORD"}, {"X-Receipt-Bridge": "1"})[0]
        == 429
    )


def test_no_secret_values_in_admin_responses_or_logs(admin):
    state, server = admin
    auth = login(server)
    status, _, data = request(server, "/api/overview", headers=auth)
    assert status == 200
    serialized = json.dumps(data)
    assert "TEST_ADMIN_PASSWORD" not in serialized
    assert "telegram_token" not in serialized and "ledger_password" not in serialized
    assert "admin_password" not in serialized
    assert request(server, "/api/settings", {"ledger_password": "NO_LEAK"}, auth)[0] == 400
    assert "NO_LEAK" not in json.dumps(request(server, "/api/logs", headers=auth)[2])
    assert request(server, "/api/settings", {"ai_timeout": "INVALID_SECRET_TEST"}, auth)[0] == 400
    assert "INVALID_SECRET_TEST" not in json.dumps(request(server, "/api/logs", headers=auth)[2])
    assert state.store.setting("ui_settings") is None


def test_settings_persist_after_reopen_without_changing_base_config(admin):
    state, server = admin
    auth = login(server)
    assert request(server, "/api/settings", {"ai_model": "new-vision", "retry_seconds": 12}, auth)[0] == 200
    assert state.base.ai_model == ""
    reopened = Store(state.base.data_dir / "jobs.sqlite3")
    assert AdminState(state.base, reopened).effective().ai_model == "new-vision"
    assert reopened.setting("ui_revision") == 1
    reopened.close()
    assert (
        request(server, "/api/settings", {"ai_provider": "codex", "allow_external_ai": False}, auth)[0] == 400
    )


def test_frozen_jobs_block_ledger_change_and_settings_snapshot_survives_restart(admin, rig):
    state, server = admin
    service, store, _, _ = rig
    auth = login(server)
    store.ingest([photo_update()], service.authorized_update)
    service.tick()
    service.confirm(store.pending(1, 1)[0])
    assert request(server, "/api/settings", {"ledger_url": "http://new.invalid/api/v1"}, auth)[0] == 400
    assert request(server, "/api/settings", {"timezone": "UTC"}, auth)[0] == 400
    store.set_setting("ui_applied_settings", {"ledger_url": state.base.ledger_url})
    store.set_setting("ui_settings", {"ledger_url": "http://requested.invalid/api/v1"})
    recreated = AdminState(state.base, store)
    assert recreated.current.ledger_url == state.base.ledger_url
    assert recreated.effective().ledger_url == "http://requested.invalid/api/v1"


def test_pause_preserves_jobs_and_resumes_processing(admin, rig):
    _, server = admin
    service, store, messenger, api = rig
    auth = login(server)
    request(server, "/api/control", {"paused": True}, auth)
    store.ingest([photo_update()], service.authorized_update)
    service.tick()
    assert store.pending(1, 1)[0]["state"] == "received" and messenger.downloads == 0
    request(server, "/api/control", {"paused": False}, auth)
    service.tick()
    assert store.pending(1, 1)[0]["state"] == "waiting" and not api.posts


def test_job_detail_photos_logs_and_pagination(admin, rig):
    state, server = admin
    service, store, _, _ = rig
    auth = login(server)
    store.ingest([photo_update()], service.authorized_update)
    service.tick()
    job = store.pending(1, 1)[0]
    for index in range(25):
        store.create_job(1, 1, index + 100, "TEST", "test-account")
    result = request(server, "/api/jobs?page=2", headers=auth)[2]
    assert result["total"] == 26 and len(result["items"]) == 6
    assert (
        request(server, "/api/jobs?state=waiting&search=%ED%85%8C%EC%8A%A4%ED%8A%B8", headers=auth)[2][
            "total"
        ]
        == 1
    )
    detail = request(server, "/api/jobs/" + job["id"], headers=auth)[2]
    assert detail["has_original"] and detail["events"][0]["state"] == "received"
    assert "request_key" not in detail and "payload" not in detail
    for kind in ("original", "image"):
        status, headers, body = request(server, f"/api/jobs/{job['id']}/{kind}", headers=auth)
        assert status == 200 and headers["Content-Type"] == "image/jpeg"
        assert body.startswith(b"\xff\xd8")
    store.update(job["id"], image="/etc/passwd")
    assert request(server, f"/api/jobs/{job['id']}/image", headers=auth)[0] == 404
    assert request(server, "/api/logs?kind=events&search=" + job["id"], headers=auth)[2]["total"] == 3
    assert request(server, "/api/jobs?page=invalid", headers=auth)[0] == 400


def test_first_setup_is_once_only_and_password_is_hashed(rig):
    from receipt_bridge.auth import password_matches

    service, store, _, _ = rig
    state = AdminState(service.settings, store)
    server = make_server(state, port=0)
    try:
        assert request(server, "/api/session")[2]["setup_required"] is True
        assert (
            request(server, "/api/login", {"password": "old-env-password"}, {"X-Receipt-Bridge": "1"})[0]
            == 409
        )
        headers = {"X-Receipt-Bridge": "1"}
        assert (
            request(server, "/api/setup", {"password": "short", "confirmation": "short"}, headers)[0] == 400
        )
        assert (
            request(
                server, "/api/setup", {"password": "NEW_ADMIN_PASSWORD", "confirmation": "different"}, headers
            )[0]
            == 400
        )
        status, cookie, data = request(
            server,
            "/api/setup",
            {"password": "NEW_ADMIN_PASSWORD", "confirmation": "NEW_ADMIN_PASSWORD"},
            headers,
        )
        assert status == 200 and data["csrf"]
        assert "HttpOnly" in cookie["Set-Cookie"]
        assert request(server, "/api/session")[2]["setup_required"] is False
        assert (
            request(
                server,
                "/api/setup",
                {"password": "ATTACKER_PASSWORD", "confirmation": "ATTACKER_PASSWORD"},
                headers,
            )[0]
            == 409
        )
        record = store.setting("admin_auth")
        assert "NEW_ADMIN_PASSWORD" not in json.dumps(record)
        assert password_matches("NEW_ADMIN_PASSWORD", record)
        assert not password_matches("ATTACKER_PASSWORD", record)
        reopened = Store(service.settings.data_dir / "jobs.sqlite3")
        assert not AdminState(service.settings, reopened).setup_required()
        assert password_matches("NEW_ADMIN_PASSWORD", reopened.setting("admin_auth"))
        reopened.close()
    finally:
        server.server_close()


def test_concurrent_initial_setup_only_one_password_wins(rig):
    from concurrent.futures import ThreadPoolExecutor

    service, store, _, _ = rig
    first = AdminState(service.settings, store)
    second_store = Store(service.settings.data_dir / "jobs.sqlite3")
    second = AdminState(service.settings, second_store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda args: args[0].setup_admin(args[1], args[1]),
                [(first, "FIRST_ADMIN_PASSWORD"), (second, "SECOND_ADMIN_PASSWORD")],
            )
        )
    assert sorted(results) == [False, True]
    second_store.close()


def test_connection_keys_save_keep_clear_and_never_echo(admin):
    state, server = admin
    auth = login(server)
    secrets = {"telegram_token": "123456789:TEST_ONLY_BOT_TOKEN", "ledger_password": "TEST_ONLY_APP_PASSWORD"}
    status, _, body = request(server, "/api/settings", {"secrets": secrets}, auth)
    assert status == 200
    assert not any(value in json.dumps(body) for value in secrets.values())
    assert state.effective().telegram_token.get_secret_value() == secrets["telegram_token"]
    assert state.effective().ledger_password.get_secret_value() == secrets["ledger_password"]
    data = request(server, "/api/settings", headers=auth)[2]
    assert data["secrets"] == {"telegram_token": True, "ledger_password": True}
    assert not any(value in json.dumps(data) for value in secrets.values())
    assert (
        request(server, "/api/settings", {"secrets": {"telegram_token": "", "ledger_password": ""}}, auth)[0]
        == 200
    )
    assert state.store.credentials() == secrets
    assert not any(
        value in json.dumps(request(server, "/api/logs", headers=auth)[2]) for value in secrets.values()
    )
    assert request(server, "/api/settings", {"secrets": {"telegram_token": None}}, auth)[0] == 200
    assert state.effective().telegram_token.get_secret_value() == ""
    from pydantic import SecretStr

    state.base.telegram_token = SecretStr("ENV_VALUE_MUST_NOT_REAPPEAR")
    assert state.effective().telegram_token.get_secret_value() == ""
    assert state.base.data_dir.joinpath("jobs.sqlite3").stat().st_mode & 0o777 == 0o600
    reopened = Store(state.base.data_dir / "jobs.sqlite3")
    assert (
        AdminState(state.base, reopened).effective().ledger_password.get_secret_value()
        == secrets["ledger_password"]
    )
    reopened.close()


def test_ledger_key_change_blocked_for_uncertain_transaction(admin, rig):
    _, server = admin
    service, store, _, _ = rig
    auth = login(server)
    store.ingest([photo_update()], service.authorized_update)
    service.tick()
    service.confirm(store.pending(1, 1)[0])
    assert request(server, "/api/settings", {"secrets": {"ledger_password": "NEW_API_KEY"}}, auth)[0] == 400
    assert not store.credentials()


def test_antigravity_option_requires_explicit_external_permission(admin):
    state, server = admin
    auth = login(server)
    assert request(server, "/api/settings", {"ai_provider": "agy"}, auth)[0] == 400
    assert (
        request(
            server,
            "/api/settings",
            {"ai_provider": "agy", "allow_external_ai": True, "ai_model": "test-model"},
            auth,
        )[0]
        == 200
    )
    assert state.effective().ai_provider == "agy"


@pytest.mark.parametrize("kind", ["service", "events"])
def test_logs_filter_by_service_timezone_and_include_the_whole_end_minute(admin, kind):
    from datetime import datetime
    from urllib.parse import urlencode

    state, server = admin
    auth = login(server)
    start = datetime.fromisoformat("2026-11-02T15:11:00+00:00").timestamp()
    values = [start - 0.001, start, start + 59.999, start + 60]
    store = state.store
    if kind == "service":
        store.db.execute("DELETE FROM service_logs")
        for value in values:
            store.db.execute(
                "INSERT INTO service_logs(at,level,source,message,job_id) VALUES(?,'error','worker','테스트 실패','range-job')",
                (value,),
            )
    else:
        for value in values:
            store.db.execute("INSERT INTO events(job_id,state,at) VALUES('range-job','waiting',?)", (value,))
    query = {
        "kind": kind,
        "from": "2026-11-03T00:11",
        "to": "2026-11-03T00:11",
        "search": "실패" if kind == "service" else "waiting",
    }
    if kind == "service":
        query["level"] = "error"
    status, _, data = request(server, "/api/logs?" + urlencode(query), headers=auth)
    assert status == 200 and data["total"] == 2
    assert data["timezone"] == "Asia/Seoul"
    assert {row["at"] for row in data["items"]} == {start, start + 59.999}
    query.pop("to")
    assert request(server, "/api/logs?" + urlencode(query), headers=auth)[2]["total"] == 3
    query.pop("from")
    query["to"] = "2026-11-03T00:11"
    assert request(server, "/api/logs?" + urlencode(query), headers=auth)[2]["total"] == 3
    state.base.timezone = "UTC"
    query.update({"from": "2026-11-02T15:11", "to": "2026-11-02T15:11"})
    assert request(server, "/api/logs?" + urlencode(query), headers=auth)[2]["total"] == 2


@pytest.mark.parametrize(
    "query",
    [
        "from=2026-11-03T00%3A12&to=2026-11-03T00%3A11",
        "from=2026-02-30T00%3A11",
        "to=not-a-date",
        "from=2026-11-03",
    ],
)
def test_logs_reject_invalid_or_reversed_time_ranges(admin, query):
    _, server = admin
    auth = login(server)
    status, _, body = request(server, "/api/logs?" + query, headers=auth)
    assert status == 400
    assert "시작" in body["error"]


def test_logs_pagination_and_content_search_use_the_same_time_filter(admin):
    from datetime import datetime
    from urllib.parse import urlencode

    state, server = admin
    auth = login(server)
    state.store.db.execute("DELETE FROM service_logs")
    first = datetime.fromisoformat("2026-11-02T15:11:00+00:00").timestamp()
    for index in range(60):
        state.store.db.execute(
            "INSERT INTO service_logs(at,level,source,message) VALUES(?,'info','telegram','연결 복구')",
            (first + index,),
        )
    state.store.db.execute(
        "INSERT INTO service_logs(at,level,source,message) VALUES(?,'info','telegram','범위 밖')",
        (first + 60,),
    )
    query = urlencode({"from": "2026-11-03T00:11", "to": "2026-11-03T00:11", "search": "연결", "page": 2})
    result = request(server, "/api/logs?" + query, headers=auth)[2]
    assert result["total"] == 60 and len(result["items"]) == 10
    assert all(first <= row["at"] < first + 60 for row in result["items"])


def test_setup_guidance_lists_each_missing_field_without_exposing_secrets(admin):
    state, server = admin
    from receipt_bridge.config import Settings

    # A first startup may be incomplete; saving a CLI provider without consent is rejected.
    state.base = Settings(
        **{
            **state.base.model_dump(),
            "telegram_token": "",
            "ledger_password": "",
            "allowed_users": [],
            "allowed_chats": [],
            "user_accounts": {},
            "chat_accounts": {},
            "ai_provider": "agy",
            "ai_model": "",
            "allow_external_ai": False,
        }
    )
    result = request(server, "/api/settings", headers=login(server))[2]["status"]
    assert not result["ready"]
    assert len(result["missing"]) == 7
    text = " ".join(result["missing"])
    for label in ("앱 비밀번호", "봇 토큰", "사용자 ID", "채팅 ID", "저장 계좌", "모델 이름", "외부 AI"):
        assert label in text
    state.save(
        {
            "secrets": {"telegram_token": "123:TEST_ONLY_TOKEN", "ledger_password": "TEST_ONLY_PASSWORD"},
            "allowed_users": [1],
            "allowed_chats": [1],
            "user_accounts": {"1": "test-account"},
            "ai_model": "test-model",
            "allow_external_ai": True,
        }
    )
    result = request(server, "/api/settings", headers=login(server))[2]["status"]
    assert result["ready"] and result["missing"] == []
    assert "TEST_ONLY" not in json.dumps(result)


def test_favicon_is_served_without_login(admin):
    _, server = admin
    status, headers, body = request(server, "/favicon.svg")
    assert status == 200
    assert headers["Content-Type"] == "image/svg+xml"
    assert b"<svg" in body


def test_setup_guidance_finds_a_mapping_for_the_wrong_telegram_user(admin):
    state, _ = admin
    settings = state.current.model_copy(
        update={
            "allowed_users": [42],
            "allowed_chats": [42],
            "user_accounts": {"99": "test-account"},
            "chat_accounts": {},
        }
    )
    assert not state.readiness(settings)["account"]
    assert any("허용 사용자 42" in item for item in state.missing_settings(settings))
    settings.chat_accounts = {"42": "test-account"}
    assert state.readiness(settings)["account"]
    assert not any("허용 사용자 42" in item for item in state.missing_settings(settings))


def test_secret_reveal_requires_authenticated_explicit_csrf_request_and_is_not_logged(admin):
    state, server = admin
    path = "/api/settings/reveal-secret"
    state.save({"secrets": {"telegram_token": "123:TEST_REVEAL", "ledger_password": "TEST_LEDGER_REVEAL"}})
    assert request(server, path, {"key": "telegram_token"})[0] == 401
    auth = login(server)
    assert request(server, path, {"key": "telegram_token"}, {"Cookie": auth["Cookie"]})[0] == 403
    assert (
        request(server, path, {"key": "telegram_token"}, {**auth, "Origin": "https://evil.invalid"})[0] == 403
    )
    assert request(server, path, {"key": "admin_auth"}, auth)[0] == 400
    assert request(server, path, {"key": []}, auth)[0] == 400
    for key, value in (("telegram_token", "123:TEST_REVEAL"), ("ledger_password", "TEST_LEDGER_REVEAL")):
        code, headers, result = request(server, path, {"key": key}, auth)
        assert code == 200 and result == {"value": value}
        assert headers["Cache-Control"] == "no-store"
        assert value not in json.dumps(request(server, "/api/settings", headers=auth)[2])
        assert value not in json.dumps(request(server, "/api/logs", headers=auth)[2])


@pytest.mark.parametrize("path", ["/", "/dashboard", "/jobs", "/logs", "/settings"])
def test_page_deep_links_have_release_version_and_keep_api_private(admin, path):
    from receipt_bridge import __version__

    _, server = admin
    code, _, body = request(server, path)
    assert code == 200 and b"__APP_VERSION__" not in body
    assert __version__.encode() in body
    assert request(server, "/api/settings")[0] == 401
