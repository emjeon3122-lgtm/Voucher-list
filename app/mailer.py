"""메일 발송 (Microsoft 365 / 사내 메일).

MAIL_BACKEND
  graph   : Microsoft Graph API (/users/{MAIL_SENDER}/sendMail). Entra 앱에 Mail.Send(애플리케이션) 권한 필요
  smtp    : SMTP 발송 (사내 메일 릴레이 등)
  console : 발송하지 않고 서버 로그에 출력 (초기 설치/시험용)
  memory  : app.extensions["outbox"] 에 보관 (자동 테스트용)
"""
import json
import logging
import smtplib
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from flask import current_app, render_template

from .db import connect, db_path

log = logging.getLogger(__name__)

_SETTING_KEYS = (
    "MAIL_BACKEND", "MAIL_SENDER", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
    "SMTP_STARTTLS", "SMTP_SSL", "SMTP_TLS_VERIFY", "GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET",
)
GRAPH_URL = "https://graph.microsoft.com/v1.0"
_token_lock = threading.Lock()
_token = {"value": None, "exp": 0.0}


def build(to, subject, template, **ctx):
    """templates/<template>.txt / .html 로 본문을 만든 메일 객체."""
    cfg = current_app.config
    sender = cfg["MAIL_SENDER"] or cfg["SMTP_USER"] or "noreply@localhost"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["MAIL_FROM_NAME"], sender))
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    msg.set_content(render_template(template + ".txt", **ctx))
    msg.add_alternative(render_template(template + ".html", **ctx), subtype="html")
    return msg


def _graph_token(s):
    """앱 전용(client credentials) 토큰. 만료 5분 전까지 재사용합니다."""
    with _token_lock:
        if _token["value"] and _token["exp"] - 300 > time.time():
            return _token["value"]
        url = f"https://login.microsoftonline.com/{s['GRAPH_TENANT_ID']}/oauth2/v2.0/token"
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials", "client_id": s["GRAPH_CLIENT_ID"],
            "client_secret": s["GRAPH_CLIENT_SECRET"], "scope": "https://graph.microsoft.com/.default",
        }).encode("ascii")
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        _token.update(value=data["access_token"], exp=time.time() + int(data.get("expires_in", 3600)))
        return _token["value"]


def _graph_send(s, token, msg):
    payload = {
        "message": {
            "subject": str(msg["Subject"]),
            "body": {"contentType": "HTML", "content": msg.get_body(("html",)).get_content()},
            "toRecipients": [{"emailAddress": {"address": str(msg["To"])}}],
        },
        "saveToSentItems": True,
    }
    url = f"{GRAPH_URL}/users/{urllib.parse.quote(s['MAIL_SENDER'])}/sendMail"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Graph {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from e


def _deliver_graph(s, messages):
    try:
        token = _graph_token(s)
    except Exception as e:  # noqa: BLE001
        log.exception("Graph 토큰 발급 실패")
        return [], [(tag, f"Microsoft Graph 인증 실패: {e}") for _m, tag in messages]
    sent, failures = [], []
    for msg, tag in messages:
        try:
            _graph_send(s, token, msg)
            sent.append(tag)
        except Exception as e:  # noqa: BLE001
            log.exception("메일 발송 실패: %s", msg["To"])
            failures.append((tag, f"발송 실패: {e}"))
    return sent, failures


def _deliver(settings, outbox, messages):
    """messages: [(EmailMessage, tag)] -> (성공 tag 목록, [(tag, 오류)])"""
    backend = settings["MAIL_BACKEND"]
    if backend == "graph":
        return _deliver_graph(settings, messages)
    if backend in ("console", "memory"):
        for msg, _tag in messages:
            if backend == "memory":
                outbox.append(msg)
            else:
                body = msg.get_body(("plain",)).get_content()
                log.warning("[메일 미발송: console 모드] To=%s Subject=%s\n%s", msg["To"], msg["Subject"], body)
        return [tag for _m, tag in messages], []

    ctx = ssl.create_default_context()
    if not settings["SMTP_TLS_VERIFY"]:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        if settings["SMTP_SSL"]:
            server = smtplib.SMTP_SSL(settings["SMTP_HOST"], settings["SMTP_PORT"], timeout=30, context=ctx)
        else:
            server = smtplib.SMTP(settings["SMTP_HOST"], settings["SMTP_PORT"], timeout=30)
            server.ehlo()
            if settings["SMTP_STARTTLS"]:
                server.starttls(context=ctx)
                server.ehlo()
        if settings["SMTP_USER"]:
            server.login(settings["SMTP_USER"], settings["SMTP_PASSWORD"])
    except Exception as e:  # noqa: BLE001 - 어떤 오류든 화면/DB에 기록
        log.exception("SMTP 연결 실패")
        return [], [(tag, f"SMTP 연결 실패: {e}") for _m, tag in messages]

    sent, failures = [], []
    try:
        for msg, tag in messages:
            try:
                server.send_message(msg)
                sent.append(tag)
            except Exception as e:  # noqa: BLE001
                log.exception("메일 발송 실패: %s", msg["To"])
                failures.append((tag, f"발송 실패: {e}"))
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass
    return sent, failures


def _snapshot():
    app = current_app._get_current_object()
    settings = {k: app.config[k] for k in _SETTING_KEYS}
    return app, settings, app.extensions.setdefault("outbox", [])


def send_now(messages):
    """즉시 발송. 실패 시 RuntimeError (로그인 인증코드처럼 결과를 바로 알려야 할 때)."""
    _app, settings, outbox = _snapshot()
    _sent, failures = _deliver(settings, outbox, [(m, None) for m in messages])
    if failures:
        raise RuntimeError(failures[0][1])


def _record_results(path, ts, sent, failures):
    conn = connect(path)
    try:
        for req_id in sent:
            if req_id:
                conn.execute(
                    "UPDATE signature_requests SET mail_sent_at=?, mail_error=NULL WHERE id=?", (ts, req_id)
                )
        for req_id, err in failures:
            if req_id:
                conn.execute("UPDATE signature_requests SET mail_error=? WHERE id=?", (err[:500], req_id))
        conn.commit()
    finally:
        conn.close()


def send_sign_requests(messages, ts):
    """서명 요청 메일 발송. messages: [(EmailMessage, request_id)]
    발송 결과(성공 시각/오류)는 signature_requests 에 기록되어 대장 화면에 표시됩니다."""
    app, settings, outbox = _snapshot()
    path = db_path(app)

    def job():
        sent, failures = _deliver(settings, outbox, messages)
        _record_results(path, ts, sent, failures)

    if app.config["MAIL_ASYNC"]:
        threading.Thread(target=job, name="mail-sender", daemon=True).start()
    else:
        job()
