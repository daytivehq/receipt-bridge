from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    merchant: str | None = Field(max_length=200)
    date: str | None = Field(max_length=32)
    time: str | None = Field(max_length=32)
    amount: str | None = Field(max_length=64)  # decimal major units, never float
    currency: str | None = Field(max_length=16)
    category: str | None = Field(max_length=200)
    subtotal: str | None = Field(max_length=64)
    tax: str | None = Field(max_length=64)
    total_evidence: str | None = Field(max_length=300)
    date_evidence: str | None = Field(max_length=300)
    warnings: list[Annotated[str, Field(max_length=500)]] = Field(max_length=20)


def minor_units(value: str | None, scale: int) -> str:
    if value is None or not re.fullmatch(r"[0-9]{1,16}(?:\.[0-9]{1,3})?", value):
        raise ValueError("금액은 쉼표 없는 양수 숫자 문자열이어야 합니다")
    if scale not in range(4):
        raise ValueError("지원하지 않는 계좌 소수 자릿수입니다")
    number = Decimal(value) * (10**scale)
    if number != number.to_integral_value() or number <= 0:
        raise ValueError("금액의 소수 자릿수 또는 양수를 확인하세요")
    return str(int(number))


def transaction(
    ex: Extraction, account: dict, categories: list[dict], timezone: str, max_amount: int
) -> dict:
    if account.get("archived") or account.get("role") not in {"owner", "editor"}:
        raise ValueError("보관된 계좌 또는 쓰기 권한이 없는 계좌입니다")
    if not ex.merchant or not ex.merchant.strip():
        raise ValueError("상호명이 필요합니다")
    if ex.currency != account["currency"]:
        raise ValueError("영수증과 계좌 통화가 다릅니다. 환율은 추측하지 않습니다")
    try:
        if ex.date is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ex.date):
            raise ValueError()
        day = date.fromisoformat(ex.date)
        if not 1900 <= day.year <= 2100 or day > datetime.now(ZoneInfo(timezone)).date():
            raise ValueError()
    except ValueError:
        raise ValueError("결제 날짜가 없거나 올바르지 않거나 미래 날짜입니다") from None
    if ex.time is not None and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", ex.time):
        raise ValueError("시간은 HH:mm 형식이어야 합니다")
    amount = minor_units(ex.amount, account["scale"])
    if int(amount) > max_amount:
        raise ValueError("설정된 최대 금액을 넘었습니다")
    valid = {c["code"] for c in categories if c.get("kind") == "expense" and not c.get("hidden")}
    if ex.category not in valid:
        raise ValueError("계좌에 없는 지출 분류입니다. /categories로 확인하세요")
    payload = {
        "account_id": account["id"],
        "kind": "expense",
        "date": ex.date,
        "timezone": timezone,
        "amount": amount,
        "title": ex.merchant.strip(),
        "category": ex.category,
        "note": "receipt-bridge",
    }
    if ex.time:
        payload["time"] = ex.time
    return payload


def fingerprint(payload: dict, currency: str) -> str:
    merchant = re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", payload["title"]).casefold())
    value = [payload["account_id"], merchant, payload["date"], payload["amount"], currency]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def auto_eligible(
    ex: Extraction,
    payload: dict,
    ocr: str,
    settings,
    duplicates: list,
    image_warnings: list[Annotated[str, Field(max_length=500)]],
) -> bool:
    if not settings.auto_save or duplicates or ex.warnings or image_warnings or not ex.time:
        return False
    if int(payload["amount"]) > settings.auto_max_amount_minor:
        return False
    age = (datetime.now(ZoneInfo(settings.timezone)).date() - date.fromisoformat(payload["date"])).days
    if not 0 <= age <= settings.auto_max_age_days:
        return False
    # Independent local OCR must contain a dated line and a final-total line matching AI evidence.
    if not ocr or not ex.total_evidence or not ex.date_evidence:
        return False

    def compact(s):
        return re.sub(r"\s", "", s).casefold()

    if any(compact(e) not in compact(ocr) for e in [ex.total_evidence, ex.date_evidence]):
        return False
    if not re.search(r"합계|총액|결제금액|승인금액|total", ex.total_evidence, re.IGNORECASE):
        return False
    amounts = re.findall(r"(?<![\d.,])\d[\d,]*(?:\.\d{1,3})?(?![\d.,])", ex.total_evidence)
    if not any(Decimal(a.replace(",", "")) == Decimal(ex.amount) for a in amounts):
        return False
    digits = re.sub(r"\D", "", ex.date_evidence)
    if payload["date"].replace("-", "") not in digits:
        return False
    # Arithmetic is an additional condition, not a confidence-score decision.
    try:
        if ex.subtotal is None or ex.tax is None:
            return False
        if not all(re.fullmatch(r"\d+(?:\.\d{1,3})?", x) for x in [ex.subtotal, ex.tax]):
            return False
        return Decimal(ex.subtotal) + Decimal(ex.tax) == Decimal(ex.amount)
    except Exception:
        return False


class TextExtractions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    items: list[Extraction] = Field(max_length=20)
