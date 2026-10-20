"""Microsoft 365(Entra ID) 로그인 — OpenID Connect Authorization Code + PKCE.

검증 항목: ID 토큰 서명(RS256), 발급자(iss), 대상(aud), 만료(exp/nbf), nonce, 테넌트(tid), 이메일 도메인.
"""
import base64
import hashlib
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt

LOGIN_TTL = 10 * 60
EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+)$")  # '@' 가 정확히 하나인 주소만 (예: x@evil.com@bdo.kr 거부)
_TIMEOUT = 15


class OidcError(Exception):
    """사용자에게 보여줄 로그인 오류."""


def http_get_json(url):
    with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_form(url, data):
    body = urllib.parse.urlencode(data).encode("ascii")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise OidcError(f"토큰 발급 실패 ({e.code}) {detail}") from e


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class OidcClient:
    def __init__(self, cfg):
        self.tenant_id = cfg["OIDC_TENANT_ID"]
        self.issuer = (cfg["OIDC_ISSUER"] or f"https://login.microsoftonline.com/{self.tenant_id}/v2.0").rstrip("/")
        self.client_id = cfg["OIDC_CLIENT_ID"]
        self.client_secret = cfg["OIDC_CLIENT_SECRET"]
        self.redirect_uri = cfg["PUBLIC_URL"] + "/auth/callback"
        self.allowed_domains = cfg["ALLOWED_EMAIL_DOMAINS"]
        self._lock = threading.Lock()
        self._meta, self._meta_at, self._jwks = None, 0.0, None

    # 공급자 정보(엔드포인트·서명 키)는 1시간 캐시하고, 모르는 kid 가 오면 키만 다시 받습니다.
    def meta(self):
        with self._lock:
            if self._meta is None or time.time() - self._meta_at > 3600:
                self._meta = http_get_json(self.issuer + "/.well-known/openid-configuration")
                self._meta_at, self._jwks = time.time(), None
            return self._meta

    def _signing_key(self, kid):
        jwks = self._jwks
        if jwks is None or not any(k.get("kid") == kid for k in jwks.get("keys", [])):
            jwks = self._jwks = http_get_json(self.meta()["jwks_uri"])
        for k in jwks.get("keys", []):
            if k.get("kid") == kid and k.get("kty") == "RSA":
                return jwt.PyJWK(k, algorithm="RS256").key
        raise OidcError("ID 토큰 서명 키를 찾을 수 없습니다.")

    def start(self):
        """(Microsoft 로그인 주소, 세션에 보관할 1회용 값)"""
        meta = self.meta()
        state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        query = urllib.parse.urlencode({
            "client_id": self.client_id, "response_type": "code", "redirect_uri": self.redirect_uri,
            "scope": "openid profile email", "state": state, "nonce": nonce, "response_mode": "query",
            "code_challenge": challenge, "code_challenge_method": "S256",
            "prompt": "select_account",  # 브라우저에 여러 Microsoft 계정이 있으면 회사 계정을 고르게
        })
        return f"{meta['authorization_endpoint']}?{query}", {
            "s": state, "n": nonce, "v": verifier, "x": int(time.time()) + LOGIN_TTL,
        }

    def finish(self, code, state, pending):
        """인가 코드를 토큰으로 바꾸고 ID 토큰을 검증해 {email, name, subject, roles} 를 돌려줍니다."""
        if (not isinstance(pending, dict) or not code or not state or pending.get("s") != state
                or pending.get("x", 0) < time.time()):
            raise OidcError("로그인 요청이 만료되었습니다. 다시 시도해 주세요.")
        tokens = http_post_form(self.meta()["token_endpoint"], {
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
            "client_id": self.client_id, "client_secret": self.client_secret, "code_verifier": pending["v"],
        })
        claims = self.verify_id_token(tokens.get("id_token"), pending["n"])
        email = str(claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").strip().lower()
        m = EMAIL_RE.match(email)
        if not m:
            raise OidcError("계정 이메일을 확인할 수 없습니다.")
        if self.allowed_domains and m.group(1) not in self.allowed_domains:
            raise OidcError("허용된 회사 계정이 아닙니다.")
        roles = claims.get("roles") if isinstance(claims.get("roles"), list) else []
        return {
            "email": email,
            "name": str(claims.get("name") or email),
            "subject": "oidc:" + str(claims.get("oid") or claims["sub"]),  # oid: 테넌트 안에서 사람마다 고정
            "roles": [str(r) for r in roles],
        }

    def verify_id_token(self, id_token, nonce):
        if not isinstance(id_token, str) or id_token.count(".") != 2:
            raise OidcError("ID 토큰 형식 오류")
        try:
            header = jwt.get_unverified_header(id_token)
            if header.get("alg") != "RS256":
                raise OidcError("허용하지 않는 서명 방식")
            claims = jwt.decode(
                id_token, self._signing_key(header.get("kid")), algorithms=["RS256"], audience=self.client_id,
                issuer=self.meta()["issuer"], leeway=60, options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as e:
            raise OidcError(f"ID 토큰 검증 실패: {e}") from e
        if claims.get("nonce") != nonce:
            raise OidcError("nonce 불일치")
        if self.tenant_id and claims.get("tid") != self.tenant_id:
            raise OidcError("다른 조직의 계정입니다.")
        return claims
