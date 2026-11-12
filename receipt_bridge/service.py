from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import telegram_identity
from .images import atomic_write, local_ocr, process_image
from .ledger import RemoteError
from .messenger import check_telegram_size, identity
from .models import Extraction, TextExtractions, auto_eligible, fingerprint, transaction
from .store import dumps
from .text_input import conflict_message, ground_text, merge_caption

HELP = """영수증 사진·이미지 파일·지출 텍스트를 보내세요. 여러 건도 각각 확인 후 저장합니다.
예: 오늘 AA에서 5000원, BB에서 43,500원 썼어. 사진 설명도 반영합니다.
/pending — 처리 중·확인 대기 목록
/status 작업ID — 상태와 결과 다시 보기
/categories 작업ID — 해당 계좌의 지출 분류
/edit 작업ID amount=12000 date=2026-10-31 time=12:30 currency=KRW category=food
/edit 작업ID merchant=상호명 (공백 포함 가능, 상호명은 단독 수정)
/edit 작업ID account=계좌ID
/rotate 작업ID 90 — 시계 방향 회전 (90·180·270)
/original 작업ID — 자르지 않은 원본 구도로 다시 분석
/retry 작업ID — 실패 단계 재시도
/cancel 작업ID — 저장 전 취소
금액은 통화의 기본 단위(USD 12.34), 시간 삭제는 time=null.
수정·재분석 뒤에는 새 확인 버튼을 누르세요."""


class Service:
    def __init__(self, settings, store, messenger, ai, ledger, ocr=local_ocr):
        self.settings, self.store, self.messenger = settings, store, messenger
        self.ai, self.ledger, self.ocr = ai, ledger, ocr
        self.settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def authorized_update(self, update):
        user, chat = identity(update)
        return self.settings.authorized(user, chat)

    def update_key(self, update):
        bot = telegram_identity(self.settings.telegram_token)
        return f"update:{bot}:{update['update_id']}" if bot else f"update:{update['update_id']}"

    def require_account(self, job, account=None):
        if job["adapter"] == "web":
            return  # Browser intake is admin-authenticated; ledger roles are rechecked before saving.
        if not self.settings.account_allowed(job["user"], job["chat"], account or job["account"]):
            raise ValueError(
                "이 사용자·대화방에 허용된 저장 계좌가 아닙니다. 관리자에게 계좌 설정을 요청하세요"
            )

    def prepare_context(self, update):
        """Fetch remote data before the inbox transaction; ownership is rechecked on commit."""
        if not self.authorized_update(update):
            return None
        user, chat = identity(update)
        try:
            cb = update.get("callback_query")
            if cb:
                parts = cb.get("data", "").split(":")
                if len(parts) != 4 or parts[:2] != ["rb", "confirm"]:
                    return None
                job = self.owned(parts[2], user, chat)
                account = job["account"]
            else:
                parts = update.get("message", {}).get("text", "").strip().split(maxsplit=2)
                if len(parts) < 2 or parts[0].split("@")[0] not in {"/edit", "/categories"}:
                    return None
                job = self.owned(parts[1], user, chat)
                account = job["account"]
                if (
                    parts[0].split("@")[0] == "/edit"
                    and len(parts) == 3
                    and not parts[2].startswith("merchant=")
                ):
                    for pair in parts[2].split():
                        if pair.startswith("account="):
                            account = pair.split("=", 1)[1]
            self.require_account(job, account)
            return self.ledger.context(account)
        except (ValueError, RemoteError) as exc:
            return exc

    def reply(self, update, chat, text):
        self.store.notify(self.update_key(update), chat, text)

    def owned(self, job_id, user, chat):
        job = self.store.get(job_id)
        if not job or job["user"] != user or job["chat"] != chat:
            raise ValueError("이 사용자의 작업을 찾을 수 없습니다")
        return job

    def editable(self, job):
        if job["payload"] or job["posting_id"] or job["state"] in {"done", "cancelled"}:
            raise ValueError("저장 요청이 시작된 작업은 수정·취소할 수 없습니다. 상태를 확인하세요")
        if job["state"] not in {"waiting", "failed"}:
            raise ValueError("분석이 끝난 뒤 다시 시도하세요")

    def handle_update(self, update, context=None, answer=True):
        if not self.authorized_update(update):
            return
        user, chat = identity(update)
        cb = update.get("callback_query")
        try:
            if isinstance(context, Exception):
                raise context
            if cb:
                # Only the owner can use a button, even in an allowed group chat.
                parts = cb.get("data", "").split(":")
                if len(parts) != 4 or parts[0] != "rb":
                    raise ValueError("지원하지 않는 버튼입니다")
                _, action, job_id, revision = parts
                job = self.owned(job_id, user, chat)
                if str(job["revision"]) != revision:
                    raise ValueError("이전 결과의 버튼입니다. /status로 최신 결과를 확인하세요")
                if action == "confirm":
                    self.confirm(job, context)
                elif action == "cancel":
                    self.cancel(job)
                    self.reply(update, chat, f"{job_id}: 취소했습니다. 보관한 원본은 남아 있습니다")
                elif action == "edit":
                    self.reply(update, chat, HELP)
                else:
                    raise ValueError("지원하지 않는 버튼입니다")
                try:
                    if answer:
                        self.messenger.answer(cb["id"])
                except RemoteError:
                    pass
                return
            message = update["message"]
            file_id = None
            if message.get("photo"):
                file_id = message["photo"][-1]["file_id"]
            elif message.get("document"):
                doc = message["document"]
                if doc.get("mime_type") not in {"image/jpeg", "image/png", "image/webp"}:
                    raise ValueError("JPG·PNG·WebP 이미지 파일을 보내세요")
                check_telegram_size(doc.get("file_size", 0), self.settings.max_download_mb * 1024 * 1024)
                file_id = doc["file_id"]
            text = message.get("text", "").strip()
            if file_id or (text and not text.startswith("/")):
                self.receive_input(update, message, file_id, user, chat)
                return
            parts = text.split(maxsplit=2)
            command = parts[0].split("@")[0] if parts else "/help"
            if command in {"/start", "/help"}:
                self.reply(update, chat, HELP)
                return
            if command == "/pending":
                jobs = self.store.pending(user, chat)
                self.reply(
                    update,
                    chat,
                    "\n".join(f"{j['id']}: {j['state']}" for j in jobs) or "대기 작업이 없습니다",
                )
                return
            if len(parts) < 2:
                raise ValueError("작업ID가 필요합니다. /help를 확인하세요")
            job = self.owned(parts[1], user, chat)
            if command == "/status":
                self.status(job, self.update_key(update))
            elif command == "/categories":
                _, cats = context or self.ledger.context(job["account"])
                self.reply(update, chat, "\n".join(f"{c['code']}: {c['name']}" for c in cats))
            elif command == "/retry":
                self.retry(job)
                self.reply(update, chat, f"{job['id']}: 실패한 단계부터 다시 시도합니다")
            elif command == "/cancel":
                self.cancel(job)
                self.reply(update, chat, f"{job['id']}: 취소했습니다. 원본은 보관됩니다")
            elif command == "/edit":
                self.editable(job)
                if len(parts) < 3 or not job["extraction"]:
                    raise ValueError("분석 결과가 필요합니다. /retry로 다시 분석하세요")
                self.edit(job, parts[2], context)
            elif command in {"/rotate", "/original"}:
                self.editable(job)
                if job["input_kind"] == "text":
                    raise ValueError("텍스트 작업에는 사진이 없습니다. /edit로 내용을 수정하세요")
                fields = {"use_original": 1} if command == "/original" else {}
                if command == "/rotate":
                    if len(parts) < 3 or parts[2] not in {"90", "180", "270"}:
                        raise ValueError("회전은 90·180·270 중 하나로 지정하세요")
                    fields["rotation"] = (job["rotation"] + int(parts[2])) % 360
                self.store.update(
                    job["id"],
                    state="received",
                    revision=job["revision"] + 1,
                    attempts=0,
                    next_at=0,
                    extraction=None,
                    fingerprint=None,
                    error=None,
                    **fields,
                )
                self.reply(update, chat, f"{job['id']}: 사진을 다시 분석합니다")
            else:
                self.reply(update, chat, HELP)
        except ValueError as exc:
            self.reply(update, chat, str(exc))
        except RemoteError as exc:
            self.reply(update, chat, f"{exc}. 잠시 후 같은 명령을 다시 보내세요")

    def receive_input(self, update, message, file_id, user, chat):
        account = self.settings.account_for(user, chat)
        if not account:
            raise ValueError("이 사용자 또는 채팅의 기본 계좌를 설정해 주세요")
        text = (message.get("caption", "") if file_id else message.get("text", "")).strip()
        if len(text) > 4096:
            raise ValueError("텍스트는 4,096자 이하로 보내세요")
        stamp = message.get("date", time.time())
        if type(stamp) not in (int, float) or not 0 <= stamp <= time.time() + 300:
            raise ValueError("메시지의 전송 날짜를 확인하세요")
        reference = datetime.fromtimestamp(stamp, ZoneInfo(self.settings.timezone)).date().isoformat()
        bot_id = telegram_identity(self.settings.telegram_token)
        job = self.store.create_job(
            chat,
            user,
            message["message_id"],
            file_id or "",
            account,
            adapter="telegram:" + bot_id if bot_id else "telegram",
            input_kind="image" if file_id else "text",
            input_text=text,
            reference_date=reference,
        )
        self.reply(update, chat, f"{job['id']}: {'영수증' if file_id else '지출 텍스트'}을 접수했습니다")

    def cancel(self, job):
        self.editable(job)
        self.store.update(job["id"], state="cancelled", revision=job["revision"] + 1)

    def retry(self, job):
        if job["state"] not in {"failed", "create_failed", "attach_failed"}:
            raise ValueError("실패한 작업만 재시도할 수 있습니다")
        stage = "attaching" if job["posting_id"] else "creating" if job["payload"] else "received"
        self.store.update(job["id"], state=stage, attempts=0, next_at=0, error=None)

    def edit(self, job, text, context=None):
        if text.startswith("merchant="):
            values = {"merchant": text.removeprefix("merchant=").strip()}
        else:
            values = {}
            for pair in text.split():
                if "=" not in pair:
                    raise ValueError("수정은 필드=값 형태로 입력하세요")
                key, value = pair.split("=", 1)
                values[key] = None if value == "null" else value
        self.edit_values(job, values, context)

    def edit_values(self, job, values, context=None):
        if not values or not values.keys() <= {
            "merchant",
            "account",
            "amount",
            "date",
            "time",
            "currency",
            "category",
        }:
            raise ValueError("지원하지 않는 수정 항목입니다")
        ex = json.loads(job["extraction"])
        conflicts = json.loads(job["conflicts"])
        account = values.get("account", job["account"])
        for key, value in values.items():
            if key != "account":
                ex[key] = value
                conflicts.pop(key, None)
        extraction = Extraction.model_validate(ex)
        # Allow incremental repair of several unreadable fields; confirmation still validates all.
        self.require_account(job, account)
        ac, cats = context or self.ledger.context(account)
        fp, error = None, None
        try:
            payload = transaction(
                extraction, ac, cats, self.settings.timezone, self.settings.max_amount_minor
            )
            fp = fingerprint(payload, ac["currency"])
            if conflicts:
                error = conflict_message(conflicts)
        except ValueError as exc:
            error = str(exc)
        self.store.update(
            job["id"],
            extraction=extraction.model_dump_json(),
            account=account,
            fingerprint=fp,
            revision=job["revision"] + 1,
            conflicts=dumps(conflicts),
            state="waiting",
            error=error,
        )
        self.status(self.store.get(job["id"]))

    def evaluate(self, job, context=None):
        self.require_account(job)
        if json.loads(job["conflicts"]):
            raise ValueError(conflict_message(json.loads(job["conflicts"])))
        ac, cats = context or self.ledger.context(job["account"])
        ex = Extraction.model_validate_json(job["extraction"])
        payload = transaction(ex, ac, cats, self.settings.timezone, self.settings.max_amount_minor)
        fp = fingerprint(payload, ac["currency"])
        self.store.update(job["id"], fingerprint=fp)
        duplicates = self.store.duplicates(job["id"], fp, job["image_hash"])
        return ex, payload, duplicates

    def confirm(self, job, context=None):
        if job["payload"] or job["state"] != "waiting":
            raise ValueError("이미 저장 요청을 받았거나 확인 대기 상태가 아닙니다")
        self.verify_image(job)
        _, payload, _ = self.evaluate(job, context)
        # Freeze the exact content and key BEFORE the first POST; no edits after this point.
        self.store.update(
            job["id"], state="creating", payload=dumps(payload), error=None, attempts=0, next_at=0
        )

    def status(self, job, key=None):
        if job["adapter"] == "web":
            return  # Browser jobs are tracked in the DB and never generate Telegram messages.
        key = key or f"status:{job['id']}:{job['revision']}:{job['state']}"
        lines = [f"작업 {job['id']} · {job['state']}", f"계좌: {job['account']}"]
        if job["input_kind"] == "text":
            lines.append("텍스트 지출 · 사진 첨부 없음")
        if job["batch_size"] > 1:
            lines.append(f"이 메시지의 {job['batch_size']}건 중 {job['part'] + 1}번째 · 각각 확인·저장하세요")
        if job["input_text"]:
            lines.append("입력: " + job["input_text"][:300])
        buttons = None
        if job["extraction"]:
            ex = Extraction.model_validate_json(job["extraction"])
            lines += [
                f"상호: {ex.merchant or '읽지 못함'}",
                f"결제: {ex.date or '읽지 못함'} {ex.time or '(시간 없음)'}",
                f"금액: {ex.amount or '읽지 못함'} {ex.currency or ''}",
                f"분류: {ex.category or '선택 필요'}",
            ]
            lines += ex.warnings[:3]
            duplicates = self.store.duplicates(job["id"], job["fingerprint"], job["image_hash"])
            if duplicates:
                lines.append("⚠ 중복 후보: " + ", ".join(d["id"] for d in duplicates[:5]))
                lines.append("기존 작업을 확인한 뒤 중복이어도 저장하려면 확인을 누르세요")
            if job["state"] == "waiting":
                buttons = {
                    "inline_keyboard": [
                        [
                            {"text": label, "callback_data": f"rb:{action}:{job['id']}:{job['revision']}"}
                            for label, action in [
                                ("확인·저장", "confirm"),
                                ("수정 방법", "edit"),
                                ("취소", "cancel"),
                            ]
                        ]
                    ]
                }
        lines += json.loads(job["image_warnings"])[:2]
        if job["error"]:
            lines.append("확인 필요: " + job["error"])
        if job["posting_id"]:
            lines.append("가계부 거래: " + job["posting_id"])
        if job["state"] in {"failed", "create_failed", "attach_failed"}:
            lines.append(f"재시도: /retry {job['id']}")
        if job["state"] == "attach_failed":
            lines.append("거래는 저장됐습니다. 사진 첨부만 재시도합니다")
        text = "\n".join(lines)
        # Photo caption limits: keep full result available in a separate message if necessary.
        image = Path(job["image"]) if job["image"] and Path(job["image"]).exists() else None
        if image and len(text) > 950:
            self.store.notify(key + ":image", job["chat"], f"{job['id']}: 보정 사진", image)
            image = None
        self.store.notify(key, job["chat"], text, image, buttons)

    def verify_image(self, job):
        if job["input_kind"] == "text":
            if not job["input_text"] or job["file_id"] or job["image"]:
                raise ValueError("텍스트 작업의 입력 정보를 확인하세요")
            return
        if not job["image"] or not Path(job["image"]).is_file():
            raise ValueError("보정 사진이 없습니다. 원본과 데이터 볼륨을 확인하세요")
        if hashlib.sha256(Path(job["image"]).read_bytes()).hexdigest() != job["image_hash"]:
            raise ValueError("확인한 사진과 현재 파일이 다릅니다. 보관 파일을 복원하세요")

    def work(self, job):
        stage = job["state"]
        try:
            self.require_account(job)
            if stage in {"received", "processing"}:
                self.analyze(job)
            elif stage == "creating":
                self.verify_image(job)
                # Recheck authorization and current account/category without changing frozen payload.
                payload = json.loads(job["payload"])
                ac, cats = self.ledger.context(payload["account_id"])
                ex = Extraction.model_validate_json(job["extraction"])
                checked = transaction(ex, ac, cats, self.settings.timezone, self.settings.max_amount_minor)
                if checked != payload:
                    raise ValueError("저장 요청과 현재 검증 결과가 다릅니다")
                posting = self.ledger.create(payload, job["request_key"])
                self.store.update(
                    job["id"],
                    posting_id=posting,
                    state="done" if job["input_kind"] == "text" else "attaching",
                    attempts=0,
                    next_at=0,
                    error=None,
                )
                if job["input_kind"] == "text":
                    self.status(self.store.get(job["id"]))
            elif stage == "attaching":
                self.verify_image(job)
                receipt = self.ledger.attach(job["posting_id"], Path(job["image"]))
                self.store.update(job["id"], receipt_id=receipt, state="done", attempts=0, error=None)
                self.status(self.store.get(job["id"]))
        except Exception as exc:
            self.fail(self.store.get(job["id"]), exc)

    def analyze(self, job):
        if job["input_kind"] == "text":
            self.analyze_text(job)
            return
        folder = self.settings.data_dir / "receipts" / job["id"]
        original = folder / "original.bin"
        output = folder / f"corrected-{job['revision']}.jpg"
        if not original.exists():
            if job["adapter"] == "web":
                raise ValueError("업로드 원본이 없습니다. 데이터 볼륨을 확인하세요")
            data = self.messenger.download(job["file_id"])
            # Preserve the exact received bytes before parsing or transforming them.
            atomic_write(original, data)
        self.store.update(job["id"], original=str(original), state="processing")
        notes, digest = process_image(original, output, job["rotation"], bool(job["use_original"]))
        self.store.update(job["id"], image=str(output), image_warnings=dumps(notes), image_hash=digest)
        account, cats = self.ledger.context(job["account"])
        extraction = self.ai.extract(output, cats)
        conflicts = {}
        if job["input_text"]:
            annotations = self.ai.extract_text(
                job["input_text"], cats, job["reference_date"], account["currency"], annotation=True
            )
            if len(annotations.items) > 1:
                raise ValueError(
                    "사진 한 장의 설명에는 한 지출만 입력하세요. 여러 지출 텍스트는 별도 메시지로 보내세요"
                )
            if annotations.items:
                annotation = ground_text(
                    annotations.items[0],
                    job["input_text"],
                    job["reference_date"],
                    account["currency"],
                    annotation=True,
                )
                extraction, conflicts = merge_caption(extraction, annotation)
        ocr = self.ocr(output, self.settings.ocr_languages)
        self.store.update(
            job["id"], extraction=extraction.model_dump_json(), ocr=ocr, conflicts=dumps(conflicts)
        )
        job = self.store.get(job["id"])
        error = None
        eligible = False
        try:
            ex, payload, duplicates = self.evaluate(job)
            eligible = (
                job["adapter"] != "web"
                and not job["input_text"]
                and auto_eligible(ex, payload, ocr, self.settings, duplicates, notes)
            )
        except ValueError as exc:
            error = str(exc)
        self.store.update(job["id"], state="waiting", attempts=0, next_at=0, error=error)
        self.status(self.store.get(job["id"]))
        if eligible:
            self.confirm(self.store.get(job["id"]))

    def analyze_text(self, job):
        self.store.update(job["id"], state="processing")
        account, cats = self.ledger.context(job["account"])
        batch = TextExtractions.model_validate(
            self.ai.extract_text(
                job["input_text"],
                cats,
                job["reference_date"],
                account["currency"],
            )
        )
        if not batch.items:
            raise ValueError("지출을 찾지 못했습니다. 상호명·금액·날짜를 입력하세요. 예: 오늘 AA에서 5000원")
        extractions = [
            ground_text(item, job["input_text"], job["reference_date"], account["currency"])
            for item in batch.items
        ]
        # All split items commit together. A crash must never leave a partially split message.
        with self.store.tx():
            for part, extraction in enumerate(extractions):
                current = (
                    job
                    if part == 0
                    else self.store.create_job(
                        job["chat"],
                        job["user"],
                        job["message"],
                        "",
                        job["account"],
                        adapter=job["adapter"] + ":part:" + str(part),
                        input_kind="text",
                        input_text=job["input_text"],
                        reference_date=job["reference_date"],
                    )
                )
                self.store.update(
                    current["id"],
                    extraction=extraction.model_dump_json(),
                    batch_size=len(extractions),
                    part=part,
                )
                error = None
                try:
                    self.evaluate(self.store.get(current["id"]), (account, cats))
                except ValueError as exc:
                    error = str(exc)
                self.store.update(current["id"], state="waiting", attempts=0, next_at=0, error=error)
                self.status(self.store.get(current["id"]))

    def fail(self, job, exc):
        self.store.log(
            "error",
            "worker",
            "처리 실패 · "
            + type(exc).__name__
            + (f" · HTTP {exc.status}" if isinstance(exc, RemoteError) else ""),
            job["id"],
        )
        attempts = job["attempts"] + 1
        # Only controlled errors may reach a user. Unexpected exceptions contain no details in logs.
        if isinstance(exc, RemoteError):
            detail = str(exc)
            retryable = exc.retryable
            delay = max(exc.retry_after, self.settings.retry_seconds * 2 ** min(attempts - 1, 7))
        elif isinstance(exc, ValueError):
            detail, retryable, delay = "입력을 확인하세요", False, 0
            # Pydantic errors can include untrusted AI data; return a generic message for them.
            if type(exc) is ValueError:
                detail = str(exc)
            else:
                detail = "AI 응답 또는 이미지 형식 검증에 실패했습니다"
        else:
            detail, retryable, delay = (
                "내부 처리 오류입니다. 로그의 작업ID와 파일 상태를 확인하세요",
                False,
                0,
            )
        if retryable and attempts < self.settings.max_attempts:
            self.store.update(job["id"], attempts=attempts, next_at=time.time() + delay, error=detail)
            self.store.notify(
                f"retry:{job['id']}:{job['revision']}:{job['state']}:{attempts}",
                job["chat"],
                f"{job['id']}: {detail}. {int(delay)}초 뒤 해당 단계만 재시도합니다",
            )
            return
        state = "attach_failed" if job["posting_id"] else "create_failed" if job["payload"] else "failed"
        self.store.update(job["id"], state=state, attempts=attempts, error=detail)
        self.status(self.store.get(job["id"]))

    def recover_notifications(self):
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT * FROM jobs WHERE state IN "
                "('waiting','done','failed','create_failed','attach_failed')"
            ).fetchall()
        for row in rows:
            job = dict(row)
            if self.settings.authorized(job["user"], job["chat"]):
                self.status(job)

    def tick(self, telegram_ready=True):
        update = self.store.next_update() if telegram_ready else None
        if update:
            update_id, body = update
            context = self.prepare_context(body)
            with self.store.tx():
                self.handle_update(body, context, answer=False)
                self.store.finish_update(update_id)
            callback = body.get("callback_query")
            if callback and self.authorized_update(body):
                try:
                    self.messenger.answer(callback["id"])
                except RemoteError:
                    pass
        job = None if self.store.setting("paused", False) else self.store.due_job(web_only=not telegram_ready)
        if job:
            # Permission removal in config also stops queued jobs after a restart.
            if job["adapter"] == "web" or self.settings.authorized(job["user"], job["chat"]):
                self.work(job)
            else:
                self.store.update(job["id"], next_at=time.time() + 300)
        notification = self.store.next_notification() if telegram_ready else None
        if notification and notification["chat"] not in self.settings.allowed_chats:
            self.store.notification_result(notification, True)
            return True
        if notification:
            try:
                self.messenger.send(
                    notification["chat"],
                    notification["text"],
                    Path(notification["image"]) if notification["image"] else None,
                    json.loads(notification["buttons"]) if notification["buttons"] else None,
                )
                self.store.notification_result(notification, True)
            except Exception:
                self.store.notification_result(
                    notification, False, min(3600, 30 * 2 ** min(7, notification["attempts"]))
                )
        return bool(update or job or notification)
