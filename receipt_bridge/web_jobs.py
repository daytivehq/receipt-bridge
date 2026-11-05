"""Authenticated browser intake and controls, sharing the receipt worker's validation."""

from __future__ import annotations

import hashlib
import re
from contextlib import closing, nullcontext
from datetime import datetime
from email import policy
from email.parser import BytesParser
from zoneinfo import ZoneInfo

from PIL import Image

from .config import configured
from .images import atomic_write, load_image
from .ledger import Ledger
from .service import Service
from .store import dumps


def parse_upload(content_type, body):
    if len(content_type) > 300 or "\r" in content_type or "\n" in content_type:
        raise ValueError("올바른 파일 업로드 요청이 아닙니다")
    header = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + content_type + "\r\n\r\n").encode()
    )
    boundary = header.get_boundary()
    if not boundary or not re.fullmatch(r"[a-zA-Z0-9'()+_,./:=?-]{1,70}", boundary):
        raise ValueError("올바른 업로드 경계가 필요합니다")
    # Bound the number of parts before constructing MIME objects.
    if body.count(b"--" + boundary.encode()) > 4:
        raise ValueError("사진은 요청당 한 장씩 업로드하세요")
    message = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body
    )
    if not message.is_multipart() or message.defects:
        raise ValueError("파일 업로드 형식을 확인하세요")
    fields = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name not in {"file", "account", "caption"} or name in fields or part.is_multipart():
            raise ValueError("파일 업로드 항목을 확인하세요")
        value = part.get_payload(decode=True)
        if not isinstance(value, bytes):
            raise ValueError("파일 업로드 내용을 확인하세요")
        if name != "file":
            if len(value) > 16384:
                raise ValueError("설명이 너무 깁니다")
            value = value.decode("utf-8", errors="strict")
        fields[name] = value
    if "file" not in fields or "account" not in fields:
        raise ValueError("사진과 저장 계좌가 필요합니다")
    return fields


class WebJobs:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store

    def ledger(self):
        if not configured(self.settings.ledger_password):
            raise ValueError("서비스 설정에서 가계부 주소와 앱 비밀번호를 입력하세요")
        return closing(Ledger(self.settings.ledger_url, self.settings.ledger_password.get_secret_value()))

    def accounts(self):
        with self.ledger() as ledger:
            accounts = ledger.request("GET", "accounts")
        return [
            {key: account[key] for key in ("id", "name", "currency")}
            for account in accounts
            if not account.get("archived") and account.get("role") in {"owner", "editor"}
        ]

    def upload(self, key, data, account, caption=""):
        if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{16,100}", key):
            raise ValueError("업로드 요청 키가 필요합니다. 화면을 새로고침하세요")
        if not isinstance(account, str) or not 1 <= len(account) <= 200:
            raise ValueError("저장 계좌를 선택하세요")
        if not isinstance(caption, str) or len(caption) > 4096:
            raise ValueError("사진 설명은 4,096자 이하로 입력하세요")
        if not 0 < len(data) <= self.settings.max_download_mb * 1024 * 1024:
            raise ValueError("사진 크기가 수신 한도를 넘었습니다")
        checks = self.settings.readiness()
        if not checks["ledger"] or not checks["ai"]:
            raise ValueError(
                "서비스 설정에서 가계부와 AI 설정을 완료하세요. Telegram 설정은 필요하지 않습니다"
            )
        try:
            load_image(data).close()  # Inspect bytes, never trust filenames or MIME labels.
        except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise ValueError("JPG·PNG·WebP 단일 사진인지, 4천만 화소 이하인지 확인하세요") from None
        with self.ledger() as ledger:
            selected, _ = ledger.context(account)
            if selected.get("archived") or selected.get("role") not in {"owner", "editor"}:
                raise ValueError("저장할 수 없는 계좌입니다")
        metadata = dumps({"account": account, "caption": caption}).encode()
        digest = hashlib.sha256(metadata + b"\0" + data).hexdigest()
        message = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") & ((1 << 63) - 1)
        reference = datetime.now(ZoneInfo(self.settings.timezone)).date().isoformat()
        with self.store.tx():
            job = self.store.create_job(
                0,
                0,
                message,
                "web:" + key,
                account,
                adapter="web",
                input_text=caption,
                reference_date=reference,
            )
            if job["upload_digest"]:
                if job["file_id"] != "web:" + key or job["upload_digest"] != digest:
                    raise ValueError("같은 업로드 키로 다른 내용을 보낼 수 없습니다")
                return job
            original = self.settings.data_dir / "receipts" / job["id"] / "original.bin"
            atomic_write(original, data)
            self.store.update(job["id"], original=str(original), upload_digest=digest)
            return self.store.get(job["id"])

    def categories(self, job):
        with self.ledger() as ledger:
            _, categories = ledger.context(job["account"])
        return [
            {"code": c["code"], "name": c["name"]}
            for c in categories
            if c.get("kind") == "expense" and not c.get("hidden")
        ]

    def control(self, job_id, data):
        if not isinstance(data, dict) or not data.keys() <= {"action", "revision", "values"}:
            raise ValueError("작업 요청 항목을 확인하세요")
        if type(data.get("revision")) is not int:
            raise ValueError("최신 작업 내용을 불러오세요")
        with self.ledger() if data.get("action") in {"confirm", "edit"} else nullcontext(None) as ledger:
            initial = self.store.get(job_id)
            if not initial:
                raise ValueError("작업을 찾지 못했습니다")
            context = (
                ledger.context(initial["account"]) if data.get("action") in {"confirm", "edit"} else None
            )
            controller = Service(self.settings, self.store, None, None, ledger)
            with self.store.tx():
                job = self.store.get(job_id)
                if job["revision"] != data["revision"] or job["account"] != initial["account"]:
                    raise ValueError("작업 내용이 변경됐습니다. 최신 내용을 확인하세요")
                action = data.get("action")
                if action == "confirm":
                    controller.confirm(job, context)
                elif action == "edit":
                    controller.editable(job)
                    values = data.get("values")
                    if not isinstance(values, dict) or "account" in values:
                        raise ValueError("수정할 거래 정보를 확인하세요")
                    controller.edit_values(job, values, context)
                elif action == "cancel":
                    controller.cancel(job)
                    controller.status(self.store.get(job_id))
                elif action == "retry":
                    controller.retry(job)
                else:
                    raise ValueError("지원하지 않는 작업입니다")
                self.store.log("info", "admin", "웹 작업 처리 · " + action, job_id)
                return self.store.get(job_id)
