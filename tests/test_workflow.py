import json
from pathlib import Path

import pytest

from receipt_bridge.service import Service
from receipt_bridge.store import Store
from tests.fakes import photo_update, sample_extraction


def received(rig, update=None):
    service, store, _, _ = rig
    store.ingest([update or photo_update()], service.authorized_update)
    service.tick()
    return store.pending(1, 1)[0]


def command(service, store, text, update_id=20, user=1):
    update = {
        "update_id": update_id,
        "message": {"message_id": update_id, "from": {"id": user}, "chat": {"id": 1}, "text": text},
    }
    store.ingest([update], service.authorized_update)
    service.tick()


def test_end_to_end_requires_confirmation_and_exact_ledger_contract(rig):
    service, store, messenger, api = rig
    job = received(rig)
    assert job["state"] == "waiting"
    assert not api.posts
    assert Path(job["original"]).read_bytes().startswith(b"\x89PNG")
    assert Path(job["image"]).read_bytes().startswith(b"\xff\xd8")
    service.confirm(job)
    service.tick()
    service.tick()
    done = store.get(job["id"])
    assert done["state"] == "done"
    assert done["posting_id"] == "test-posting"
    assert done["receipt_id"] == "test-receipt"
    payload = api.posts[0][1]
    assert payload["amount"] == "12000" and payload["category"] == "food"
    assert payload["kind"] == "expense" and payload["account_id"] == "test-account"
    assert payload["timezone"] == "Asia/Seoul"
    assert len(api.uploads) == 1
    assert messenger.downloads == 1
    states = [r[0] for r in store.db.execute("SELECT state FROM events WHERE job_id=?", (job["id"],))]
    assert states == ["received", "processing", "waiting", "creating", "attaching", "done"]


def test_redelivered_update_and_message_create_one_job(rig):
    service, store, messenger, _ = rig
    received(rig)
    store.ingest([photo_update(), photo_update(update_id=2)], service.authorized_update)
    service.tick()
    assert store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    assert store.offset() == 3
    assert messenger.downloads == 1


def test_lost_create_response_restart_same_payload_and_key(rig):
    service, store, messenger, api = rig
    job = received(rig)
    service.confirm(job)
    api.fail_create_after_commit = True
    service.tick()
    current = store.get(job["id"])
    assert current["state"] == "creating" and current["posting_id"] is None
    frozen = current["payload"]
    with pytest.raises(ValueError):
        service.editable(current)
    # Simulate a fresh process with the persisted database.
    reopened = Store(service.settings.data_dir / "jobs.sqlite3")
    resumed = Service(service.settings, reopened, messenger, service.ai, service.ledger, ocr=lambda *_: "")
    reopened.update(job["id"], next_at=0)
    resumed.tick()
    resumed.tick()
    assert reopened.get(job["id"])["state"] == "done"
    assert reopened.get(job["id"])["payload"] == frozen
    assert len(api.keys) == 1 and len(api.posts) == 2
    assert api.posts[0] == api.posts[1]
    reopened.close()


def test_attachment_failure_retries_only_attachment(rig):
    service, store, _, api = rig
    job = received(rig)
    service.confirm(job)
    service.tick()
    api.fail_attach = True
    service.tick()
    store.update(job["id"], next_at=0)
    service.tick()
    current = store.get(job["id"])
    assert current["state"] == "attach_failed" and current["posting_id"]
    api.fail_attach = False
    command(service, store, f"/retry {job['id']}")
    assert store.get(job["id"])["state"] == "done"
    assert len(api.posts) == 1 and len(api.uploads) == 3


def test_missing_total_or_date_never_posts_and_can_be_edited(rig):
    service, store, _, api = rig
    service.ai.extract = lambda *_: sample_extraction(amount=None, date=None)
    job = received(rig)
    assert job["state"] == "waiting" and job["error"]
    with pytest.raises(ValueError):
        service.confirm(job)
    assert not api.posts
    command(service, store, f"/edit {job['id']} amount=12000 date=2026-01-15")
    edited = store.get(job["id"])
    assert edited["revision"] == 1 and edited["error"] is None
    service.confirm(edited)
    service.tick()
    assert api.posts[0][1]["date"] == "2026-01-15"


def test_stale_buttons_and_other_user_cannot_confirm(rig):
    service, store, _, api = rig
    job = received(rig)
    command(service, store, f"/edit {job['id']} amount=13000")
    for uid, revision in [(1, 0), (2, 1)]:
        update = {
            "update_id": 30 + uid,
            "callback_query": {
                "id": "callback",
                "from": {"id": uid},
                "message": {"chat": {"id": 1}},
                "data": f"rb:confirm:{job['id']}:{revision}",
            },
        }
        store.ingest([update], service.authorized_update)
        service.tick()
    assert store.get(job["id"])["state"] == "waiting"
    assert not api.posts


def test_allowlists_require_both_and_reject_before_download(rig):
    service, store, messenger, _ = rig
    store.ingest([photo_update(user=999), photo_update(update_id=2, chat=999)], service.authorized_update)
    service.tick()
    assert not store.pending(1, 1) and messenger.downloads == 0
    assert store.db.execute("SELECT count(*) FROM inbox").fetchone()[0] == 0
    assert store.offset() == 3


def test_duplicate_candidate_ignores_time_and_stops_auto(rig):
    service, store, _, api = rig
    first = received(rig)
    service.ai.extract = lambda *_: sample_extraction(time="12:31")
    received(rig, photo_update(update_id=2, message=11))
    jobs = store.pending(1, 1)
    second = next(j for j in jobs if j["id"] != first["id"])
    duplicates = store.duplicates(second["id"], second["fingerprint"], second["image_hash"])
    assert first["id"] in [d["id"] for d in duplicates]
    assert not api.posts
    assert any("중복 후보" in r[0] for r in store.db.execute("SELECT text FROM outbox"))


def test_cancel_and_rotate_invalidate_confirmation(rig):
    service, store, _, api = rig
    job = received(rig)
    command(service, store, f"/rotate {job['id']} 180")
    current = store.get(job["id"])
    assert current["rotation"] == 180 and current["revision"] == 1
    command(service, store, f"/cancel {job['id']}", update_id=21)
    assert store.get(job["id"])["state"] == "cancelled"
    assert Path(job["original"]).exists() and not api.posts


def test_recover_notification_after_state_commit(rig):
    service, store, _, _ = rig
    received(rig)
    store.db.execute("DELETE FROM outbox")
    service.recover_notifications()
    service.recover_notifications()
    assert store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
    assert json.loads(store.db.execute("SELECT buttons FROM outbox").fetchone()[0])["inline_keyboard"]


def test_edit_update_rolls_back_on_crash_and_replays_once(rig, monkeypatch):
    service, store, _, _ = rig
    job = received(rig)
    original = store.finish_update
    monkeypatch.setattr(store, "finish_update", lambda _: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError):
        command(service, store, f"/edit {job['id']} amount=13000")
    assert store.get(job["id"])["revision"] == 0
    monkeypatch.setattr(store, "finish_update", original)
    service.tick()
    assert store.get(job["id"])["revision"] == 1
    store.ingest([{"update_id": 20, "message": {}}], lambda _: True)
    service.tick()
    assert store.get(job["id"])["revision"] == 1


def test_incremental_correction_of_missing_merchant_and_amount(rig):
    service, store, _, api = rig
    service.ai.extract = lambda *_: sample_extraction(merchant=None, amount=None)
    job = received(rig)
    command(service, store, f"/edit {job['id']} merchant=수정 상호")
    assert store.get(job["id"])["revision"] == 1
    assert store.get(job["id"])["error"]
    command(service, store, f"/edit {job['id']} amount=10000", update_id=21)
    fixed = store.get(job["id"])
    assert not fixed["error"] and fixed["revision"] == 2
    service.confirm(fixed)
    service.tick()
    assert api.posts[0][1]["title"] == "수정 상호"


def test_changed_image_cannot_be_attached_or_posted(rig):
    service, store, _, api = rig
    job = received(rig)
    service.confirm(job)
    Path(job["image"]).write_bytes(b"tampered")
    service.tick()
    assert store.get(job["id"])["state"] == "create_failed"
    assert not api.posts


def test_auto_mode_stores_only_independently_verified_receipt(rig):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    service, store, _, api = rig
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    service.settings.auto_save = True
    service.ai.extract = lambda *_: sample_extraction(
        date=today, date_evidence=today, subtotal="11000", tax="1000"
    )
    service.ocr = lambda *_: f"{today}\nTotal KRW 12000"
    job = received(rig)
    assert job["state"] == "creating"
    service.tick()
    service.tick()
    assert store.get(job["id"])["state"] == "done"
    assert len(api.keys) == 1
