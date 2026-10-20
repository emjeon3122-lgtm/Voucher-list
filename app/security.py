import hmac
import secrets

from flask import abort, current_app, request, session


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def init_app(app):
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def _check_csrf():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE") or app.config.get("CSRF_DISABLED"):
            return
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("_csrf", "")
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, description="보안 토큰이 만료되었습니다. 페이지를 새로고침한 뒤 다시 시도하세요.")

    @app.after_request
    def _security_headers(resp):
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        # 서명 링크 토큰이 외부 사이트로 새어나가지 않도록
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        if request.endpoint != "static":
            h.setdefault("Cache-Control", "no-store")  # 로그아웃 후 뒤로가기로 대장이 보이지 않게
        if current_app.config["SESSION_COOKIE_SECURE"]:
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "frame-ancestors 'none'; form-action 'self'",
        )
        return resp
