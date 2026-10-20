import base64
import re
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app import create_app
from app.db import connect, db_path


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATA_DIR": str(tmp_path),
        "SECRET_KEY": "test",
        "MAIL_BACKEND": "memory",
        "MAIL_ASYNC": False,
        "CSRF_DISABLED": True,
        "ADMIN_EMAILS": "",
        "ALLOWED_EMAIL_DOMAINS": [],
        "BASE_URL": "http://nas.test",
    })
    with app.app_context():
        conn = connect(db_path(app))
        ts = "2026-01-01 00:00:00"
        conn.executemany(
            "INSERT INTO users (email, name, department, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            [("admin@co.kr", "관리자", "총무팀", "admin", ts, ts),
             ("kim@co.kr", "김철수", "영업팀", "staff", ts, ts),
             ("lee@co.kr", "이영희", "개발팀", "staff", ts, ts)],
        )
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
