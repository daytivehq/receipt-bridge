import base64
import json
import runpy
from types import SimpleNamespace

import pytest

from receipt_bridge import runner, runner_setup
from receipt_bridge.config import load_settings
from receipt_bridge.runner_auth import runner_token
from tests.fakes import sample_extraction, sample_image
from tests.test_admin import login, request


def test_automatic_token_persists_without_exposing_other_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_RUNNER_TOKEN", raising=False)
    monkeypatch.delenv("AI_RUNNER_TOKEN_FILE", raising=False)
    auth = tmp_path / "auth"
    monkeypatch.setenv("AI_RUNNER_AUTH_DIR", str(auth))
    config = tmp_path / "config.toml"
    config.write_text("web_enabled = true\n")
    monkeypatch.setenv("DUET_APP_PASSWORD", "DO_NOT_SHARE_LEDGER")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "DO_NOT_SHARE_TELEGRAM")
    first = load_settings(config).ai_runner_token.get_secret_value()
    assert len(first) >= 32
    assert load_settings(config).ai_runner_token.get_secret_value() == first
    assert runner_token() == first
    assert list(auth.iterdir()) == [auth / "token"]
    assert (auth / "token").stat().st_mode & 0o777 == 0o600
    assert "DO_NOT_SHARE" not in (auth / "token").read_text()


def test_manual_token_remains_compatible_and_shared_symlinks_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_RUNNER_AUTH_DIR", str(tmp_path))
    monkeypatch.setenv("AI_RUNNER_TOKEN", "T" * 32)
    monkeypatch.delenv("AI_RUNNER_TOKEN_FILE", raising=False)
    assert runner_token(create=True) == "T" * 32
    assert not (tmp_path / "token").exists()
    monkeypatch.delenv("AI_RUNNER_TOKEN")
    secret = tmp_path / "other"
    secret.write_text("PRIVATE")
    (tmp_path / "token").symlink_to(secret)
    with pytest.raises(OSError):
        runner_token(create=True)
    assert secret.read_text() == "PRIVATE"


@pytest.fixture
def runner_request(monkeypatch, tmp_path):
    socket_type = runpy.run_path("tests/test_admin.py")["Socket"]
    handlers = []
    monkeypatch.setenv("AI_RUNNER_TOKEN", "T" * 32)
    monkeypatch.delenv("AI_RUNNER_TOKEN_FILE", raising=False)
    monkeypatch.setenv("AI_HOME", str(tmp_path))
    for key in (
        "DUET_APP_PASSWORD",
        "TELEGRAM_BOT_TOKEN",
        "DUET_APP_PASSWORD_FILE",
        "TELEGRAM_BOT_TOKEN_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        runner,
        "RunnerServer",
        lambda address, handler: handlers.append(handler) or SimpleNamespace(serve_forever=lambda: None),
    )
    runner.serve()

    def send(path, data=None, token="T" * 32):
        body = json.dumps(data).encode() if data is not None else b""
        method = "POST" if data is not None else "GET"
        wire = (
            f"{method} {path} HTTP/1.0\r\nAuthorization: Bearer {token}\r\nContent-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        socket = socket_type(wire)
        handlers[0](socket, ("127.0.0.1", 1), None)
        header, _, raw = bytes(socket.output).partition(b"\r\n\r\n")
        return int(header.split()[1]), raw

    return send


def test_one_runner_switches_providers_models_and_timeout_per_request(runner_request, monkeypatch):
    calls = []
    monkeypatch.setattr(
        runner, "run_cli", lambda *args, **kwargs: calls.append((args, kwargs)) or sample_extraction()
    )
    for provider in ("agy", "codex", "claude"):
        body = {"provider": provider, "model": "chosen-" + provider, "timeout": 600, "categories": []}
        body.update(
            {"text": "TEST OCR"}
            if provider == "agy"
            else {"image": base64.b64encode(sample_image()).decode()}
        )
        assert runner_request("/extract", body)[0] == 200
    assert [args[0] for args, _ in calls] == ["agy", "codex", "claude"]
    assert [args[1] for args, _ in calls] == ["chosen-agy", "chosen-codex", "chosen-claude"]
    assert all(args[5] == 600 for args, _ in calls)
    for value in (True, 0, 1801, "600"):
        assert runner_request("/extract", {"provider": "agy", "model": "TEST", "timeout": value})[0] == 400
    assert len(calls) == 3


def test_runner_setup_requires_auth_and_never_returns_api_key(runner_request, tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner, "check_provider", lambda provider, home: {"provider": provider, "installed": True}
    )
    for path, body in (
        ("/check", {"provider": "agy"}),
        ("/credentials", {"provider": "claude", "key": "TEST_API_KEY"}),
    ):
        assert runner_request(path, body, "WRONG")[0] == 401
    assert not (tmp_path / "anthropic-api-key").exists()
    assert runner_request("/check", {"provider": "agy"})[0] == 200
    status, raw = runner_request("/credentials", {"provider": "claude", "key": "TEST_API_KEY"})
    assert status == 200 and b"TEST_API_KEY" not in raw
    assert (tmp_path / "anthropic-api-key").read_text() == "TEST_API_KEY"
    assert (tmp_path / "anthropic-api-key").stat().st_mode & 0o777 == 0o600
    for provider, key in (("agy", "OTHER"), ("claude", "BAD\nKEY")):
        assert runner_request("/credentials", {"provider": provider, "key": key})[0] == 400
    assert (tmp_path / "anthropic-api-key").read_text() == "TEST_API_KEY"
    assert runner_request("/status", token="WRONG")[0] == 401


def test_setup_checks_run_fixed_commands_without_receipt_or_bridge_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_setup.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setenv("DUET_APP_PASSWORD", "DO_NOT_PASS")
    monkeypatch.setenv("AI_RUNNER_TOKEN", "DO_NOT_PASS_EITHER")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0, stdout=b"gemini-test-low\tTEST\ngemini-test-low\tTEST\nPRIVATE_EMAIL@example.com"
        )

    monkeypatch.setattr(runner_setup.subprocess, "run", run)
    result = runner_setup.check_provider("agy", tmp_path)
    assert result["models"] == ["gemini-test-low"]
    assert result["auth"] == "unknown"  # agy models also works before login.
    assert "PRIVATE_EMAIL" not in json.dumps(result)
    assert calls[0][0] == ["agy", "models"]
    assert "DUET_APP_PASSWORD" not in calls[0][1]["env"]
    assert "AI_RUNNER_TOKEN" not in calls[0][1]["env"]
    assert runner_setup.check_provider("codex", tmp_path)["auth"] == "configured"
    assert calls[-1][0] == ["codex", "login", "status"]
    with pytest.raises(ValueError):
        runner_setup.check_provider("sh", tmp_path)


def test_admin_ai_setup_requires_session_csrf_and_saved_settings(rig, monkeypatch):
    from receipt_bridge import admin

    settings = rig[0].settings.model_copy(update={"ai_provider": "claude", "allow_external_ai": True})
    state = admin.AdminState(settings, rig[1])
    state.setup_admin("TEST_ADMIN_PASSWORD", "TEST_ADMIN_PASSWORD")
    server = admin.make_server(state, port=0)
    calls = []
    monkeypatch.setattr(
        admin,
        "runner_setup",
        lambda settings, action, key=None: (
            calls.append((settings.ai_provider, action, key)) or {"installed": True}
        ),
    )
    try:
        for path in ("/api/ai/check", "/api/ai/credentials"):
            assert request(server, path, {})[0] == 401
        auth = login(server)
        assert request(server, "/api/ai/check", {}, {"Cookie": auth["Cookie"]})[0] == 403
        assert not calls
        assert request(server, "/api/ai/check", {}, auth)[0] == 200
        status, _, body = request(server, "/api/ai/credentials", {"key": "TEST_API_KEY"}, auth)
        assert status == 200 and "TEST_API_KEY" not in json.dumps(body)
        assert calls == [("claude", "check", None), ("claude", "credentials", "TEST_API_KEY")]
        assert "TEST_API_KEY" not in json.dumps(state.store.setting("ui_settings", {}))
    finally:
        server.server_close()


def test_setup_proxy_sends_only_runner_token_and_selected_ai_key(rig, monkeypatch):
    import httpx
    from pydantic import SecretStr

    from receipt_bridge import ai

    settings = rig[0].settings.model_copy(
        update={
            "ai_provider": "claude",
            "allow_external_ai": True,
            "ai_runner_token": SecretStr("T" * 32),
            "ai_runner_url": "http://runner.invalid",
            "ledger_password": SecretStr("DO_NOT_PASS_LEDGER"),
            "telegram_token": SecretStr("DO_NOT_PASS_TELEGRAM"),
        }
    )
    real_client = httpx.Client
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer " + "T" * 32
        assert json.loads(request.content) == {"provider": "claude", "key": "TEST_API_KEY"}
        assert b"DO_NOT_PASS" not in request.content
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(
        ai.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)
    )
    assert ai.runner_setup(settings, "credentials", "TEST_API_KEY") == {"ok": True}
    assert len(calls) == 1
    for invalid in (None, "", "BAD\nKEY"):
        with pytest.raises(ValueError):
            ai.runner_setup(settings, "credentials", invalid)
    with pytest.raises(ValueError, match="외부 AI"):
        ai.runner_setup(settings.model_copy(update={"allow_external_ai": False}), "check")
    assert len(calls) == 1

    monkeypatch.setattr(
        ai.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="TEST_API_KEY DO_NOT_PASS_LEDGER")
            ),
            **kwargs,
        ),
    )
    with pytest.raises(ValueError, match="인증이 일치하지") as error:
        ai.runner_setup(settings, "check")
    assert "DO_NOT_PASS" not in str(error.value) and "TEST_API_KEY" not in str(error.value)


def test_runner_text_protocol_validates_metadata_and_returns_batch(runner_request, monkeypatch):
    from receipt_bridge.models import TextExtractions

    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return TextExtractions(items=[sample_extraction()])

    monkeypatch.setattr(runner, "run_cli", run)
    body = {
        "provider": "agy",
        "model": "chosen",
        "mode": "text",
        "text": "오늘 AA 5000원",
        "categories": [],
        "reference_date": "2026-01-15",
        "currency": "KRW",
        "annotation": False,
    }
    status, raw = runner_request("/extract", body)
    assert status == 200 and len(json.loads(raw)["items"]) == 1
    assert calls[0][0][2] is None
    assert calls[0][1]["text_only"] is True
    assert calls[0][1]["reference_date"] == "2026-01-15"
    for invalid in (
        {"reference_date": "invalid"},
        {"annotation": "true"},
        {"currency": "USD\n"},
        {"text": "X" * 4097},
    ):
        assert runner_request("/extract", {**body, **invalid})[0] != 200
    assert len(calls) == 1
