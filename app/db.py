import os
import sqlite3
from contextlib import contextmanager

from flask import current_app, g

from .utils import now_str


def db_path(app=None):
    return os.path.join((app or current_app).config["DATA_DIR"], "voucher.db")


def connect(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(db_path())
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@contextmanager
def write_tx(conn):
    """쓰기 트랜잭션. BEGIN IMMEDIATE로 동시 출고 시 재고 검사와 기록이 섞이지 않게 합니다."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def init_db():
    conn = connect(db_path())
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        with current_app.open_resource("schema.sql") as f:
            conn.executescript(f.read().decode("utf-8"))
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


_NEW_COLUMNS = {  # 이전 버전 DB에 없을 수 있는 컬럼
    "users": ["sso_subject TEXT", "directory_id TEXT", "job_title TEXT NOT NULL DEFAULT ''"],
    "transactions": ["rcpt_name TEXT", "rcpt_email TEXT", "rcpt_dept TEXT"],
}


def _migrate(conn):
    """이전 버전 DB에 새 컬럼을 추가합니다 (기존 데이터는 그대로)."""
    for table, columns in _NEW_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col in columns:
            if col.split()[0] not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_sso ON users (sso_subject)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_dir ON users (directory_id)")


def admin_entries(cfg):
    """ADMIN_EMAILS (예: a@bdo.kr:홍길동,b@bdo.kr) → [(메일, 성명)]"""
    out = []
    for entry in (e.strip() for e in cfg.get("ADMIN_EMAILS", "").split(",")):
        if entry:
            email, _, name = entry.partition(":")
            out.append((email.strip().lower(), name.strip()))
    return out


def upsert_admin(conn, email, name):
    email = email.strip().lower()
    ts = now_str()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        conn.execute("UPDATE users SET role='admin', is_active=1, updated_at=? WHERE id=?", (ts, row["id"]))
    else:
        conn.execute(
            "INSERT INTO users (email, name, role, created_at, updated_at) VALUES (?, ?, 'admin', ?, ?)",
            (email, name or email.split("@")[0], ts, ts),
        )


def sync_admins():
    """ADMIN_EMAILS 가 관리자 목록의 기준입니다: 적힌 사람은 관리자로, 빠진 사람은 관리자에서 해제합니다."""
    entries = admin_entries(current_app.config)
    if not entries:
        return
    conn = connect(db_path())
    try:
        with write_tx(conn):
            for email, name in entries:
                upsert_admin(conn, email, name)
            marks = ",".join("?" * len(entries))
            conn.execute(f"UPDATE users SET role='staff', updated_at=? WHERE role='admin' AND email NOT IN ({marks})",
                         [now_str(), *(e for e, _n in entries)])
    finally:
        conn.close()


def init_app(app):
    app.teardown_appcontext(close_db)
