from __future__ import annotations

import argparse
import fcntl
import logging
import os
import signal
import threading
import time

from .admin import EDITABLE, AdminState, make_server
from .ai import OllamaAI, RunnerAI
from .config import load_settings, telegram_identity
from .ledger import Ledger, RemoteError
from .messenger import Telegram
from .service import Service
from .store import Store

log = logging.getLogger("receipt_bridge")


def make_ai(settings):
    if settings.ai_provider == "ollama":
        return OllamaAI(settings.ollama_url, settings.ai_model, settings.ai_timeout)
    return RunnerAI(
        settings.ai_runner_url,
        settings.ai_timeout,
        settings.ai_provider,
        settings.ai_model,
        ocr_languages=settings.ocr_languages,
        token=settings.ai_runner_token.get_secret_value(),
    )


def apply_settings(admin, service):
    """Switch clients between jobs; keep the previous secret snapshot for uncertain POSTs."""
    store = admin.store
    with admin.config_lock:
        revision = store.setting("ui_revision", 0)
        if revision == admin.applied_revision:
            return
        desired = admin.effective()
        if admin.ledger_change_blocked(desired, service.settings):
            return
        previous_bot = store.setting("telegram_bot_id", telegram_identity(service.settings.telegram_token))
        new_bot = telegram_identity(desired.telegram_token)
        switching_bot = new_bot and previous_bot and new_bot != previous_bot
        if switching_bot and store.has_pending_messages():
            return
        ledger = Ledger(desired.ledger_url, desired.ledger_password.get_secret_value())
        ai = make_ai(desired)
        token_changed = desired.telegram_token != service.settings.telegram_token
        messenger = (
            Telegram(desired.telegram_token.get_secret_value(), desired.max_download_mb)
            if token_changed
            else service.messenger
        )
        with store.tx():
            if switching_bot:
                store.db.execute("DELETE FROM inbox")  # All are processed; IDs belong to the old bot.
                store.set_setting("telegram_offset", 0)
            if new_bot:
                store.set_setting("telegram_bot_id", new_bot)
            store.set_credentials(
                {
                    name: getattr(desired, name).get_secret_value()
                    for name in ("telegram_token", "ledger_password")
                },
                applied=True,
            )
            store.set_setting("ui_applied_settings", {key: getattr(desired, key) for key in EDITABLE})
            store.set_setting("ui_applied_revision", revision)
        old_ledger, old_ai, old_messenger = service.ledger, service.ai, service.messenger
        service.ledger, service.ai, service.messenger, service.settings = ledger, ai, messenger, desired
        messenger.limit = desired.max_download_mb * 1024 * 1024
        with admin.lock:
            admin.current, admin.applied_revision = desired, revision
    old_ledger.close()
    old_ai.close()
    if token_changed:
        old_messenger.close()
    store.log("info", "service", "운영 설정 적용")


def run(path):
    settings = load_settings(path)
    os.umask(0o077)
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (settings.data_dir / "worker.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError("같은 데이터 폴더에 이미 실행 중인 서비스가 있습니다") from None
    store = Store(settings.data_dir / "jobs.sqlite3")
    admin = AdminState(settings, store)
    settings = admin.current
    if not settings.web_enabled:
        settings.check_runtime()
    telegram = Telegram(settings.telegram_token.get_secret_value(), settings.max_download_mb)
    ledger = Ledger(settings.ledger_url, settings.ledger_password.get_secret_value())
    ai = make_ai(settings)
    service = Service(settings, store, telegram, ai, ledger)
    stop = threading.Event()
    ready = threading.Event()
    if all(admin.readiness(settings).values()) and (not settings.web_enabled or not admin.setup_required()):
        ready.set()
    server = make_server(admin) if settings.web_enabled else None
    web_thread = None
    if server:
        web_thread = threading.Thread(target=server.serve_forever, name="admin-web", daemon=True)
        web_thread.start()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    def poll():
        poller, token = None, None
        try:
            while not stop.is_set():
                if not ready.wait(timeout=1):
                    continue
                next_token = service.settings.telegram_token.get_secret_value()
                if next_token != token:
                    if poller:
                        poller.close()
                    poller, token = Telegram(next_token), next_token
                try:
                    updates = poller.poll(store.offset())
                    with admin.config_lock:
                        # A pending old-bot request must never consume a new bot's offset.
                        if token != admin.effective().telegram_token.get_secret_value() or not ready.is_set():
                            continue
                        store.ingest(updates, service.authorized_update)
                    with admin.lock:
                        recovered = admin.last_poll_error is not None
                        admin.last_poll, admin.last_poll_error = time.time(), None
                    if recovered:
                        store.log("info", "telegram", "텔레그램 수신 연결 복구")
                except RemoteError as exc:
                    log.warning("Telegram polling failed, status=%d", exc.status)
                    with admin.lock:
                        previous = admin.last_poll_error
                        admin.last_poll_error = exc.status or "connection"
                    if previous != admin.last_poll_error:
                        store.log("error", "telegram", f"텔레그램 수신 오류 · HTTP {exc.status or 0}")
                    stop.wait(max(5, min(300, exc.retry_after)))
                except Exception:
                    log.error("Polling failed; update not acknowledged")
                    store.log("error", "telegram", "수신 처리 오류 · 메시지는 확인 처리하지 않았습니다")
                    stop.wait(10)
        finally:
            if poller:
                poller.close()

    # Recover a crash between state commit and notification creation.
    service.recover_notifications()
    thread = threading.Thread(target=poll, name="telegram-poll", daemon=True)
    thread.start()
    log.info("Receipt Bridge started; provider=%s", settings.ai_provider)
    store.log("info", "service", "서비스 시작")
    try:
        while not stop.is_set():
            try:
                apply_settings(admin, service)
                if all(admin.readiness().values()) and (
                    not settings.web_enabled or not admin.setup_required()
                ):
                    ready.set()
                else:
                    ready.clear()
                common = admin.readiness()
                if not (common["ledger"] and common["ai"]) or (
                    settings.web_enabled and admin.setup_required()
                ):
                    stop.wait(1)
                    continue
                if not service.tick(telegram_ready=ready.is_set()):
                    stop.wait(0.5)
            except Exception:
                log.error("Worker failed; queued work remains on disk")
                store.log("error", "worker", "작업 처리 중 오류 · 대기 작업은 보관됩니다")
                stop.wait(5)
    finally:
        stop.set()
        if server:
            server.shutdown()
            server.server_close()
            web_thread.join(timeout=5)
        thread.join(timeout=55)
        store.log("info", "service", "서비스 종료")
        service.messenger.close()
        service.ledger.close()
        service.ai.close()
        store.close()
        lock.close()


def main():
    parser = argparse.ArgumentParser(description="Telegram 영수증 → Duet Ledger")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("command", choices=["run", "check", "ai-runner"], nargs="?", default="run")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Do not enable HTTP request logging: Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    try:
        if args.command == "ai-runner":
            from .runner import serve

            serve()
        elif args.command == "check":
            checked = load_settings(args.config)
            db_path = checked.data_dir / "jobs.sqlite3"
            if db_path.exists():
                saved = Store(db_path)
                try:
                    state = AdminState(checked, saved)
                    checked = state.effective()
                    if checked.web_enabled and state.setup_required():
                        raise ValueError("첫 접속 화면에서 관리자 비밀번호를 설정하세요")
                finally:
                    saved.close()
            checked.check_runtime()
            print("설정 형식 확인 완료 (외부 접속 없음)")
        else:
            run(args.config)
    except (ValueError, OSError):
        # Config validation can include a secret as input; never print the original exception.
        parser.exit(1, "시작 실패: 설정·권한·AI 지원 여부를 확인하세요. README.md를 참고하세요.\n")


if __name__ == "__main__":
    main()
