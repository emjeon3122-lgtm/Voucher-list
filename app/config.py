"""환경변수 기반 설정. 모든 값은 .env (docker-compose env_file) 로 주입합니다."""
import os


def _bool(name, default=False):
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _list(name):
    return [x.strip().lower() for x in os.environ.get(name, "").split(",") if x.strip()]


class Config:
    APP_NAME = os.environ.get("APP_NAME", "상품권 수불 관리")
    COMPANY_NAME = os.environ.get("COMPANY_NAME", "")
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
    DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", "data"))
    # 메일 속 서명 링크에 들어가는 외부 접속 주소 (예: https://nas.company.local:8443)
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
    TIMEZONE = os.environ.get("TIMEZONE", "Asia/Seoul")

    # 로그인
    ALLOWED_EMAIL_DOMAINS = _list("ALLOWED_EMAIL_DOMAINS")  # 예: company.co.kr
    ADMIN_EMAILS = os.environ.get("ADMIN_EMAILS", "")  # 예: a@company.co.kr:홍길동,b@company.co.kr
    LOGIN_CODE_MINUTES = _int("LOGIN_CODE_MINUTES", 10)
    SESSION_HOURS = _int("SESSION_HOURS", 12)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    DEV_SHOW_CODES = _bool("DEV_SHOW_CODES", False)  # 테스트용: 인증코드를 화면에 표시

    # 전자서명
    SIGN_LINK_DAYS = _int("SIGN_LINK_DAYS", 7)
    SIGN_REQUIRE_LOGIN = _bool("SIGN_REQUIRE_LOGIN", False)  # True면 서명 전 메일 인증 로그인 필수

    # 메일 (Outlook / Microsoft 365 / 사내 Exchange)
    MAIL_BACKEND = os.environ.get("MAIL_BACKEND", "smtp" if os.environ.get("SMTP_HOST") else "console")
    MAIL_ASYNC = _bool("MAIL_ASYNC", True)
    MAIL_FROM_NAME = os.environ.get("MAIL_FROM_NAME", "상품권 수불관리")
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = _int("SMTP_PORT", 587)
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "")
    SMTP_STARTTLS = _bool("SMTP_STARTTLS", True)
    SMTP_SSL = _bool("SMTP_SSL", False)
    SMTP_TLS_VERIFY = _bool("SMTP_TLS_VERIFY", True)

    TRUST_PROXY = _bool("TRUST_PROXY", False)  # 리버스 프록시 뒤에서 실제 접속 IP 기록
    CSRF_DISABLED = False
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
