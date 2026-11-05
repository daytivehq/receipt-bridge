import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from receipt_bridge.models import TextExtractions
from receipt_bridge.service import Service
from receipt_bridge.store import Store
from receipt_bridge.text_input import ground_text, merge_caption, money_values
from tests.fakes import photo_update, sample_extraction
from tests.test_workflow import command, received


def text_update(text, update_id=1, message=10, timestamp=None):
    body = {"message_id": message, "from": {"id": 1}, "chat": {"id": 1}, "text": text}
    if timestamp is not None:
        body["date"] = timestamp
    return {"update_id": update_id, "message": body}


def expense(merchant="AA", amount="5000", **changes):
    return sample_extraction(
        merchant=merchant,
        amount=amount,
        time=None,
        subtotal=None,
        tax=None,
        total_evidence=f"{merchant}에서 {amount}원",
        date_evidence="오늘",
        **changes,
    )


def accept_text(rig, text, items, timestamp=None):
    service, store, _, _ = rig
    service.ai.extract_text = lambda *args, **kwargs: TextExtractions(items=items)
    store.ingest([text_update(text, timestamp=timestamp)], service.authorized_update)
    service.tick()
    return store.pending(1, 1)


def test_multiple_expenses_have_individual_confirmation_keys_and_no_photo_upload(rig):
    service, store, messenger, api = rig
    service.settings.auto_save = True
    jobs = accept_text(rig, "나 오늘 AA에서 5000원, BB에서 43500원 썼어", [expense(), expense("BB", "43500")])
    assert len(jobs) == 2
    assert all(j["state"] == "waiting" and not j["error"] for j in jobs)
    assert sorted(j["part"] for j in jobs) == [0, 1]
    assert all(j["batch_size"] == 2 and j["input_kind"] == "text" for j in jobs)
    assert len({j["request_key"] for j in jobs}) == 2
    assert not api.posts and messenger.downloads == 0
    for job in jobs:
        service.confirm(job)
        service.tick()
    assert all(store.get(j["id"])["state"] == "done" for j in jobs)
    assert sorted(payload["amount"] for _, payload in api.posts) == ["43500", "5000"]
    assert not api.uploads
    assert all(store.get(j["id"])["receipt_id"] is None for j in jobs)


def test_redelivery_and_restart_do_not_split_or_create_again(rig):
    service, store, messenger, api = rig
    jobs = accept_text(rig, "오늘 AA에서 5000원, BB에서 43500원", [expense(), expense("BB", "43500")])
    store.ingest([text_update("오늘 AA에서 5000원, BB에서 43500원", update_id=2)], service.authorized_update)
    service.tick()
    assert store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
    first = next(j for j in jobs if j["part"] == 0)
    service.confirm(first)
    api.fail_create_after_commit = True
    service.tick()
    frozen = store.get(first["id"])["payload"]
    reopened = Store(service.settings.data_dir / "jobs.sqlite3")
    try:
        resumed = Service(service.settings, reopened, messenger, service.ai, service.ledger)
        reopened.update(first["id"], next_at=0)
        resumed.tick()
        saved = reopened.get(first["id"])
        assert saved["state"] == "done" and saved["payload"] == frozen
        assert api.posts[0] == api.posts[1] and len(api.keys) == 1
        assert reopened.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
        assert not api.uploads
    finally:
        reopened.close()


def test_split_is_atomic_if_second_item_commit_fails(rig, monkeypatch):
    service, store, _, api = rig
    service.ai.extract_text = lambda *args, **kwargs: TextExtractions(
        items=[expense(), expense("BB", "43500")]
    )
    store.ingest([text_update("오늘 AA에서 5000원, BB에서 43500원")], service.authorized_update)
    original = store.update

    def crash(job_id, **fields):
        if fields.get("part") == 1:
            raise RuntimeError("simulated crash")
        return original(job_id, **fields)

    monkeypatch.setattr(store, "update", crash)
    service.tick()
    assert store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    job = store.pending(1, 1)[0]
    assert job["state"] == "failed" and job["extraction"] is None
    assert not api.posts
    monkeypatch.setattr(store, "update", original)
    command(service, store, f"/retry {job['id']}")
    assert store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
    assert all(j["state"] == "waiting" for j in store.pending(1, 1))


def test_relative_date_uses_message_day_and_missing_fields_require_edits(rig):
    service, store, _, api = rig
    reference = datetime(2026, 1, 15, 23, 59, tzinfo=ZoneInfo("Asia/Seoul"))
    jobs = accept_text(rig, "오늘 AA에서 5000원", [expense()], timestamp=int(reference.timestamp()))
    job = jobs[0]
    assert json.loads(job["extraction"])["date"] == "2026-01-15"
    assert job["reference_date"] == "2026-01-15"
    service.confirm(job)
    service.tick()
    assert api.posts[0][1]["date"] == "2026-01-15"


def test_unstated_date_and_hallucinated_amount_never_post(rig):
    service, store, _, api = rig
    jobs = accept_text(rig, "AA에서 5000원", [expense(amount="99999")])
    job = jobs[0]
    ex = json.loads(job["extraction"])
    assert ex["date"] is None and ex["amount"] is None and job["error"]
    with pytest.raises(ValueError):
        service.confirm(job)
    command(service, store, f"/edit {job['id']} amount=5000 date=2026-01-15")
    fixed = store.get(job["id"])
    service.confirm(fixed)
    service.tick()
    assert api.posts[0][1]["amount"] == "5000"


def test_photo_caption_can_set_category_and_conflicting_total_requires_choice(rig):
    service, store, _, api = rig
    annotation = sample_extraction(
        merchant=None,
        amount="13000",
        total_evidence="13000원",
        date=None,
        date_evidence=None,
        time=None,
        currency=None,
        category="food",
    )
    service.ai.extract_text = lambda *args, **kwargs: TextExtractions(items=[annotation])
    update = photo_update()
    update["message"]["caption"] = "이건 식비야. 13000원"
    service.settings.auto_save = True
    job = received(rig, update)
    assert job["state"] == "waiting"
    assert json.loads(job["conflicts"]) == {"amount": ["12000", "13000"]}
    assert "불일치" in job["error"]
    with pytest.raises(ValueError, match="불일치"):
        service.confirm(job)
    assert not api.posts
    command(service, store, f"/edit {job['id']} amount=13000")
    fixed = store.get(job["id"])
    assert json.loads(fixed["conflicts"]) == {} and fixed["error"] is None
    service.confirm(fixed)
    service.tick()
    service.tick()
    assert api.posts[0][1]["amount"] == "13000" and len(api.uploads) == 1


def test_photo_caption_fills_missing_values_and_always_waits(rig):
    service, store, _, api = rig
    service.ai.extract = lambda *args: sample_extraction(amount=None, category=None)
    annotation = sample_extraction(
        merchant=None,
        amount="12000",
        total_evidence="12000원",
        date=None,
        date_evidence=None,
        time=None,
        currency=None,
        category="food",
    )
    seen = []
    service.ai.extract_text = lambda *args, **kwargs: (
        seen.append(kwargs) or TextExtractions(items=[annotation])
    )
    update = photo_update()
    update["message"]["caption"] = "식비, 12000원"
    service.settings.auto_save = True
    job = received(rig, update)
    assert job["state"] == "waiting" and not job["error"]
    assert json.loads(job["extraction"])["amount"] == "12000"
    assert seen == [{"annotation": True}]
    assert not api.posts


def test_five_photo_album_creates_five_individual_jobs(rig):
    service, store, messenger, api = rig
    updates = [photo_update(update_id=n, message=100 + n) for n in range(1, 6)]
    for update in updates:
        update["message"]["media_group_id"] = "TEST_ALBUM"
    store.ingest(updates, service.authorized_update)
    for _ in range(5):
        service.tick()
    jobs = store.pending(1, 1)
    assert len(jobs) == 5 and messenger.downloads == 5
    assert all(j["state"] == "waiting" for j in jobs)
    assert not api.posts
    for job in jobs:
        service.confirm(job)
    for _ in range(10):
        service.tick()
    assert all(store.get(j["id"])["state"] == "done" for j in jobs)
    assert len(api.keys) == 5 and len(api.uploads) == 5


def test_text_cannot_rotate_and_commands_do_not_go_to_ai(rig):
    service, store, _, api = rig
    job = accept_text(rig, "오늘 AA에서 5000원", [expense()])[0]
    service.ai.extract_text = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("no inference for commands")
    )
    command(service, store, f"/rotate {job['id']} 90")
    assert store.get(job["id"])["state"] == "waiting" and store.get(job["id"])["rotation"] == 0
    command(service, store, "/help", update_id=21)
    assert not api.posts
    assert any("사진이 없습니다" in row[0] for row in store.db.execute("SELECT text FROM outbox"))


def test_legacy_database_migration_keeps_frozen_jobs(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    store = Store(path)
    job = store.create_job(1, 1, 1, "TEST", "account")
    store.update(job["id"], state="creating", payload='{"TEST":"FROZEN"}')
    key = job["request_key"]
    store.close()
    # SQLite supports dropping newly added columns, reproducing the previous schema.
    with sqlite3.connect(path) as db:
        for column in ("input_kind", "input_text", "reference_date", "conflicts", "batch_size", "part"):
            db.execute("ALTER TABLE jobs DROP COLUMN " + column)
    reopened = Store(path)
    try:
        migrated = reopened.get(job["id"])
        assert migrated["request_key"] == key and migrated["payload"] == '{"TEST":"FROZEN"}'
        assert migrated["input_kind"] == "image" and migrated["input_text"] == ""
    finally:
        reopened.close()


def test_grounding_and_batch_limits():
    assert money_values("4.35만원, 5천원, 43,500원") == {Decimal("43500"), Decimal("5000")}
    bad = sample_extraction(
        merchant="없는 상호",
        amount="999",
        date="2026-01-01",
        time="12:30",
        total_evidence="999",
        date_evidence="임의 날짜",
    )
    result = ground_text(bad, "AA 5000원", "2026-01-15", "KRW")
    assert result.merchant is None and result.amount is None and result.date is None and result.time is None
    assert len(result.warnings) <= 20
    receipt = sample_extraction(amount="12000")
    annotation = sample_extraction(
        amount="12000.00", time=None, date=None, merchant=None, category=None, currency=None
    )
    _, conflicts = merge_caption(receipt, annotation)
    assert conflicts == {}
    with pytest.raises(ValidationError):
        TextExtractions(items=[expense() for _ in range(21)])


def test_ambiguous_dates_and_negative_values_are_not_invented():
    from receipt_bridge.text_input import supported_date

    assert supported_date("어제", "2026-01-15") == "2026-01-14"
    assert supported_date("오늘 또는 어제", "2026-01-15") is None
    assert supported_date("2026년 1월 2일", "2026-01-15") == "2026-01-02"
    assert supported_date("2026-01-153", "2026-01-15") is None
    assert not money_values("-5000원")


def test_currency_is_defaulted_only_when_omitted_not_when_foreign_symbol_is_unresolved():
    value = sample_extraction(merchant="AA", amount="12", total_evidence="AA $12", currency=None)
    unresolved = ground_text(value, "오늘 AA $12", "2026-01-15", "KRW")
    assert unresolved.currency is None
    explicit = ground_text(
        value.model_copy(update={"total_evidence": "AA 12 EUR", "currency": "KRW"}),
        "오늘 AA 12 EUR",
        "2026-01-15",
        "KRW",
    )
    assert explicit.currency == "EUR"
    omitted = ground_text(
        value.model_copy(update={"total_evidence": "AA 12"}), "오늘 AA 12", "2026-01-15", "KRW"
    )
    assert omitted.currency == "KRW"
    caption = ground_text(
        value.model_copy(update={"total_evidence": "12원"}), "12원", "2026-01-15", "USD", annotation=True
    )
    assert caption.currency == "KRW"


def test_three_letter_merchant_is_not_mistaken_for_a_currency():
    ex = sample_extraction(merchant="BBQ", amount="5000", currency=None, total_evidence="BBQ 5000")
    result = ground_text(ex, "오늘 BBQ 5000", "2026-01-15", "KRW")
    assert result.currency == "KRW"
