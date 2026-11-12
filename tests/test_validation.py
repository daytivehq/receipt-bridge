from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from receipt_bridge.config import Settings, load_settings
from receipt_bridge.models import Extraction, auto_eligible, minor_units, transaction
from tests.fakes import ACCOUNT, CATEGORIES, sample_extraction


@pytest.mark.parametrize(
    "amount,scale,want",
    [
        ("12000", 0, "12000"),
        ("12.34", 2, "1234"),
        ("1.234", 3, "1234"),
        ("9000000000000", 0, "9000000000000"),
    ],
)
def test_exact_amounts(amount, scale, want):
    assert minor_units(amount, scale) == want


@pytest.mark.parametrize(
    "value,scale",
    [("1.01", 0), ("12.345", 2), ("0", 0), ("-1", 0), ("1e6", 0), ("NaN", 2), ("12,000", 0), (None, 0)],
)
def test_bad_amounts(value, scale):
    with pytest.raises(ValueError):
        minor_units(value, scale)


@pytest.mark.parametrize(
    "changes",
    [
        {"date": None},
        {"date": "2026-02-30"},
        {"date": "2101-01-01"},
        {"date": "2099-01-01"},
        {"time": "24:30"},
        {"currency": "USD"},
        {"category": "nonexistent"},
        {"amount": "9000000000001"},
    ],
)
def test_validation_blocks_bad_data(changes):
    with pytest.raises(ValueError):
        transaction(sample_extraction(**changes), ACCOUNT, CATEGORIES, "Asia/Seoul", 9000000000000)


def test_schema_does_not_coerce_numeric_amount_or_accept_extra_fields():
    data = sample_extraction().model_dump()
    data["amount"] = 12000
    with pytest.raises(ValidationError):
        Extraction.model_validate(data)
    data["amount"] = "12000"
    data["execute"] = "ignore safeguards"
    with pytest.raises(ValidationError):
        Extraction.model_validate(data)


def test_auto_save_requires_independent_evidence_and_no_warnings():
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    ex = sample_extraction(
        date=today, date_evidence=today, subtotal="11000", tax="1000", total_evidence="총액 12,000"
    )
    settings = Settings(auto_save=True)
    payload = transaction(ex, ACCOUNT, CATEGORIES, settings.timezone, settings.max_amount_minor)
    ocr = f"{today}\n총액 12,000"
    assert auto_eligible(ex, payload, ocr, settings, [], [])
    for duplicates, image_warnings, text in [
        ([{"id": "old"}], [], ocr),
        ([], ["잘림 경고"], ocr),
        ([], [], ""),
        ([], [], "총액 11,000"),
    ]:
        assert not auto_eligible(ex, payload, text, settings, duplicates, image_warnings)
    assert not auto_eligible(ex.model_copy(update={"warnings": ["불명확"]}), payload, ocr, settings, [], [])
    assert not auto_eligible(ex.model_copy(update={"tax": "900"}), payload, ocr, settings, [], [])
    assert not auto_eligible(ex.model_copy(update={"time": None}), payload, ocr, settings, [], [])
    old = (datetime.now(ZoneInfo(settings.timezone)).date() - timedelta(days=10)).isoformat()
    assert not auto_eligible(
        ex.model_copy(update={"date": old}), {**payload, "date": old}, ocr, settings, [], []
    )


def test_settings_do_not_leak_secrets_and_load_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(
        'allowed_users = [1]\nallowed_chats = [1]\nai_model = "test-vision"\n[user_accounts]\n"1" = "test"'
    )
    secret = tmp_path / "token"
    secret.write_text("SUPER_SECRET_TOKEN\n")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(secret))
    monkeypatch.setenv("DUET_APP_PASSWORD", "SUPER_SECRET_PASSWORD")
    monkeypatch.setenv("AI_RUNNER_TOKEN", "T" * 32)
    settings = load_settings(path)
    settings.check_runtime()
    assert "SUPER_SECRET" not in repr(settings)
    assert settings.telegram_token.get_secret_value() == "SUPER_SECRET_TOKEN"
    assert not Settings().authorized(1, 1)
    settings.ai_provider = "codex"
    with pytest.raises(ValueError, match="allow_external_ai"):
        settings.check_runtime()
    settings.allow_external_ai = True
    settings.ai_provider = "agy"
    settings.check_runtime()


@pytest.mark.parametrize(
    "value,currency,expected",
    [
        ("100000000", "KRW", "100,000,000원"),
        ("1234.50", "USD", "1,234.50 USD"),
        ("9007199254740993.010", "USD", "9,007,199,254,740,993.010 USD"),
        ("0", "KRW", "0원"),
        (None, "KRW", "읽지 못함"),
        ("", "KRW", "읽지 못함"),
    ],
)
def test_display_amount_formats_without_changing_stored_value(value, currency, expected):
    from receipt_bridge.models import display_amount

    assert display_amount(value, currency) == expected
