import hashlib
import hmac
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import current_app, has_request_context, request


def now():
    """회사 기준 시간대(기본 Asia/Seoul)의 현재 시각 (naive datetime)."""
    return datetime.now(ZoneInfo(current_app.config["TIMEZONE"])).replace(tzinfo=None)


def now_str(dt=None):
    return (dt or now()).strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return now().strftime("%Y-%m-%d")


def valid_date(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def parse_int(v, default=None):
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def sha256_hex(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hmac_hex(value):
    key = current_app.config["SECRET_KEY"].encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def client_ip():
    return (request.remote_addr or "") if has_request_context() else ""


def safe_next(target):
    """오픈 리다이렉트 방지: 같은 사이트 내부 경로만 허용."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None
