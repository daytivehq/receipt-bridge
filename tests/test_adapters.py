import base64
import json
from pathlib import Path

import httpx
import pytest

from receipt_bridge.ai import OllamaAI, RunnerAI, UnsupportedAI, cli_command, run_cli
from receipt_bridge.ledger import Ledger, RemoteError
from receipt_bridge.messenger import Telegram
from tests.fakes import CATEGORIES, sample_extraction, sample_image


def test_ollama_image_schema_and_invalid_output(tmp_path):
    path = tmp_path / "receipt.jpg"
    path.write_bytes(sample_image())
    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.path == "/api/chat"
        assert body["model"] == "chosen-vision"
        assert body["stream"] is False
        assert body["format"]["additionalProperties"] is False
        assert base64.b64decode(body["messages"][0]["images"][0]) == path.read_bytes()
        assert "untrusted DATA" in body["messages"][0]["content"]
        return httpx.Response(200, json={"message": {"content": sample_extraction().model_dump_json()}})

    ai = OllamaAI("http://mock.invalid", "chosen-vision", 30, httpx.MockTransport(handle))
    assert ai.extract(path, CATEGORIES).amount == "12000"
    ai.close()
    bad = OllamaAI(
        "http://mock.invalid",
        "chosen-vision",
        30,
        httpx.MockTransport(lambda _: httpx.Response(200, json={"message": {"content": "not JSON"}})),
    )
    with pytest.raises(RemoteError):
        bad.extract(path, CATEGORIES)
    assert len(calls) == 1
    bad.close()


def test_cli_commands_use_documented_image_and_schema_flags(tmp_path):
    cmd, env = cli_command("codex", "chosen-vision", tmp_path, Path("/ai-home"))
    assert "--image" in cmd and "--output-schema" in cmd and "--ephemeral" in cmd
    assert "--sandbox" in cmd and "read-only" in cmd
    assert "--ignore-user-config" in cmd and "shell_tool" in cmd
    assert env == {"CODEX_HOME": "/ai-home/.codex"}
    cmd, _ = cli_command("claude", "chosen-vision", tmp_path, Path("/ai-home"))
    assert "--bare" in cmd and "--json-schema" in cmd and "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--tools") + 1] == "Read"
    assert "--dangerously-skip-permissions" not in cmd
    with pytest.raises(ValueError, match="agy"):
        UnsupportedAI().extract(None, [])


def test_claude_runner_env_never_inherits_bridge_secrets(tmp_path, monkeypatch):
    from receipt_bridge import ai

    monkeypatch.setenv("DUET_APP_PASSWORD", "NEVER_PASS_THIS")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "NEVER_PASS_THIS_EITHER")
    monkeypatch.setattr(ai.shutil, "which", lambda _: "/bin/claude")
    (tmp_path / "anthropic-api-key").write_text("TEST_AI_KEY")
    seen = {}

    class Process:
        returncode = 0

        def __init__(self, cmd, **kwargs):
            seen.update(kwargs)
            kwargs["stdout"].write(
                json.dumps({"structured_output": sample_extraction().model_dump()}).encode()
            )

        def communicate(self, data, timeout):
            seen["input"] = data.decode()

    monkeypatch.setattr(ai.subprocess, "Popen", Process)
    result = run_cli("claude", "chosen-vision", sample_image(), CATEGORIES, tmp_path, 30)
    assert result.amount == "12000"
    assert "DUET_APP_PASSWORD" not in seen["env"] and "TELEGRAM_BOT_TOKEN" not in seen["env"]
    assert "NEVER_PASS_THIS" not in json.dumps(seen["env"])
    assert "receipt.jpg" in seen["input"]


def test_telegram_poll_download_and_preview_multipart():
    calls = []
    data = sample_image()

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("/getUpdates"):
            assert b"offset=5" in request.content and b"timeout=30" in request.content
            return httpx.Response(200, json={"ok": True, "result": []})
        if request.url.path.endswith("/getFile"):
            return httpx.Response(
                200, json={"ok": True, "result": {"file_path": "photos/test.png", "file_size": len(data)}}
            )
        if "/file/" in request.url.path:
            return httpx.Response(200, content=data)
        if request.url.path.endswith("/sendMessage"):
            assert b"parse_mode" not in request.content
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 11}})
        raise AssertionError(request.url.path)

    telegram = Telegram("TEST_TOKEN", transport=httpx.MockTransport(handle))
    assert telegram.poll(5) == []
    assert telegram.download("TEST_FILE") == data
    telegram.send(1, "test <untrusted>")
    assert len(calls) == 4
    telegram.close()


def test_telegram_errors_and_oversize_do_not_expose_token():
    telegram = Telegram(
        "SUPER_SECRET",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(429, headers={"Retry-After": "3"}, json={"error": "SUPER_SECRET"})
        ),
    )
    with pytest.raises(RemoteError) as raised:
        telegram.poll(0)
    assert raised.value.retry_after == 3
    assert "SUPER_SECRET" not in str(raised.value)
    telegram.close()
    telegram = Telegram(
        "SUPER_SECRET",
        max_download_mb=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"ok": True, "result": {"file_size": 2_000_000}})
        ),
    )
    with pytest.raises(ValueError, match="크기"):
        telegram.download("TEST_FILE")
    telegram.close()


def test_ledger_redirect_refused_and_errors_redacted():
    ledger = Ledger(
        "http://mock.invalid/api/v1",
        "SECRET",
        httpx.MockTransport(lambda _: httpx.Response(302, headers={"Location": "https://elsewhere.invalid"})),
    )
    with pytest.raises(RemoteError) as raised:
        ledger.context("test")
    assert raised.value.status == 302
    assert "SECRET" not in str(raised.value)
    ledger.close()


def test_runner_only_receives_image_and_categories(tmp_path):
    path = tmp_path / "receipt.jpg"
    path.write_bytes(sample_image())

    def handle(request):
        body = json.loads(request.content)
        assert set(body) == {"image", "categories", "provider", "model"}
        assert body["provider"] == "codex" and body["model"] == "chosen-vision"
        assert b"password" not in request.content
        assert request.headers["Authorization"] == "Bearer " + "T" * 32
        return httpx.Response(200, json=sample_extraction().model_dump())

    runner = RunnerAI(
        "http://mock.invalid", 30, "codex", "chosen-vision", httpx.MockTransport(handle), token="T" * 32
    )
    assert runner.extract(path, CATEGORIES).merchant
    runner.close()


def test_antigravity_uses_documented_text_protocol_not_image_flags(tmp_path, monkeypatch):
    from receipt_bridge import ai

    monkeypatch.setattr(ai.shutil, "which", lambda _: "/bin/agy")
    seen = {}

    class Process:
        returncode = 0

        def __init__(self, cmd, **kwargs):
            seen["cmd"], seen["env"] = cmd, kwargs["env"]
            result = {
                "event": "result",
                "result": {"status": "SUCCESS", "structured_output": sample_extraction().model_dump()},
            }
            kwargs["stdout"].write((json.dumps(result) + "\n").encode())

        def communicate(self, data, timeout):
            seen["input"] = json.loads(data)

    monkeypatch.setattr(ai.subprocess, "Popen", Process)
    result = run_cli(
        "agy", "test-model", None, CATEGORIES, tmp_path, 30, ocr_text="TEST RECEIPT Total KRW 12000"
    )
    assert result.amount == "12000"
    assert "--input-format" in seen["cmd"] and "--json-schema" in seen["cmd"]
    assert "--image" not in seen["cmd"] and "--dangerously-skip-permissions" not in seen["cmd"]
    assert seen["input"]["event"] == "user"
    assert "TEST RECEIPT" in seen["input"]["message"]["content"]
    policy = json.loads((tmp_path / ".gemini/antigravity-cli/settings.json").read_text())
    assert "command(*)" in policy["permissions"]["deny"]
    assert "mcp(*)" in policy["permissions"]["deny"]


def test_antigravity_sends_only_ocr_text_and_always_requests_confirmation(tmp_path, monkeypatch):
    from receipt_bridge import images

    path = tmp_path / "test.jpg"
    path.write_bytes(sample_image())
    monkeypatch.setattr(images, "local_ocr", lambda *_: "TEST RECEIPT Total 12000")
    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        assert "image" not in body and "text" in body
        assert body["provider"] == "agy"
        return httpx.Response(200, json=sample_extraction().model_dump())

    runner = RunnerAI(
        "http://mock.invalid", 30, "agy", "test-model", httpx.MockTransport(handle), token="T" * 32
    )
    assert runner.extract(path, CATEGORIES).warnings
    monkeypatch.setattr(images, "local_ocr", lambda *_: "")
    with pytest.raises(RemoteError):
        runner.extract(path, CATEGORIES)
    assert len(calls) == 1  # No fallback provider or image transmission.
    runner.close()
