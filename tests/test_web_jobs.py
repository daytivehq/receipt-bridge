import hashlib
import json
from http.client import HTTPResponse
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from receipt_bridge.admin import AdminState, make_server
from receipt_bridge.ledger import Ledger
from receipt_bridge.web_jobs import WebJobs, parse_upload
from tests.fakes import sample_image
from tests.test_admin import Socket, login, request


@pytest.fixture
def web(rig, monkeypatch):
    from receipt_bridge import web_jobs

    service, store, _, api = rig
    settings = service.settings
    settings.web_enabled = True
    settings.ledger_password = SecretStr("TEST_ONLY")
    settings.ai_model = "test-vision"
    settings.telegram_token = SecretStr("")
    settings.allowed_users = []
    settings.allowed_chats = []
    settings.user_accounts = {}
    monkeypatch.setattr(
        web_jobs,
        "Ledger",
        lambda url, password: Ledger("http://mock.invalid/api/v1", password, httpx.MockTransport(api)),
    )
    state = AdminState(settings, store)
    state.setup_admin("TEST_ADMIN_PASSWORD", "TEST_ADMIN_PASSWORD")
    server = make_server(state, port=0)
    try:
        yield WebJobs(settings, store), state, server, service, api
    finally:
        server.server_close()


def multipart(data=None, account="test-account", caption="", extra=b""):
    boundary = "TEST_RECEIPT_BOUNDARY"
    body = b""
    for name, value in (("account", account), ("caption", caption)):
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="../../UNTRUSTED.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
    body += (sample_image() if data is None else data) + b"\r\n" + extra
    body += f"--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", body


def upload_request(server, headers=None, data=None, key="TEST_UPLOAD_KEY_0001", overrides=None):
    content_type, body = multipart(data)
    all_headers = {
        "Host": "localhost",
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        "Idempotency-Key": key,
        **(headers or {}),
        **(overrides or {}),
    }
    wire = (
        b"POST /api/uploads HTTP/1.0\r\n"
        + "".join(f"{k}: {v}\r\n" for k, v in all_headers.items()).encode()
        + b"\r\n"
        + body
    )
    socket = Socket(wire)
    server.RequestHandlerClass(socket, ("127.0.0.1", 1), server)
    response = HTTPResponse(Socket(bytes(socket.output)))
    response.begin()
    return response.status, json.loads(response.read())


def test_browser_upload_analyze_edit_confirm_attach_without_telegram(web, rig):
    jobs, state, server, service, api = web
    auth = login(server)
    assert request(server, "/api/accounts", headers=auth)[2]["accounts"][0]["name"] == "테스트 계좌"
    assert state.status()["web_ready"] and state.status()["ready"] and not state.status()["telegram_ready"]
    code, response = upload_request(server, auth)
    assert code == 200
    job = state.store.get(response["id"])
    assert job["adapter"] == "web" and Path(job["original"]).read_bytes() == sample_image()
    service.settings.auto_save = True
    service.tick(telegram_ready=False)
    current = state.store.get(job["id"])
    assert current["state"] == "waiting" and not api.posts
    assert rig[2].downloads == 0 and state.store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
    code, _, edited = request(
        server,
        f"/api/jobs/{job['id']}/control",
        {"action": "edit", "revision": 0, "values": {"amount": "13000"}},
        auth,
    )
    assert code == 200 and edited["revision"] == 1
    assert (
        request(server, f"/api/jobs/{job['id']}/control", {"action": "confirm", "revision": 0}, auth)[0]
        == 400
    )
    assert (
        request(server, f"/api/jobs/{job['id']}/control", {"action": "confirm", "revision": 1}, auth)[0]
        == 200
    )
    service.tick(telegram_ready=False)
    service.tick(telegram_ready=False)
    assert state.store.get(job["id"])["state"] == "done"
    assert len(api.posts) == 1 and api.posts[0][1]["amount"] == "13000" and len(api.uploads) == 1
    assert not rig[2].messages


def test_upload_auth_csrf_origin_size_and_bytes_are_checked_before_queueing(web):
    jobs, state, server, service, api = web
    assert upload_request(server)[0] == 401
    auth = login(server)
    assert upload_request(server, {"Cookie": auth["Cookie"]})[0] == 403
    assert upload_request(server, auth, overrides={"Origin": "https://evil.invalid"})[0] == 403
    assert upload_request(server, auth, overrides={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert upload_request(server, auth, overrides={"Content-Length": str(100 * 1024 * 1024)})[0] == 413
    assert upload_request(server, auth, data=b"NOT_AN_IMAGE")[0] == 400
    assert state.store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    assert not api.posts


def test_upload_retries_are_idempotent_and_changed_content_is_rejected(web):
    jobs, state, server, service, api = web
    data = sample_image()
    first = jobs.upload("SAME_REQUEST_KEY_1234", data, "test-account")
    second = jobs.upload("SAME_REQUEST_KEY_1234", data, "test-account")
    assert first["id"] == second["id"] and first["request_key"] == second["request_key"]
    with pytest.raises(ValueError, match="다른 내용"):
        jobs.upload("SAME_REQUEST_KEY_1234", data, "test-account", "changed caption")
    assert state.store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    assert hashlib.sha256(Path(first["original"]).read_bytes()).digest() == hashlib.sha256(data).digest()


def test_upload_disallows_unavailable_account_and_controls_need_csrf(web):
    jobs, state, server, service, api = web
    with pytest.raises(ValueError):
        jobs.upload("TEST_REQUEST_KEY_1234", sample_image(), "unknown-account")
    assert state.store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    job = jobs.upload("TEST_REQUEST_KEY_1234", sample_image(), "test-account")
    auth = login(server)
    path = f"/api/jobs/{job['id']}/control"
    assert request(server, path, {"action": "cancel", "revision": 0})[0] == 401
    assert request(server, path, {"action": "cancel", "revision": 0}, {"Cookie": auth["Cookie"]})[0] == 403
    assert request(server, path, {"action": "confirm", "revision": 0}, auth)[0] == 400
    state.store.update(job["id"], state="waiting")
    assert request(server, path, {"action": "cancel", "revision": 0}, auth)[0] == 200
    assert state.store.get(job["id"])["state"] == "cancelled"
    assert Path(job["original"]).exists()


def test_failed_attachment_can_be_retried_from_browser_without_second_transaction(web):
    jobs, state, server, service, api = web
    job = jobs.upload("TEST_REQUEST_KEY_1234", sample_image(), "test-account")
    service.tick(telegram_ready=False)
    jobs.control(job["id"], {"action": "confirm", "revision": 0})
    service.tick(telegram_ready=False)
    api.fail_attach = True
    service.tick(telegram_ready=False)
    state.store.update(job["id"], next_at=0)
    service.tick(telegram_ready=False)
    assert state.store.get(job["id"])["state"] == "attach_failed"
    api.fail_attach = False
    jobs.control(job["id"], {"action": "retry", "revision": 0})
    service.tick(telegram_ready=False)
    assert state.store.get(job["id"])["state"] == "done" and len(api.posts) == 1


def test_multipart_parser_rejects_duplicate_fields_and_too_many_parts():
    content_type, body = multipart()
    assert parse_upload(content_type, body)["account"] == "test-account"
    extra = b'--TEST_RECEIPT_BOUNDARY\r\nContent-Disposition: form-data; name="account"\r\n\r\nother\r\n'
    content_type, body = multipart(extra=extra)
    with pytest.raises(ValueError):
        parse_upload(content_type, body)
    with pytest.raises(ValueError):
        parse_upload('multipart/form-data; boundary="bad boundary"', body)


def test_read_only_accounts_are_hidden_and_cannot_accept_upload(web, monkeypatch):
    from receipt_bridge import web_jobs
    from tests.fakes import ACCOUNT

    jobs, state, server, service, api = web

    class ReadOnlyLedger:
        def request(self, *args):
            return [{**ACCOUNT, "role": "viewer"}]

        def context(self, account):
            return {**ACCOUNT, "role": "viewer"}, []

        def close(self):
            pass

    monkeypatch.setattr(web_jobs, "Ledger", lambda *args: ReadOnlyLedger())
    assert jobs.accounts() == []
    with pytest.raises(ValueError, match="저장할 수 없는"):
        jobs.upload("TEST_UPLOAD_KEY_1234", sample_image(), "test-account")
    assert state.store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_two_browser_confirmations_cannot_duplicate_a_transaction(web):
    from concurrent.futures import ThreadPoolExecutor

    jobs, state, server, service, api = web
    job = jobs.upload("TEST_UPLOAD_KEY_1234", sample_image(), "test-account")
    service.tick(telegram_ready=False)

    def confirm():
        try:
            jobs.control(job["id"], {"action": "confirm", "revision": 0})
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm(), range(2)))
    assert results.count(True) == 1
    service.tick(telegram_ready=False)
    service.tick(telegram_ready=False)
    assert len(api.posts) == 1 and len(api.keys) == 1


def test_web_only_runtime_check_does_not_require_telegram_configuration():
    from receipt_bridge.config import Settings

    settings = Settings(web_enabled=True, ledger_password="TEST_ONLY", ai_model="test-vision")
    settings.check_runtime()
    settings.web_enabled = False
    with pytest.raises(ValueError):
        settings.check_runtime()
