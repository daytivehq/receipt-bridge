from pathlib import Path

import httpx
import pytest

from receipt_bridge.config import Settings
from receipt_bridge.ledger import Ledger
from receipt_bridge.service import Service
from receipt_bridge.store import Store
from tests.fakes import DemoAI, DemoLedgerAPI, DemoMessenger


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("tests must not use real network connections")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.fixture
def rig(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path,
        allowed_users=[1, 2],
        allowed_chats=[1],
        user_accounts={"1": "test-account", "2": "test-account"},
        ai_runner_token="T" * 32,
        retry_seconds=1,
        max_attempts=2,
    )
    store = Store(tmp_path / "jobs.sqlite3")
    messenger, api = DemoMessenger(), DemoLedgerAPI()
    ledger = Ledger("http://mock.invalid/api/v1", "TEST_ONLY", transport=httpx.MockTransport(api))
    service = Service(settings, store, messenger, DemoAI(), ledger, ocr=lambda *_: "")
    yield service, store, messenger, api
    ledger.close()
    store.close()
