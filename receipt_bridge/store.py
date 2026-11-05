from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .config import CREDENTIAL_FIELDS


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Store:
    """One active worker per DB; mutations and polling commits share a short lock."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA foreign_keys=ON;
            PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS credentials(name TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS service_logs(
                id INTEGER PRIMARY KEY, at REAL NOT NULL, level TEXT NOT NULL,
                source TEXT NOT NULL, message TEXT NOT NULL, job_id TEXT);
            CREATE TABLE IF NOT EXISTS inbox(
                update_id INTEGER PRIMARY KEY, body TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, adapter TEXT NOT NULL DEFAULT 'telegram',
                chat INTEGER NOT NULL, user INTEGER NOT NULL, message INTEGER NOT NULL,
                file_id TEXT NOT NULL, account TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'received', revision INTEGER NOT NULL DEFAULT 0,
                original TEXT, image TEXT, image_hash TEXT, image_warnings TEXT NOT NULL DEFAULT '[]',
                rotation INTEGER NOT NULL DEFAULT 0, use_original INTEGER NOT NULL DEFAULT 0,
                extraction TEXT, ocr TEXT NOT NULL DEFAULT '', fingerprint TEXT,
                payload TEXT, request_key TEXT NOT NULL, posting_id TEXT, receipt_id TEXT,
                attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
                error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                UNIQUE(adapter,chat,message));
            CREATE INDEX IF NOT EXISTS jobs_due ON jobs(state,next_at);
            CREATE INDEX IF NOT EXISTS jobs_fingerprint ON jobs(fingerprint);
            CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created_at);
            CREATE TABLE IF NOT EXISTS events(
                seq INTEGER PRIMARY KEY, job_id TEXT NOT NULL, state TEXT NOT NULL, at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS events_job ON events(job_id,seq);
            CREATE INDEX IF NOT EXISTS events_at ON events(at);
            CREATE INDEX IF NOT EXISTS service_logs_at ON service_logs(at);
            CREATE TABLE IF NOT EXISTS outbox(
                id INTEGER PRIMARY KEY, dedupe TEXT UNIQUE NOT NULL, chat INTEGER NOT NULL,
                text TEXT NOT NULL, image TEXT, buttons TEXT,
                done INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                next_at REAL NOT NULL DEFAULT 0);
        """)

        # Additive migration: existing jobs, payloads and idempotency keys stay intact.
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}
        for name, definition in {
            "input_kind": "TEXT NOT NULL DEFAULT 'image'",
            "input_text": "TEXT NOT NULL DEFAULT ''",
            "reference_date": "TEXT NOT NULL DEFAULT ''",
            "conflicts": "TEXT NOT NULL DEFAULT '{}'",
            "batch_size": "INTEGER NOT NULL DEFAULT 1",
            "part": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in columns:
                self.db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")

    @contextmanager
    def tx(self):
        with self.lock:
            nested = self.db.in_transaction
            savepoint = "sp_" + uuid.uuid4().hex
            self.db.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute(f"RELEASE SAVEPOINT {savepoint}" if nested else "COMMIT")
            except BaseException:
                self.db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}" if nested else "ROLLBACK")
                if nested:
                    self.db.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise

    def close(self):
        self.db.close()

    def offset(self):
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key='telegram_offset'").fetchone()
            return int(row[0]) if row else 0

    def ingest(self, updates: list[dict], authorized):
        # Acknowledge to Telegram only after committing the allowed updates durably.
        with self.tx() as db:
            offset = self.offset()
            for update in updates:
                offset = max(offset, update["update_id"] + 1)
                if authorized(update):
                    db.execute(
                        "INSERT OR IGNORE INTO inbox(update_id,body) VALUES(?,?)",
                        (update["update_id"], dumps(update)),
                    )
            db.execute("INSERT OR REPLACE INTO meta VALUES('telegram_offset',?)", (str(offset),))

    def next_update(self):
        with self.lock:
            row = self.db.execute("SELECT * FROM inbox WHERE done=0 ORDER BY update_id LIMIT 1").fetchone()
            return (row["update_id"], json.loads(row["body"])) if row else None

    def finish_update(self, update_id):
        with self.tx() as db:
            # Do not retain message contents after their actions are durably recorded.
            db.execute("UPDATE inbox SET done=1,body='{}' WHERE update_id=?", (update_id,))

    def create_job(
        self,
        chat,
        user,
        message,
        file_id,
        account,
        adapter="telegram",
        *,
        input_kind="image",
        input_text="",
        reference_date="",
    ):
        with self.tx() as db:
            job_id = uuid.uuid4().hex[:12]
            now = time.time()
            db.execute(
                """INSERT OR IGNORE INTO jobs
                (id,chat,user,message,file_id,account,request_key,created_at,updated_at,adapter,input_kind,input_text,reference_date)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id,
                    chat,
                    user,
                    message,
                    file_id,
                    account,
                    "rb-" + uuid.uuid4().hex,
                    now,
                    now,
                    adapter,
                    input_kind,
                    input_text,
                    reference_date,
                ),
            )
            row = db.execute(
                "SELECT * FROM jobs WHERE chat=? AND message=? AND adapter=?", (chat, message, adapter)
            ).fetchone()
            if row["id"] == job_id:
                db.execute("INSERT INTO events(job_id,state,at) VALUES(?,'received',?)", (job_id, now))
            return dict(row)

    def get(self, job_id):
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return dict(row) if row else None

    def update(self, job_id, **fields):
        allowed = {r[1] for r in self.db.execute("PRAGMA table_info(jobs)")}
        if not fields or not fields.keys() <= allowed - {"id"}:
            raise ValueError("invalid job fields")
        fields["updated_at"] = time.time()
        with self.tx() as db:
            db.execute(
                "UPDATE jobs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                [*fields.values(), job_id],
            )
            if "state" in fields:
                db.execute(
                    "INSERT INTO events(job_id,state,at) VALUES(?,?,?)",
                    (job_id, fields["state"], fields["updated_at"]),
                )

    def due_job(self):
        with self.lock:
            row = self.db.execute(
                """SELECT * FROM jobs WHERE
                state IN ('received','processing','creating','attaching') AND next_at<=?
                ORDER BY created_at,id LIMIT 1""",
                (time.time(),),
            ).fetchone()
            return dict(row) if row else None

    def duplicates(self, job_id, fingerprint=None, image_hash=None):
        with self.lock:
            rows = self.db.execute(
                """SELECT id,state FROM jobs WHERE id<>? AND state<>'cancelled'
                AND account=(SELECT account FROM jobs WHERE id=?)
                AND ((? IS NOT NULL AND fingerprint=?) OR (? IS NOT NULL AND image_hash=?))""",
                (job_id, job_id, fingerprint, fingerprint, image_hash, image_hash),
            ).fetchall()
            return [dict(r) for r in rows]

    def pending(self, user, chat):
        with self.lock:
            return [
                dict(r)
                for r in self.db.execute(
                    """SELECT * FROM jobs WHERE user=? AND chat=?
                AND state NOT IN ('done','cancelled') ORDER BY created_at DESC LIMIT 20""",
                    (user, chat),
                )
            ]

    def notify(self, key, chat, text, image=None, buttons=None):
        with self.tx() as db:
            db.execute(
                "INSERT OR IGNORE INTO outbox(dedupe,chat,text,image,buttons) VALUES(?,?,?,?,?)",
                (key, chat, text, str(image) if image else None, dumps(buttons) if buttons else None),
            )

    def next_notification(self):
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM outbox WHERE done=0 AND next_at<=? ORDER BY id LIMIT 1", (time.time(),)
            ).fetchone()
            return dict(row) if row else None

    def notification_result(self, row, success, delay=30):
        with self.tx() as db:
            db.execute(
                "UPDATE outbox SET done=?,attempts=attempts+1,next_at=? WHERE id=?",
                (int(success), time.time() + delay, row["id"]),
            )

    def setting(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, dumps(value)))

    def log(self, level, source, message, job_id=None):
        # Callers use fixed messages and numeric status codes, never raw exceptions or HTTP data.
        with self.tx() as db:
            db.execute(
                "INSERT INTO service_logs(at,level,source,message,job_id) VALUES(?,?,?,?,?)",
                (time.time(), level, source, message, job_id),
            )
            db.execute("DELETE FROM service_logs WHERE id <= (SELECT MAX(id)-5000 FROM service_logs)")

    def dashboard(self, since):
        with self.lock:
            counts = {r[0]: r[1] for r in self.db.execute("SELECT state,count(*) FROM jobs GROUP BY state")}
            today = self.db.execute("SELECT count(*) FROM jobs WHERE created_at>=?", (since,)).fetchone()[0]
            dates = [
                dict(r)
                for r in self.db.execute(
                    "SELECT created_at,state FROM jobs WHERE created_at>=? ORDER BY created_at",
                    (since - 6 * 86400,),
                )
            ]
            return {
                "counts": counts,
                "today": today,
                "total": sum(counts.values()),
                "dates": dates,
                "inbox": self.db.execute("SELECT count(*) FROM inbox WHERE done=0").fetchone()[0],
                "outbox": self.db.execute("SELECT count(*) FROM outbox WHERE done=0").fetchone()[0],
            }

    def browse_jobs(self, state="", search="", page=1):
        conditions, args = [], []
        if state:
            conditions.append("state=?")
            args.append(state)
        if search:
            conditions.append("(instr(id,?)>0 OR instr(COALESCE(extraction,''),?)>0)")
            args.extend([search, search])
        fields = "id,state,account,attempts,error,created_at,updated_at,extraction,posting_id,receipt_id,input_kind,batch_size,part"
        result = self._browse_page("jobs", fields, "created_at DESC,id DESC", conditions, args, page, 20)
        for item in result["items"]:
            item["extraction"] = json.loads(item["extraction"]) if item["extraction"] else None
        return result

    def browse_logs(self, kind="service", level="", search="", page=1, start_at=None, end_at=None):
        if kind == "events":
            table, fields, ordering = "events", "seq AS id,at,job_id,state", "seq"
        else:
            table, fields, ordering = "service_logs", "id,at,level,source,message,job_id", "id"
        conditions, args = [], []
        if level and kind != "events":
            conditions.append("level=?")
            args.append(level)
        if search:
            columns = ("job_id", "state") if kind == "events" else ("job_id", "message", "source")
            conditions.append(
                "(" + " OR ".join(f"instr(COALESCE({column},''),?)>0" for column in columns) + ")"
            )
            args.extend([search] * len(columns))
        if start_at is not None:
            conditions.append("at>=?")
            args.append(start_at)
        if end_at is not None:
            conditions.append("at<?")
            args.append(end_at)
        return self._browse_page(table, fields, ordering + " DESC", conditions, args, page, 50)

    def _browse_page(self, table, fields, ordering, conditions, args, page, page_size):
        """SQL identifiers come only from the fixed listing queries above."""
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.lock:
            count = self.db.execute(f"SELECT count(*) FROM {table}{where}", args).fetchone()[0]
            rows = self.db.execute(
                f"SELECT {fields} FROM {table}{where} ORDER BY {ordering} LIMIT ? OFFSET ?",
                [*args, page_size, (page - 1) * page_size],
            ).fetchall()
            return {
                "items": [dict(row) for row in rows],
                "total": count,
                "page": page,
                "page_size": page_size,
            }

    def credentials(self, applied=False):
        prefix = "applied:" if applied else ""
        with self.lock:
            return {
                name: row[0]
                for name in CREDENTIAL_FIELDS
                if (
                    row := self.db.execute(
                        "SELECT value FROM credentials WHERE name=?", (prefix + name,)
                    ).fetchone()
                )
                is not None
            }

    def set_credentials(self, values, applied=False):
        prefix = "applied:" if applied else ""
        if not values.keys() <= set(CREDENTIAL_FIELDS):
            raise ValueError("접속 키 항목을 확인하세요")
        with self.tx() as db:
            for name, value in values.items():
                db.execute(
                    "INSERT OR REPLACE INTO credentials(name,value) VALUES(?,?)", (prefix + name, value)
                )

    def job_events(self, job_id):
        with self.lock:
            return [
                dict(row)
                for row in self.db.execute(
                    "SELECT at,state FROM events WHERE job_id=? ORDER BY seq", (job_id,)
                )
            ]

    def has_pending_transactions(self, unposted_only=False):
        with self.lock:
            return bool(
                self.db.execute(
                    "SELECT 1 FROM jobs WHERE payload IS NOT NULL "
                    "AND state NOT IN ('done','cancelled') "
                    + ("AND posting_id IS NULL " if unposted_only else "")
                    + "LIMIT 1"
                ).fetchone()
            )

    def has_pending_messages(self):
        with self.lock:
            return bool(
                self.db.execute(
                    "SELECT 1 FROM jobs WHERE state NOT IN ('done','cancelled') LIMIT 1"
                ).fetchone()
                or self.db.execute("SELECT 1 FROM inbox WHERE done=0 LIMIT 1").fetchone()
                or self.db.execute("SELECT 1 FROM outbox WHERE done=0 LIMIT 1").fetchone()
            )
