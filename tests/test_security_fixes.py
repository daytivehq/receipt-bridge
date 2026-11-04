import json
import runpy
import threading
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from receipt_bridge import runner
from receipt_bridge.admin import AdminState
from receipt_bridge.ai import OllamaAI
from receipt_bridge.models import Extraction
from tests.fakes import photo_update, sample_extraction, sample_image


def test_attachment_key_rotation_keeps_post_and_never_creates_again(rig):
    service, store, _, api = rig
    state = AdminState(service.settings, store)
    store.ingest([photo_update()], service.authorized_update)
    service.tick()
    job = store.pending(1, 1)[0]
    service.confirm(job)
    service.tick()
    api.fail_attach = True
    service.tick()
    saved = store.get(job["id"])
    state.save({"secrets": {"ledger_password": "NEW_TEST_KEY"}})
    assert not state.ledger_change_blocked(state.effective())
    assert store.get(job["id"])["posting_id"] == saved["posting_id"]
    assert store.get(job["id"])["payload"] == saved["payload"]
    assert len(api.posts) == 1
    with pytest.raises(ValueError):
        state.save({"ledger_url": "http://other.invalid/api/v1"})


def test_account_override_and_later_revocation_are_blocked(rig):
    service, store, _, api = rig
    store.ingest([photo_update()], service.authorized_update)
    service.tick()
    job = store.pending(1, 1)[0]
    with pytest.raises(ValueError, match="허용된 저장 계좌"):
        service.edit(job, "account=other-account")
    service.settings.user_accounts["1"] = "different-account"
    with pytest.raises(ValueError, match="허용된 저장 계좌"):
        service.confirm(job)
    assert not api.posts


def test_db_is_available_while_context_is_waiting_and_update_commits_once(rig):
    service, store, _, _ = rig
    job = store.create_job(1, 1, 1, "TEST", "test-account")
    store.set_setting("paused", True)
    entered, release = threading.Event(), threading.Event()
    original = service.ledger.context

    def context(account):
        entered.set()
        assert release.wait(5)
        return original(account)

    service.ledger.context = context
    store.ingest(
        [
            {
                "update_id": 5,
                "message": {"from": {"id": 1}, "chat": {"id": 1}, "text": "/categories " + job["id"]},
            }
        ],
        service.authorized_update,
    )
    errors = []

    def tick():
        try:
            service.tick()
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=tick)
    worker.start()
    try:
        assert entered.wait(2)
        assert store.lock.acquire(timeout=0.5)
        store.lock.release()
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and not errors
    assert store.next_update() is None


def test_bot_reply_keys_do_not_collide(rig):
    service, store, _, _ = rig
    service.settings.telegram_token = SecretStr("100:TEST")
    service.reply({"update_id": 1}, 1, "first")
    store.notification_result(store.next_notification(), True)
    service.settings = service.settings.model_copy(update={"telegram_token": SecretStr("200:TEST")})
    service.reply({"update_id": 1}, 1, "second")
    assert store.next_notification()["text"] == "second"


def test_runner_auth_checked_before_inference(monkeypatch):
    Socket = runpy.run_path("tests/test_admin.py")["Socket"]
    handlers = []
    monkeypatch.setenv("AI_PROVIDER", "agy")
    monkeypatch.setenv("AI_RUNNER_TOKEN", "T" * 32)
    monkeypatch.setattr(
        runner,
        "RunnerServer",
        lambda address, handler: handlers.append(handler) or SimpleNamespace(serve_forever=lambda: None),
    )
    calls = []
    monkeypatch.setattr(runner, "run_cli", lambda *args, **kwargs: calls.append(True) or sample_extraction())
    runner.serve()
    for auth, expected in [("", b"401"), ("Bearer WRONG", b"401"), ("Bearer " + "T" * 32, b"200")]:
        body = json.dumps({"provider": "agy", "model": "TEST", "text": "TEST", "categories": []}).encode()
        wire = (
            b"POST /extract HTTP/1.0\r\nAuthorization: "
            + auth.encode()
            + b"\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n\r\n"
            + body
        )
        socket = Socket(wire)
        handlers[0](socket, ("127.0.0.1", 1), None)
        assert expected in bytes(socket.output).split(b"\r\n")[0]
    assert len(calls) == 1


def test_ai_response_and_field_sizes_are_bounded(tmp_path):
    image = tmp_path / "receipt.png"
    image.write_bytes(sample_image())
    ai = OllamaAI(
        "http://mock.invalid",
        "TEST",
        30,
        httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 1_000_001)),
    )
    with pytest.raises(Exception, match="JSON 검증"):
        ai.extract(image, [])
    ai.close()
    result = sample_extraction().model_dump()
    result["warnings"] = ["x" * 501]
    with pytest.raises(ValueError):
        Extraction.model_validate(result)


def test_runtime_and_admin_agree_on_missing_mapping(rig):
    service, store, _, _ = rig
    settings = service.settings.model_copy(update={"user_accounts": {"999": "other"}})
    assert not AdminState(settings, store).readiness()["account"]
    with pytest.raises(ValueError):
        settings.check_runtime()


def test_runner_connection_limit_releases_slots(monkeypatch):
    from http.server import ThreadingHTTPServer

    server = runner.RunnerServer(("127.0.0.1", 0), lambda *args: None)
    admitted, closed = [], []
    monkeypatch.setattr(
        ThreadingHTTPServer, "process_request", lambda self, request, address: admitted.append(request)
    )
    monkeypatch.setattr(ThreadingHTTPServer, "process_request_thread", lambda *args: None)
    monkeypatch.setattr(server, "shutdown_request", lambda request: closed.append(request))
    try:
        for number in range(9):
            server.process_request(number, ("127.0.0.1", number))
        assert len(admitted) == 8 and closed == [8]
        server.process_request_thread(0, ("127.0.0.1", 0))
        server.process_request(10, ("127.0.0.1", 10))
        assert admitted[-1] == 10
    finally:
        server.server_close()


def test_edit_and_confirm_network_calls_are_outside_inbox_transaction(rig):
    service, store, messenger, _ = rig
    store.ingest([photo_update()], service.authorized_update)
    service.tick()
    job = store.pending(1, 1)[0]
    store.set_setting("paused", True)
    original = service.ledger.context
    checks = []

    def context(account):
        assert not store.db.in_transaction
        checks.append("context")
        return original(account)

    def answer(callback_id):
        assert not store.db.in_transaction
        checks.append("answer")

    service.ledger.context = context
    messenger.answer = answer
    store.ingest(
        [
            {
                "update_id": 2,
                "message": {
                    "from": {"id": 1},
                    "chat": {"id": 1},
                    "text": "/edit " + job["id"] + " merchant=TEST",
                },
            }
        ],
        service.authorized_update,
    )
    service.tick()
    revision = store.get(job["id"])["revision"]
    store.ingest(
        [
            {
                "update_id": 3,
                "callback_query": {
                    "id": "TEST",
                    "from": {"id": 1},
                    "message": {"chat": {"id": 1}},
                    "data": f"rb:confirm:{job['id']}:{revision}",
                },
            }
        ],
        service.authorized_update,
    )
    service.tick()
    assert checks == ["context", "context", "answer"]
    assert store.get(job["id"])["state"] == "creating"


def test_runner_without_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("AI_RUNNER_TOKEN", raising=False)
    monkeypatch.delenv("AI_RUNNER_TOKEN_FILE", raising=False)
    monkeypatch.setenv("AI_PROVIDER", "agy")
    with pytest.raises(ValueError, match="AI_RUNNER_TOKEN"):
        runner.serve()
