"""로그인: 회사(아웃룩) 메일 주소로 6자리 인증코드를 받아 로그인합니다. 별도 비밀번호가 없습니다."""
import functools
import hmac
import re
import secrets
from datetime import timedelta

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for

from . import mailer
from .db import get_db, write_tx
from .services import audit
from .utils import hmac_hex, now, now_str, safe_next

bp = Blueprint("auth", __name__)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ATTEMPTS = 5


@bp.before_app_request
def load_user():
    g.user = None
    if request.endpoint == "static":
        return
    uid = session.get("uid")
    if uid:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ? AND is_active = 1", (uid,)).fetchone()
        if g.user is None:
            session.pop("uid", None)


def _to_login():
    target = request.full_path if request.query_string else request.path
    return redirect(url_for("auth.login", next=target))


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return _to_login()
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return _to_login()
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    nxt = safe_next(request.values.get("next"))
    if g.user is not None:
        return redirect(nxt or url_for("ledger.home"))
    if request.method == "GET":
        return render_template("login.html", next=nxt)

    cfg = current_app.config
    email = (request.form.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        flash("메일 주소를 올바르게 입력하세요.", "error")
        return render_template("login.html", next=nxt, email=email), 400
    domains = cfg["ALLOWED_EMAIL_DOMAINS"]
    if domains and email.split("@", 1)[1] not in domains:
        flash(f"회사 메일({', '.join('@' + d for d in domains)})만 사용할 수 있습니다.", "error")
        return render_template("login.html", next=nxt, email=email), 400

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not user["is_active"]:
        flash("등록되지 않았거나 사용이 중지된 계정입니다. 관리자에게 등록을 요청하세요.", "error")
        return render_template("login.html", next=nxt, email=email), 400

    recent = db.execute(
        "SELECT COUNT(*) FROM login_codes WHERE email = ? AND created_at >= ?",
        (email, now_str(now() - timedelta(minutes=15))),
    ).fetchone()[0]
    if recent >= 5:
        flash("인증코드 요청이 너무 많습니다. 15분 후 다시 시도하세요.", "error")
        return render_template("login.html", next=nxt, email=email), 429

    code = f"{secrets.randbelow(1_000_000):06d}"
    minutes = cfg["LOGIN_CODE_MINUTES"]
    with write_tx(db):
        db.execute("UPDATE login_codes SET used = 1 WHERE email = ? AND used = 0", (email,))
        db.execute(
            "INSERT INTO login_codes (email, code_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (email, hmac_hex(code), now_str(now() + timedelta(minutes=minutes)), now_str()),
        )
    msg = mailer.build(email, f"[{cfg['APP_NAME']}] 로그인 인증코드 {code}", "email/login_code",
                       user=user, code=code, minutes=minutes)
    try:
        mailer.send_now([msg])
    except RuntimeError as e:
        current_app.logger.error("로그인 코드 메일 실패 (%s): %s", email, e)
        flash("인증코드 메일 발송에 실패했습니다. 관리자에게 메일 서버 설정을 확인해 달라고 요청하세요.", "error")
        return render_template("login.html", next=nxt, email=email), 502

    session["login_email"] = email
    session["login_next"] = nxt
    if cfg["DEV_SHOW_CODES"]:
        flash(f"[테스트 모드] 인증코드: {code}", "info")
    return redirect(url_for("auth.verify"))


@bp.route("/login/verify", methods=["GET", "POST"])
def verify():
    email = session.get("login_email")
    if not email:
        return redirect(url_for("auth.login"))
    if request.method == "GET":
        return render_template("verify.html", email=email)

    db = get_db()
    code = re.sub(r"\D", "", request.form.get("code") or "")
    row = db.execute(
        "SELECT * FROM login_codes WHERE email = ? AND used = 0 ORDER BY id DESC LIMIT 1", (email,)
    ).fetchone()
    if row is None or row["expires_at"] < now_str() or row["attempts"] >= MAX_ATTEMPTS:
        flash("인증코드가 만료되었습니다. 다시 요청하세요.", "error")
        return redirect(url_for("auth.login"))
    if not hmac.compare_digest(row["code_hash"], hmac_hex(code)):
        with write_tx(db):
            db.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        left = MAX_ATTEMPTS - row["attempts"] - 1
        flash(f"인증코드가 올바르지 않습니다. (남은 시도 {left}회)", "error")
        return render_template("verify.html", email=email), 400

    user = db.execute("SELECT * FROM users WHERE email = ? AND is_active = 1", (email,)).fetchone()
    if user is None:
        abort(403)
    with write_tx(db):
        db.execute("UPDATE login_codes SET used = 1 WHERE id = ?", (row["id"],))
        audit(db, "LOGIN", f"user:{user['id']}", user["email"], user_id=user["id"])
    nxt = session.get("login_next")
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    return redirect(nxt or url_for("ledger.home"))


@bp.post("/logout")
def logout():
    session.clear()
    flash("로그아웃되었습니다.", "info")
    return redirect(url_for("auth.login"))
