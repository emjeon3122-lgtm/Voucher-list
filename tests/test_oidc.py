"""Microsoft 365(Entra ID) 로그인 — 가짜 OIDC 공급자로 확인."""
import time
import urllib.parse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import create_app, oidc
from app.db import connect, db_path
from conftest import signature_data_url

ISSUER = "https://login.example/tenant-1/v2.0"
TENANT, CLIENT = "tenant-1", "client-1"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "k1", "use": "sig"}


class FakeProvider:
    def __init__(self):
        self.claims = {}   # 다음 ID 토큰에 덮어쓸 값
        self.nonce = None

    def get_json(self, url):
        if url.endswith("/.well-known/openid-configuration"):
            return {"issuer": ISSUER, "authorization_endpoint": "https://login.example/authorize",
                    "token_endpoint": "https://login.example/token", "jwks_uri": "https://login.example/keys"}
        assert url == "https://login.example/keys"
        return {"keys": [JWK]}

    def post_form(self, url, data):
        assert url == "https://login.example/token" and data["code"] == "good-code" and data["code_verifier"]
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT, "sub": "sub-1", "oid": "oid-kim", "tid": TENANT, "iat": now,
                  "exp": now + 600, "nonce": self.nonce, "email": "kim@co.kr", "name": "김철수", **self.claims}
        return {"id_token": jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "k1"})}


@pytest.fixture
def provider(monkeypatch):
    p = FakeProvider()
    monkeypatch.setattr(oidc, "http_get_json", p.get_json)
    monkeypatch.setattr(oidc, "http_post_form", p.post_form)
    return p


@pytest.fixture
def sso_app(tmp_path):
    app = create_app({
        "TESTING": True, "DATA_DIR": str(tmp_path), "SECRET_KEY": "x" * 40, "CSRF_DISABLED": True,
        "AUTH_MODE": "oidc", "OIDC_TENANT_ID": TENANT, "OIDC_CLIENT_ID": CLIENT, "OIDC_CLIENT_SECRET": "s",
        "OIDC_ISSUER": ISSUER, "PUBLIC_URL": "https://nas.test", "ALLOWED_EMAIL_DOMAINS": ["co.kr"],
        "MAIL_BACKEND": "memory", "MAIL_ASYNC": False, "ADMIN_EMAILS": "",
    })
    conn = connect(db_path(app))
    ts = "2026-01-01 00:00:00"
    conn.executemany("INSERT INTO users (email, name, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                     [("admin@co.kr", "관리자", "admin", ts, ts), ("kim@co.kr", "김철수", "staff", ts, ts)])
    conn.execute("INSERT INTO voucher_types (name, face_value, created_at) VALUES ('문화상품권', 10000, ?)", (ts,))
    conn.commit()
    conn.close()
    return app


def sso_login(client, provider, **claims):
    r = client.get("/auth/login?next=/my")
    assert r.status_code == 302
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r.location).query)
    assert q["code_challenge_method"] == ["S256"] and q["redirect_uri"] == ["https://nas.test/auth/callback"]
    provider.nonce = q["nonce"][0]
    provider.claims = claims
    return client.get(f"/auth/callback?code=good-code&state={q['state'][0]}")


def test_login_page_shows_microsoft_button(sso_app):
    html = sso_app.test_client().get("/login").get_data(as_text=True)
    assert "Microsoft 365 계정으로 로그인" in html and "인증코드" not in html


def test_sso_admin_login_links_account(sso_app, provider):
    c = sso_app.test_client()
    r = sso_login(c, provider, email="admin@co.kr", oid="oid-admin")
    assert r.status_code == 302 and r.location.endswith("/my")  # 로그인 전에 열려던 주소로 복귀
    assert c.get("/ledger").status_code == 200
    conn = connect(db_path(sso_app))
    assert conn.execute("SELECT sso_subject FROM users WHERE email='admin@co.kr'").fetchone()[0] == "oidc:oid-admin"
    conn.close()
    # 다음 로그인은 메일이 바뀌어도 Microsoft 계정 고유값으로 찾음
    c3 = sso_app.test_client()
    sso_login(c3, provider, email="admin.renamed@co.kr", oid="oid-admin")
    assert c3.get("/ledger").status_code == 200
    # 같은 로그인 응답을 다시 쓰면 거부 (state 는 1회용)
    c2 = sso_app.test_client()
    assert "/login" in c2.get("/auth/callback?code=good-code&state=whatever").location


@pytest.mark.parametrize("claims, reason", [
    ({}, "명단에 있지만 관리자가 아닌 수령자"),
    ({"email": "nobody@co.kr", "oid": "oid-x"}, "명단에 없는 계정"),
    ({"tid": "other-tenant"}, "다른 테넌트"),
    ({"email": "kim@other.com", "oid": "oid-y"}, "허용 안 된 도메인"),
    ({"email": "kim@evil.com@co.kr", "oid": "oid-z"}, "'@' 두 개"),
    ({"aud": "someone-else"}, "다른 앱용 토큰"),
    ({"exp": int(time.time()) - 3600}, "만료"),
])
def test_sso_login_rejected(sso_app, provider, claims, reason):
    c = sso_app.test_client()
    r = sso_login(c, provider, **claims)
    assert "/login" in r.location, reason
    assert c.get("/ledger").status_code == 302, reason


def test_sso_nonce_mismatch_rejected(sso_app, provider):
    c = sso_app.test_client()
    r = c.get("/auth/login")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r.location).query)
    provider.nonce = "other"
    provider.claims = {"email": "admin@co.kr", "oid": "oid-admin"}
    c.get(f"/auth/callback?code=good-code&state={q['state'][0]}")
    assert c.get("/ledger").status_code == 302


def test_entra_admin_role_grants_admin(sso_app, provider):
    """명단에서 '수령자'여도 Entra 앱 역할 Admin 을 받았으면 관리자로 접속."""
    c = sso_app.test_client()
    sso_login(c, provider, roles=["Admin"])
    assert c.get("/ledger").status_code == 200


def test_sign_link_works_without_login_in_oidc_mode(sso_app, provider):
    admin = sso_app.test_client()
    sso_login(admin, provider, email="admin@co.kr", oid="oid-admin")
    admin.post("/ledger/in", data={"txn_date": "2026-01-05", "voucher_type_id": 1, "quantity": 5})
    admin.post("/ledger/out", data={"txn_date": "2026-01-06", "voucher_type_id": 1, "quantity": 1,
                                    "recipient_id": 2, "send_request": "1"})
    body = sso_app.extensions["outbox"][-1].get_body(("plain",)).get_content()
    link = body[body.index("https://nas.test/sign?t="):].split()[0].replace("https://nas.test", "")
    anon = sso_app.test_client()  # 수령자: Microsoft 로그인 없이 바로 서명
    assert anon.get(link).status_code == 200
    r = anon.post(link, data={"agree": "1", "signer_name": "김철수", "signature": signature_data_url()})
    assert r.status_code == 302
    conn = connect(db_path(sso_app))
    assert conn.execute("SELECT sign_status FROM transactions WHERE id=2").fetchone()[0] == "SIGNED"
    conn.close()


def test_email_code_routes_closed_in_oidc_mode(sso_app):
    c = sso_app.test_client()
    assert c.post("/login", data={"email": "kim@co.kr"}).status_code == 405
    assert c.get("/login/verify").status_code == 404
