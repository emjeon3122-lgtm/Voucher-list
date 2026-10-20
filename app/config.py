"""환경변수 기반 설정. 모든 값은 .env (docker-compose env_file) 로 주입합니다.

비밀값은 `변수이름_FILE=/경로` 로 파일에서 읽을 수도 있습니다 (예: OIDC_CLIENT_SECRET_FILE=/run/secrets/oidc).
"""
import os


def env(name, default=""):
    path = os.environ.get(name + "_FILE")
    if path:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    return os.environ.get(name, default)


def _bool(name, default=False):
    v = env(name)
    if v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _int(name, default):
    try:
        return int(env(name, default))
    except (TypeError, ValueError):
        return default


def _list(name):
    return [x.strip().lower() for x in env(name).split(",") if x.strip()]


class Config:
    APP_NAME = env("APP_NAME", "상품권 수불 관리")
    COMPANY_NAME = env("COMPANY_NAME")
    # DEV_MODE=1 이면 아래 '운영 설정 검사'를 건너뜁니다 (PC에서 시험할 때만).
    DEV_MODE = _bool("DEV_MODE", False)
    SECRET_KEY = env("SESSION_SECRET") or env("SECRET_KEY") or "dev-insecure-change-me"
    DATA_DIR = os.path.abspath(env("DATA_DIR", "data"))
    # 직원이 접속하는 주소 (DSM 역방향 프록시 https). 서명 링크와 Entra 리디렉션 URI(= 이 주소 + /auth/callback)에 쓰입니다.
    PUBLIC_URL = (env("PUBLIC_URL") or env("BASE_URL") or "http://localhost:8000").rstrip("/")
    TIMEZONE = env("TIMEZONE", "Asia/Seoul")

    # ---- 로그인 ----
    # oidc : Microsoft 365(Entra ID) 회사 계정 로그인 (운영)
    # email: 회사 메일로 받은 6자리 인증코드로 로그인 (Entra 앱 등록 전 임시용)
    AUTH_MODE = env("AUTH_MODE", "email").strip().lower()
    ALLOWED_EMAIL_DOMAINS = _list("ALLOWED_EMAIL_DOMAINS")
    ADMIN_EMAILS = env("ADMIN_EMAILS")  # 관리자(접속할 수 있는 사람). 예: a@bdo.kr:홍길동
    SESSION_HOURS = _int("SESSION_HOURS", 8)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("COOKIE_SECURE", _bool("SESSION_COOKIE_SECURE", False))
    TRUST_PROXY = _bool("TRUST_PROXY", False)  # 역방향 프록시 뒤에서 접속자 IP 기록

    OIDC_TENANT_ID = env("OIDC_TENANT_ID")
    OIDC_CLIENT_ID = env("OIDC_CLIENT_ID")
    OIDC_CLIENT_SECRET = env("OIDC_CLIENT_SECRET")
    OIDC_ISSUER = env("OIDC_ISSUER")  # 비우면 OIDC_TENANT_ID 로 자동 구성
    OIDC_ADMIN_ROLE = env("OIDC_ADMIN_ROLE", "Admin")  # 이 Entra 앱 역할을 받은 사람은 관리자

    # email 모드 전용
    LOGIN_CODE_MINUTES = _int("LOGIN_CODE_MINUTES", 10)
    DEV_SHOW_CODES = _bool("DEV_SHOW_CODES", False)  # 시험용: 인증코드를 화면에 표시

    # ---- 전자서명 ----
    SIGN_LINK_DAYS = _int("SIGN_LINK_DAYS", 7)

    # ---- 메일 ----
    # graph  : Microsoft Graph API 로 발송 (Microsoft 365 권장, Entra 앱에 Mail.Send 권한 필요)
    # smtp   : SMTP 발송 (사내 메일 릴레이 등)
    # console: 발송하지 않고 서버 로그에 출력 (초기 설치/시험용)
    MAIL_BACKEND = env("MAIL_BACKEND", "console").strip().lower()
    MAIL_ASYNC = _bool("MAIL_ASYNC", True)
    MAIL_FROM_NAME = env("MAIL_FROM_NAME", "상품권 수불관리")
    MAIL_SENDER = env("MAIL_SENDER") or env("SMTP_FROM")  # 보내는 사서함 주소
    # Graph 발송용 앱 (비우면 로그인용 OIDC 앱 값을 그대로 사용)
    GRAPH_TENANT_ID = env("GRAPH_TENANT_ID") or OIDC_TENANT_ID
    GRAPH_CLIENT_ID = env("GRAPH_CLIENT_ID") or OIDC_CLIENT_ID
    GRAPH_CLIENT_SECRET = env("GRAPH_CLIENT_SECRET") or OIDC_CLIENT_SECRET
    SMTP_HOST = env("SMTP_HOST")
    SMTP_PORT = _int("SMTP_PORT", 587)
    SMTP_USER = env("SMTP_USER")
    SMTP_PASSWORD = env("SMTP_PASSWORD")
    SMTP_STARTTLS = _bool("SMTP_STARTTLS", True)
    SMTP_SSL = _bool("SMTP_SSL", False)
    SMTP_TLS_VERIFY = _bool("SMTP_TLS_VERIFY", True)

    # ---- 자동 백업 ----
    BACKUP_HOUR = _int("BACKUP_HOUR", 3)  # 매일 이 시각 이후 하루 한 번 DB 백업
    BACKUP_KEEP_DAYS = _int("BACKUP_KEEP_DAYS", 30)
    BACKUP_DIR = env("BACKUP_DIR")  # 비우면 DATA_DIR/backups

    CSRF_DISABLED = False
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024


def check_production(cfg):
    """운영에서 위험한 설정이면 시작하지 않습니다 — 잘못된 채로 열리는 것보다 안 뜨는 편이 낫습니다."""
    if cfg.get("TESTING") or cfg.get("DEV_MODE"):
        return
    problems = []
    if len(cfg["SECRET_KEY"]) < 32 or cfg["SECRET_KEY"] == "dev-insecure-change-me":
        problems.append("SESSION_SECRET 을 32자 이상 임의 문자열로 지정하세요 (예: openssl rand -base64 48).")
    if cfg["AUTH_MODE"] not in ("oidc", "email"):
        problems.append("AUTH_MODE 는 oidc 또는 email 이어야 합니다.")
    if cfg["AUTH_MODE"] == "oidc":
        if not (cfg["OIDC_TENANT_ID"] or cfg["OIDC_ISSUER"]) or not cfg["OIDC_CLIENT_ID"] or not cfg["OIDC_CLIENT_SECRET"]:
            problems.append("AUTH_MODE=oidc 이면 OIDC_TENANT_ID, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET 이 모두 필요합니다.")
        if not cfg["PUBLIC_URL"].startswith("https://"):
            problems.append("PUBLIC_URL 을 https 주소로 지정하세요 (DSM 역방향 프록시 주소).")
    if not cfg["ALLOWED_EMAIL_DOMAINS"]:
        problems.append("ALLOWED_EMAIL_DOMAINS 에 회사 메일 도메인을 지정하세요 (예: bdo.kr).")
    if cfg["MAIL_BACKEND"] not in ("graph", "smtp", "console"):
        problems.append("MAIL_BACKEND 는 graph, smtp, console 중 하나여야 합니다.")
    if cfg["MAIL_BACKEND"] == "graph" and not (cfg["MAIL_SENDER"] and cfg["GRAPH_TENANT_ID"]
                                               and cfg["GRAPH_CLIENT_ID"] and cfg["GRAPH_CLIENT_SECRET"]):
        problems.append("MAIL_BACKEND=graph 이면 MAIL_SENDER 와 Entra 앱 값(OIDC_* 또는 GRAPH_*)이 필요합니다.")
    if cfg["MAIL_BACKEND"] == "smtp" and not cfg["SMTP_HOST"]:
        problems.append("MAIL_BACKEND=smtp 이면 SMTP_HOST 가 필요합니다.")
    if problems:
        raise RuntimeError("운영 설정 오류:\n- " + "\n- ".join(problems))
