"""Ground text facts in the submitted message, without executing any instructions."""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from .models import Extraction


def compact(value):
    return re.sub(r"\s", "", value).casefold()


def money_values(text):
    values = set()
    for number, unit in re.findall(r"(?<![\d.,+\-])(\d[\d,]*(?:\.\d{1,3})?)\s*(만|천)?(?![\d.,])", text):
        if re.fullmatch(r"\d+(?:\.\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?", number):
            values.add(Decimal(number.replace(",", "")) * {"만": 10000, "천": 1000, "": 1}[unit])
    return values


def supported_date(evidence, reference):
    value = compact(evidence)
    candidates = set()
    for word, days in (("그저께", 2), ("그제", 2), ("어제", 1), ("오늘", 0), ("yesterday", 1), ("today", 0)):
        if word in value:
            candidates.add((date.fromisoformat(reference) - timedelta(days=days)).isoformat())
    for match in re.finditer(r"(?<!\d)(\d{4})[-./년](\d{1,2})[-./월](\d{1,2})(?:일)?(?!\d)", value):
        try:
            candidates.add(date(*(int(x) for x in match.groups())).isoformat())
        except ValueError:
            return None
    return next(iter(candidates)) if len(candidates) == 1 else None


def explicit_currency(text):
    patterns = {
        "KRW": r"₩|원화|\d\s*원",
        "USD": r"미국\s*달러",
        "EUR": r"€|유로",
        "JPY": r"\d\s*엔",
        "GBP": r"£|파운드",
        "CNY": r"위안",
        "CAD": r"캐나다\s*달러",
        "AUD": r"호주\s*달러",
    }
    currencies = {
        code
        for code, pattern in patterns.items()
        if re.search(r"(?<![a-zA-Z])" + code + r"(?![a-zA-Z])|" + pattern, text, re.I)
    }
    return next(iter(currencies)) if len(currencies) == 1 else None


def ground_text(ex: Extraction, text: str, reference: str, currency: str, *, annotation=False):
    """Unverified numeric/date facts become missing fields for explicit user repair."""
    result = ex.model_copy(deep=True)
    warnings = result.warnings[:14]
    source = compact(text)
    if result.merchant and compact(result.merchant) not in source:
        result.merchant = None
        warnings.append("입력에서 상호명을 확인하지 못했습니다")
    if result.amount is not None:
        evidence = result.total_evidence
        try:
            valid = bool(
                evidence and compact(evidence) in source and Decimal(result.amount) in money_values(evidence)
            )
        except Exception:
            valid = False
        if not valid:
            result.amount = None
            warnings.append("입력에서 금액 근거를 확인하지 못했습니다. 금액을 지정하세요")
    if result.date is not None:
        evidence = result.date_evidence
        grounded = supported_date(evidence, reference) if evidence and compact(evidence) in source else None
        if grounded:
            result.date = grounded
        else:
            result.date = None
            warnings.append("날짜를 명시하거나 오늘·어제처럼 입력하세요")
    if result.time and result.time not in text:
        result.time = None
        warnings.append("입력에 없는 결제 시간은 사용하지 않습니다")
    money_evidence = (
        result.total_evidence if result.total_evidence and compact(result.total_evidence) in source else text
    )
    explicit = explicit_currency(money_evidence)
    if explicit:
        result.currency = explicit
    elif annotation and result.currency and result.currency.casefold() not in source:
        result.currency = None
    if not result.currency and not annotation:
        if re.search(
            r"[$€£¥₩]|달러|유로|위안|(?<![a-zA-Z])(?:KRW|USD|EUR|JPY|GBP|CNY|CAD|AUD|SGD|HKD|NZD|CHF|THB|TWD)(?![a-zA-Z])",
            money_evidence,
        ):
            warnings.append("입력의 통화를 확인하고 currency=코드로 지정하세요")
        else:
            result.currency = currency
            warnings.append("통화 미기재: 저장 계좌의 통화를 사용합니다")
    result.subtotal = result.tax = None
    result.warnings = warnings[:20]
    return result


def merge_caption(receipt: Extraction, annotation: Extraction):
    merged = receipt.model_copy(deep=True)
    conflicts = {}
    for field in ("merchant", "date", "time", "amount", "currency", "category"):
        value = getattr(annotation, field)
        original = getattr(merged, field)
        if value is None:
            continue
        different = original is not None and original != value
        if field == "amount" and different:
            try:
                different = Decimal(original) != Decimal(value)
            except Exception:
                pass
        if field in {"date", "time", "amount", "currency"} and different:
            conflicts[field] = [original, value]
        else:
            setattr(merged, field, value)
    merged.warnings = (receipt.warnings + annotation.warnings)[:20]
    return merged, conflicts


def conflict_message(conflicts):
    labels = {"amount": "금액", "date": "날짜", "time": "시간", "currency": "통화"}
    return "; ".join(
        f"{labels[field]} 불일치: 사진 {values[0]} / 설명 {values[1]} · /edit 작업ID {field}=값으로 선택하세요"
        for field, values in conflicts.items()
    )
