"""Explicit, durable Telegram edits must never create an extra transaction."""

import json
from datetime import date

from receipt_bridge.models import blank_extraction
from tests.fakes import photo_update
from tests.test_workflow import command, received


def test_bare_merchant_repairs_single_receipt_and_prompts_for_remaining_values(rig):
    service, store, _, api = rig
    service.ai.extract = lambda *_: blank_extraction()
    job = received(rig)
    command(service, store, "테스트 상호", update_id=20)
    current = store.get(job["id"])
    assert json.loads(current["extraction"])["merchant"] == "테스트 상호"
    assert store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    assert store.setting(service.edit_key(1, 1))["field"] == "amount"
    # Sessions are durable across worker recreation (same DB/settings).
    from receipt_bridge.service import Service

    service = Service(service.settings, store, rig[2], service.ai, service.ledger, ocr=lambda *_: "")
    command(service, store, "1,2원", update_id=21)
    assert json.loads(store.get(job["id"])["extraction"])["amount"] is None
    command(service, store, "12,000원", update_id=22)
    command(service, store, date.today().isoformat(), update_id=23)
    command(service, store, "krw", update_id=24)
    command(service, store, "식비", update_id=25)
    current = store.get(job["id"])
    assert not current["error"] and not api.posts
    assert not store.setting(service.edit_key(1, 1))
    service.confirm(current)
    service.tick()
    service.tick()
    assert store.get(job["id"])["state"] == "done" and len(api.posts) == 1


def test_missing_fields_hide_confirmation_and_edit_button_uses_selected_job(rig):
    service, store, _, _ = rig
    service.ai.extract = lambda *_: blank_extraction()
    job = received(rig)
    row = store.db.execute(
        "SELECT buttons FROM outbox WHERE buttons IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    buttons = json.loads(row[0])["inline_keyboard"][0]
    assert all(":confirm:" not in b["callback_data"] for b in buttons)
    update = {
        "update_id": 50,
        "callback_query": {
            "id": "TEST",
            "from": {"id": 1},
            "message": {"chat": {"id": 1}},
            "data": f"rb:edit:{job['id']}:0",
        },
    }
    service.handle_update(update, service.prepare_context(update))
    assert store.setting(service.edit_key(1, 1))["id"] == job["id"]
    command(service, store, "/stop", update_id=51)
    assert not store.setting(service.edit_key(1, 1))
    assert store.get(job["id"])["state"] == "waiting"


def test_correction_does_not_target_other_users_or_ambiguous_receipts(rig):
    service, store, _, api = rig
    service.ai.extract = lambda *_: blank_extraction()
    first = received(rig)
    assert (
        service.correction_target({"message": {"from": {"id": 2}, "chat": {"id": 1}, "text": "다른 상호"}})
        is None
    )
    store.ingest([photo_update(update_id=2, message=11)], service.authorized_update)
    service.tick()
    assert (
        service.correction_target({"message": {"from": {"id": 1}, "chat": {"id": 1}, "text": "어느 상호"}})
        is None
    )
    assert json.loads(store.get(first["id"])["extraction"])["merchant"] is None and not api.posts


def test_telegram_status_groups_amount_but_ledger_payload_stays_plain(rig):
    from tests.fakes import sample_extraction

    service, store, _, api = rig
    service.ai.extract = lambda *_: sample_extraction(amount="100000000")
    job = received(rig)
    messages = [row[0] for row in store.db.execute("SELECT text FROM outbox")]
    assert any("100,000,000원" in message for message in messages)
    assert json.loads(job["extraction"])["amount"] == "100000000"
    service.confirm(job)
    service.tick()
    assert api.posts[0][1]["amount"] == "100000000"
