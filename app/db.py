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


def _migrate(conn):
    """이전 버전 DB에 새 컬럼을 추가합니다 (기존 데이터는 그대로)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "sso_subject" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN sso_subject TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_sso ON users (sso_subject)")


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


def seed_admins():
    """ADMIN_EMAILS (예: a@co.kr:홍길동,b@co.kr) 에 지정된 계정을 관리자로 등록합니다."""
    spec = current_app.config.get("ADMIN_EMAILS", "")
    entries = [e.strip() for e in spec.split(",") if e.strip()]
    if not entries:
        return
    conn = connect(db_path())
    try:
        with write_tx(conn):
            for entry in entries:
                email, _, name = entry.partition(":")
                exists = conn.execute("SELECT 1 FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
                if not exists:  # 이미 있는 계정은 관리자 화면에서 바꾼 권한을 존중
                    upsert_admin(conn, email, name.strip())
    finally:
        conn.close()


def init_app(app):
    app.teardown_appcontext(close_db)
