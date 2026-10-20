import base64
import json
import re
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app import create_app
from app.db import connect, db_path


# 시험용 회사 주소록 (동명이인 김철수 2명, 퇴사자 1명, 게스트 1명)
DIRECTORY = [
    {"id": "oid-kim", "displayName": "김철수", "mail": "kim@co.kr", "department": "영업팀", "jobTitle": "대리"},
    {"id": "oid-kim2", "displayName": "김철수", "mail": "kim.cs@co.kr", "department": "개발팀", "jobTitle": "과장"},
    {"id": "oid-lee", "displayName": "이영희", "mail": "lee@co.kr", "department": "개발팀", "jobTitle": "사원"},
    {"id": "oid-gone", "displayName": "박퇴사", "mail": "gone@co.kr", "department": "인사팀", "accountEnabled": False},
    {"id": "oid-guest", "displayName": "외부인", "mail": "x@co.kr", "userType": "Guest"},
]


def write_directory(path, people):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(people, fh, ensure_ascii=False)


@pytest.fixture
def app(tmp_path):
    write_directory(tmp_path / "directory.json", DIRECTORY)
    app = create_app({
        "TESTING": True,
        "DATA_DIR": str(tmp_path),
        "SECRET_KEY": "test",
        "MAIL_BACKEND": "memory",
        "MAIL_ASYNC": False,
        "CSRF_DISABLED": True,
        "ADMIN_EMAILS": "admin@co.kr:관리자",
        "ALLOWED_EMAIL_DOMAINS": ["co.kr"],
        "PUBLIC_URL": "http://nas.test",
        "AUTH_MODE": "email",
        "DIRECTORY_BACKEND": "file",
        "DIRECTORY_FILE": str(tmp_path / "directory.json"),
    })
    with app.app_context():
        conn = connect(db_path(app))
        ts = "2026-01-01 00:00:00"
        conn.executemany(
            "INSERT INTO voucher_types (name, face_value, created_at) VALUES (?, ?, ?)",
            [("신세계상품권", 50000, ts), ("신세계상품권", 10000, ts)],
        )
        conn.commit()
        conn.close()
    return app


@pytest.fixture
def outbox(app):
    return app.extensions.setdefault("outbox", [])


def login(client, outbox, email):
    client.post("/login", data={"email": email})
    body = outbox[-1].get_body(("plain",)).get_content()
    code = re.search(r"인증코드: (\d{6})", body).group(1)
    resp = client.post("/login/verify", data={"code": code})
    assert resp.status_code == 302
    return resp


@pytest.fixture
def admin_client(app, outbox):
    c = app.test_client()
    login(c, outbox, "admin@co.kr")
    return c


def signature_data_url(blank=False):
    img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    if not blank:
        ImageDraw.Draw(img).line([(20, 150), (120, 40), (250, 160), (380, 30)], fill=(0, 0, 0, 255), width=4)
    bio = BytesIO()
    img.save(bio, "PNG")
    return "data:image/png;base64," + base64.b64encode(bio.getvalue()).decode()


def sign_link(msg):
    body = msg.get_body(("plain",)).get_content()
    return re.search(r"http://nas\.test(/sign\?t=\S+)", body).group(1)
