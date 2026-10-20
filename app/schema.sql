-- 상품권 수불 관리 DB 스키마 (SQLite)
-- 앱 시작 시 자동 실행되며, 이미 존재하는 테이블은 건드리지 않습니다.

-- 사람: 관리자(로그인) + 상품권을 받은 직원(회사 주소록에서 고른 사람이 자동 저장됨). 직접 관리하지 않습니다.
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name        TEXT NOT NULL,
    department  TEXT NOT NULL DEFAULT '',
    employee_no TEXT NOT NULL DEFAULT '',
    job_title   TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT 'staff' CHECK (role IN ('admin', 'staff')),   -- admin: ADMIN_EMAILS 로 동기화
    is_active   INTEGER NOT NULL DEFAULT 1,                                          -- 0: 주소록에서 사용 중지(퇴사)
    directory_id TEXT,                                   -- 회사 주소록(Entra ID) 사용자 ID — 동명이인 구분
    sso_subject TEXT,                                    -- 관리자 Microsoft 로그인 고유값(oidc:<oid>)
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 상품권 종류 + 권종 (예: 신세계상품권 / 50,000원)
CREATE TABLE IF NOT EXISTS voucher_types (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    face_value INTEGER NOT NULL CHECK (face_value > 0),
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE (name, face_value)
);

-- 수불 대장 (입고 IN / 출고 OUT). 삭제하지 않고 is_void(취소)로만 정정하여 영구 보존합니다.
CREATE TABLE IF NOT EXISTS transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_date        TEXT NOT NULL,                       -- YYYY-MM-DD
    direction       TEXT NOT NULL CHECK (direction IN ('IN', 'OUT')),
    voucher_type_id INTEGER NOT NULL REFERENCES voucher_types(id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    face_value      INTEGER NOT NULL,                    -- 등록 시점 권종 금액
    amount          INTEGER NOT NULL,                    -- quantity * face_value
    serial_no       TEXT NOT NULL DEFAULT '',            -- 일련번호 (선택)
    counterparty    TEXT NOT NULL DEFAULT '',            -- 입고: 구매처
    giver_id        INTEGER REFERENCES users(id),        -- 지급자(담당자)
    recipient_id    INTEGER REFERENCES users(id),        -- 수령자 (출고)
    rcpt_name       TEXT,                                -- 지급 당시 수령자 성명·메일·부서 (이후 이동·퇴사해도 기록 유지)
    rcpt_email      TEXT,
    rcpt_dept       TEXT,
    purpose         TEXT NOT NULL DEFAULT '',            -- 용도 / 비고
    sign_status     TEXT NOT NULL DEFAULT 'NONE'
                    CHECK (sign_status IN ('NONE', 'UNREQUESTED', 'REQUESTED', 'SIGNED')),
    sign_request_id INTEGER REFERENCES signature_requests(id),
    is_void         INTEGER NOT NULL DEFAULT 0,
    void_reason     TEXT NOT NULL DEFAULT '',
    voided_by       INTEGER REFERENCES users(id),
    voided_at       TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_txn_order ON transactions (txn_date, id);
CREATE INDEX IF NOT EXISTS ix_txn_type ON transactions (voucher_type_id, txn_date, id);
CREATE INDEX IF NOT EXISTS ix_txn_recipient ON transactions (recipient_id);

-- 전자서명 요청 (메일 1통 = 요청 1건, 같은 수령자의 출고 여러 건을 묶을 수 있음)
CREATE TABLE IF NOT EXISTS signature_requests (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash       TEXT NOT NULL UNIQUE,               -- 링크 토큰의 SHA-256 (원문은 저장하지 않음)
    recipient_id     INTEGER NOT NULL REFERENCES users(id),
    email            TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'PENDING'
                     CHECK (status IN ('PENDING', 'SIGNED', 'CANCELLED')),
    expires_at       TEXT NOT NULL,
    requested_by     INTEGER REFERENCES users(id),
    requested_at     TEXT NOT NULL,
    mail_sent_at     TEXT,
    mail_error       TEXT,
    signed_at        TEXT,
    signer_name      TEXT,
    signer_ip        TEXT,
    signer_ua        TEXT,
    signature_file   TEXT,                               -- data/signatures/ 아래 PNG 파일명
    signature_sha256 TEXT                                -- 위변조 확인용 해시
);
CREATE INDEX IF NOT EXISTS ix_sigreq_recipient ON signature_requests (recipient_id, status);

CREATE TABLE IF NOT EXISTS signature_request_items (
    request_id     INTEGER NOT NULL REFERENCES signature_requests(id),
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    PRIMARY KEY (request_id, transaction_id)
);

-- 로그인용 메일 인증코드 (해시만 저장)
CREATE TABLE IF NOT EXISTS login_codes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL COLLATE NOCASE,
    code_hash  TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    used       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_login_codes_email ON login_codes (email, created_at);

-- 감사 로그 (누가 언제 무엇을 했는지)
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id),
    action     TEXT NOT NULL,
    target     TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '',
    ip         TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
