import json

import httpx
import pytest

from receipt_bridge import main
from receipt_bridge.admin import AdminState
from receipt_bridge.ledger import Ledger
from tests.fakes import DemoAI, DemoMessenger, photo_update


@pytest.fixture
def runtime(rig, monkeypatch):
    service, store, messenger, api = rig
    service.ai.close = lambda: None
    messenger.close = lambda: None
    captured = []

    def ledger(url, password):
        captured.append(password)
        return Ledger("http://mock.invalid/api/v1", "TEST_ONLY", transport=httpx.MockTransport(api))

    def ai(settings):
        result = DemoAI()
        result.close = lambda: None
        return result

    def telegram(*args, **kwargs):
        result = DemoMessenger()
        result.close = lambda: None
        return result

    monkeypatch.setattr(main, "Ledger", ledger)
    monkeypatch.setattr(main, "make_ai", ai)
    monkeypatch.setattr(main, "Telegram", telegram)
    state = AdminState(service.settings, store)
    yield state, service, store, captured
    service.ledger.close()


def test_connection_clients_apply_without_restart_and_restore_applied_snapshot(runtime):
    state, service, store, captured = runtime
    state.save({"secrets": {"telegram_token": "100:TEST_TOKEN", "ledger_password": "FIRST_KEY"}})
    main.apply_settings(state, service)
    assert service.settings.telegram_token.get_secret_value() == "100:TEST_TOKEN"
    assert service.settings.ledger_password.get_secret_value() == "FIRST_KEY"
    assert captured[-1] == "FIRST_KEY"
    assert store.credentials(applied=True)["ledger_password"] == "FIRST_KEY"
    restored = AdminState(state.base, store)
    assert restored.current.ledger_password.get_secret_value() == "FIRST_KEY"
    assert restored.effective().ledger_password.get_secret_value() == "FIRST_KEY"
    snapshot = json.dumps(store.setting("ui_applied_settings"))
    assert "FIRST_KEY" not in snapshot and "TEST_TOKEN" not in snapshot


def test_uncertain_post_keeps_original_credential_and_payload_across_restart(runtime):
    state, service, store, _ = runtime
    state.save({"secrets": {"ledger_password": "ORIGINAL_KEY"}})
    main.apply_settings(state, service)
    store.ingest([photo_update()], service.authorized_update)
    service.tick()
    job = store.pending(1, 1)[0]
    service.confirm(job)
    payload, key = store.get(job["id"])["payload"], job["request_key"]
    # Simulate a save racing with a job reaching the POST stage.
    store.set_credentials({"ledger_password": "REQUESTED_NEW_KEY"})
    store.set_setting("ui_revision", state.applied_revision + 1)
    main.apply_settings(state, service)
    assert service.settings.ledger_password.get_secret_value() == "ORIGINAL_KEY"
    restored = AdminState(state.base, store)
    assert restored.current.ledger_password.get_secret_value() == "ORIGINAL_KEY"
    assert restored.effective().ledger_password.get_secret_value() == "REQUESTED_NEW_KEY"
    assert store.get(job["id"])["payload"] == payload
    assert store.get(job["id"])["request_key"] == key


def test_switching_bot_resets_only_processed_inbox_and_uses_distinct_message_scope(runtime):
    state, service, store, _ = runtime
    state.save({"secrets": {"telegram_token": "100:FIRST_TOKEN"}})
    main.apply_settings(state, service)
    store.db.execute("INSERT INTO inbox VALUES(123,'{}',1)")
    store.set_setting("telegram_offset", 124)
    state.save({"secrets": {"telegram_token": "200:SECOND_TOKEN"}})
    main.apply_settings(state, service)
    assert store.offset() == 0
    assert store.db.execute("SELECT count(*) FROM inbox").fetchone()[0] == 0
    first = store.create_job(1, 1, 10, "test", "test-account", adapter="telegram:100")
    second = store.create_job(1, 1, 10, "test", "test-account", adapter="telegram:200")
    assert first["id"] != second["id"]


def test_pending_jobs_block_different_bot_but_allow_same_bot_token_rotation(runtime):
    state, service, store, _ = runtime
    state.save({"secrets": {"telegram_token": "100:FIRST_TOKEN"}})
    main.apply_settings(state, service)
    store.ingest([photo_update()], service.authorized_update)
    service.tick()
    with pytest.raises(ValueError, match="텔레그램 봇"):
        state.save({"secrets": {"telegram_token": "200:SECOND_BOT"}})
    state.save({"secrets": {"telegram_token": "100:ROTATED_TOKEN"}})
    main.apply_settings(state, service)
    assert service.settings.telegram_token.get_secret_value() == "100:ROTATED_TOKEN"
    assert store.offset() == 2


def test_rotated_key_resumes_only_attachment(runtime):
    state, service, store, captured = runtime
    state.save({"secrets": {"ledger_password": "OLD_KEY"}})
    main.apply_settings(state, service)
    store.ingest([photo_update()], service.authorized_update)
    service.tick()
    job = store.pending(1, 1)[0]
    service.confirm(job)
    service.tick()
    saved = store.get(job["id"])
    store.update(job["id"], state="attach_failed")
    state.save({"secrets": {"ledger_password": "ROTATED_KEY"}})
    main.apply_settings(state, service)
    assert captured[-1] == "ROTATED_KEY"
    store.update(job["id"], state="attaching", next_at=0)
    service.tick()
    result = store.get(job["id"])
    assert result["state"] == "done"
    assert result["posting_id"] == saved["posting_id"]
    assert result["payload"] == saved["payload"] and result["request_key"] == saved["request_key"]
