"""운영: 설정 검사, Graph 메일 발송, 자동 백업, 명단 엑셀."""
import json
import os
from datetime import datetime

import pytest

from app import backup, create_app, directory, graph, mailer
from app.config import check_production


def test_production_config_refuses_weak_settings(tmp_path):
    with pytest.raises(RuntimeError) as e:
        create_app({"DATA_DIR": str(tmp_path), "SECRET_KEY": "short", "AUTH_MODE": "oidc",
                    "OIDC_CLIENT_ID": "", "PUBLIC_URL": "http://x", "ALLOWED_EMAIL_DOMAINS": []})
    msg = str(e.value)
    assert "SESSION_SECRET" in msg and "OIDC_TENANT_ID" in msg and "https" in msg and "ALLOWED_EMAIL_DOMAINS" in msg


def test_production_config_ok():
    check_production({
        "SECRET_KEY": "x" * 48, "AUTH_MODE": "oidc", "OIDC_TENANT_ID": "t", "OIDC_ISSUER": "", "OIDC_CLIENT_ID": "c",
        "OIDC_CLIENT_SECRET": "s", "PUBLIC_URL": "https://192.168.100.25:7031", "ALLOWED_EMAIL_DOMAINS": ["bdo.kr"],
        "MAIL_BACKEND": "graph", "MAIL_SENDER": "voucher@bdo.kr", "GRAPH_TENANT_ID": "t", "GRAPH_CLIENT_ID": "c",
        "GRAPH_CLIENT_SECRET": "s", "SMTP_HOST": "", "ADMIN_EMAILS": "eunmin.jeon@bdo.kr:전은민",
        "DIRECTORY_BACKEND": "graph", "DIRECTORY_FILE": "",
    })


class FakeResp:
    def __init__(self, data=b"{}"):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_graph_mail_backend(app, monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        if "oauth2/v2.0/token" in req.full_url:
            return FakeResp(json.dumps({"access_token": "tok", "expires_in": 3600}).encode())
        return FakeResp()

    monkeypatch.setattr(graph.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(graph, "_tokens", {})
    app.config.update(MAIL_BACKEND="graph", MAIL_SENDER="voucher@co.kr", GRAPH_TENANT_ID="t",
                      GRAPH_CLIENT_ID="c", GRAPH_CLIENT_SECRET="s")
    with app.test_request_context():
        msg = mailer.build("kim@co.kr", "제목", "email/login_code", user={"name": "김철수"}, code="123456", minutes=10)
        mailer.send_now([msg, msg])
    token_calls = [c for c in calls if "token" in c.full_url]
    send_calls = [c for c in calls if "sendMail" in c.full_url]
    assert len(token_calls) == 1 and len(send_calls) == 2  # 토큰은 재사용
    assert send_calls[0].full_url == "https://graph.microsoft.com/v1.0/users/voucher%40co.kr/sendMail"
    assert send_calls[0].get_header("Authorization") == "Bearer tok"
    body = json.loads(send_calls[0].data)
    assert body["message"]["toRecipients"][0]["emailAddress"]["address"] == "kim@co.kr"
    assert "123456" in body["message"]["body"]["content"]


def test_daily_backup_and_prune(app):
    cfg = app.config
    d = backup.backup_dir(cfg)
    os.makedirs(d, exist_ok=True)
    old = os.path.join(d, "voucher-backup-20250101.db")
    open(old, "w").close()
    assert backup.run_daily(cfg, datetime(2026, 10, 20, 2, 0)) is None  # BACKUP_HOUR(3시) 전
    made = backup.run_daily(cfg, datetime(2026, 10, 20, 3, 5))
    assert made and made.endswith("voucher-backup-20261020.db") and os.path.getsize(made) > 0
    assert backup.run_daily(cfg, datetime(2026, 10, 20, 9, 0)) is None  # 하루 한 번
    assert not os.path.exists(old)  # 보관 기간 지난 사본 삭제


def test_graph_directory_queries(app, monkeypatch):
    calls = []

    def fake_request(cfg, method, path, payload=None, headers=None):
        calls.append((method, path, headers))
        if path.startswith("/users?"):
            return {"value": [
                {"id": "a1", "displayName": "김철수", "mail": "kim@co.kr", "department": "영업팀", "accountEnabled": True},
                {"id": "a2", "displayName": "김철수", "mail": "kim@partner.com", "accountEnabled": True},  # 외부 도메인
            ]}
        if path.startswith("/users/missing"):
            raise graph.GraphError(404, "not found")
        return {"id": "a1", "displayName": "김철수", "mail": "kim@co.kr", "accountEnabled": False}

    monkeypatch.setattr(graph, "request", fake_request)
    app.config["DIRECTORY_BACKEND"] = "graph"
    with app.test_request_context():
        found = directory.search('김"철')
        assert [p["email"] for p in found] == ["kim@co.kr"]
        method, path, headers = calls[0]
        assert headers == {"ConsistencyLevel": "eventual"}
        query = path.split("?", 1)[1]
        assert "%22displayName%3A%EA%B9%80%EC%B2%A0%22" in query  # 따옴표 제거된 검색어
        assert "accountEnabled%20eq%20true" in query and "userType%20eq%20%27Member%27" in query
        assert directory.get("missing") is None
        assert directory.get("a1") is None        # 사용 중지(퇴사)
        assert directory.get("../etc") is None    # 잘못된 ID 는 조회하지 않음
