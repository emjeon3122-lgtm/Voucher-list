"""로그인.

AUTH_MODE=oidc  : Microsoft 365(Entra ID) 회사 계정 로그인 (운영). 직원 명단에 등록된 사람만 들어올 수 있습니다.
AUTH_MODE=email : 회사 메일로 받은 6자리 인증코드로 로그인 (Entra 앱 등록 전 임시용).
"""
import functools
import hmac
import re
import secrets
from datetime import timedelta

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for

from . import mailer
from .db import get_db, write_tx
from .oidc import OidcClient, OidcError
from .services import audit
from .utils import hmac_hex, now, now_str, safe_next

bp = Blueprint("auth", __name__)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ATTEMPTS = 5


def _oidc():
    app = current_app
    if "oidc" not in app.extensions:
        app.extensions["oidc"] = OidcClient(app.config)
    return app.extensions["oidc"]


def _mode():
    return current_app.config["AUTH_MODE"]


@bp.before_app_request
def load_user():
    g.user = None
    if request.endpoint == "static":
        return
    uid = session.get("uid")
    if uid:
        row = get_db().execute("SELECT * FROM users WHERE id = ? AND is_active = 1", (uid,)).fetchone()
        if row is None:
            session.pop("uid", None)
            return
        g.user = dict(row)
        # Entra 앱 역할(OIDC_ADMIN_ROLE)을 받은 사람은 명단의 권한과 관계없이 관리자
        if session.get("sso_admin"):
            g.user["role"] = "admin"


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


def _start_session(user, sso_admin=False):
    nxt = session.get("login_next")
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    if sso_admin:
        session["sso_admin"] = True
    return redirect(nxt or url_for("ledger.home"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    nxt = safe_next(request.values.get("next"))
    if g.user is not None:
        return redirect(nxt or url_for("ledger.home"))
    if _mode() == "oidc":
        if request.method == "POST":
            abort(405)
        return render_template("login.html", next=nxt, mode="oidc")
    if request.method == "GET":
        return render_template("login.html", next=nxt, mode="email")
    return _email_send_code(nxt)


# --------------------------------------------------------------------------- Microsoft 365 (OIDC)

@bp.get("/auth/login")
def oidc_login():
    if _mode() != "oidc":
        abort(404)
    try:
        url, pending = _oidc().start()
    except Exception:  # noqa: BLE001 - 공급자 정보를 못 가져온 경우(네트워크·설정 오류)
        current_app.logger.exception("Microsoft 로그인 정보를 가져오지 못했습니다 (%s)", _oidc().issuer)
        flash("Microsoft 로그인 서버에 연결할 수 없습니다. 잠시 후 다시 시도하거나 전산 담당자에게 문의하세요.", "error")
        return redirect(url_for("auth.login"))
    session["oidc"] = pending
    session["login_next"] = safe_next(request.args.get("next"))
    return redirect(url)


@bp.get("/auth/callback")
def oidc_callback():
    if _mode() != "oidc":
        abort(404)
    pending = session.pop("oidc", None)  # 1회용: 같은 로그인 응답을 두 번 쓰지 못하게
    if request.args.get("error"):
        current_app.logger.warning("Microsoft 로그인 취소/거부: %s %s", request.args.get("error"),
                                   request.args.get("error_description", "")[:300])
        flash("Microsoft 로그인이 취소되었습니다.", "error")
        return redirect(url_for("auth.login"))
    try:
        ident = _oidc().finish(request.args.get("code"), request.args.get("state"), pending)
    except (OidcError, OSError, ValueError) as e:
        current_app.logger.warning("Microsoft 로그인 검증 실패: %s", e)
        flash(f"로그인하지 못했습니다: {e}" if isinstance(e, OidcError) else "로그인 처리 중 오류가 발생했습니다.", "error")
        return redirect(url_for("auth.login"))

    db = get_db()
    with write_tx(db):
        # 처음에는 명단의 회사 메일로 찾아 Microsoft 계정 고유값을 기록하고, 이후로는 그 값으로 찾습니다.
        user = db.execute("SELECT * FROM users WHERE sso_subject = ?", (ident["subject"],)).fetchone()
        if user is None:
            user = db.execute("SELECT * FROM users WHERE email = ?", (ident["email"],)).fetchone()
            if user is not None:
                if user["sso_subject"]:
                    current_app.logger.warning("%s 의 Microsoft 계정 연결을 새 값으로 갱신합니다.", ident["email"])
                db.execute("UPDATE users SET sso_subject = ?, updated_at = ? WHERE id = ?",
                           (ident["subject"], now_str(), user["id"]))
        if user is None or not user["is_active"]:
            current_app.logger.warning("직원 명단에 없거나 사용 중지된 계정의 로그인 시도: %s", ident["email"])
            flash(f"{ident['email']} 은(는) 직원 명단에 등록되지 않았거나 사용이 중지된 계정입니다. 관리자에게 등록을 요청하세요.",
                  "error")
            return redirect(url_for("auth.login"))
        sso_admin = current_app.config["OIDC_ADMIN_ROLE"] in ident["roles"]
        audit(db, "LOGIN", f"user:{user['id']}", f"{ident['email']} (Microsoft 365{' / 관리자 역할' if sso_admin else ''})",
              user_id=user["id"])
    return _start_session(user, sso_admin)


# --------------------------------------------------------------------------- 메일 인증코드 (임시)

def _email_send_code(nxt):
    cfg = current_app.config
    email = (request.form.get("email") or "").strip().lower()

    def fail(msg, status):
        flash(msg, "error")
        return render_template("login.html", next=nxt, email=email, mode="email"), status

    if not EMAIL_RE.match(email):
        return fail("메일 주소를 올바르게 입력하세요.", 400)
    domains = cfg["ALLOWED_EMAIL_DOMAINS"]
    if domains and email.split("@", 1)[1] not in domains:
        return fail(f"회사 메일({', '.join('@' + d for d in domains)})만 사용할 수 있습니다.", 400)
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not user["is_active"]:
        return fail("등록되지 않았거나 사용이 중지된 계정입니다. 관리자에게 등록을 요청하세요.", 400)
    recent = db.execute(
        "SELECT COUNT(*) FROM login_codes WHERE email = ? AND created_at >= ?",
        (email, now_str(now() - timedelta(minutes=15))),
    ).fetchone()[0]
    if recent >= 5:
        return fail("인증코드 요청이 너무 많습니다. 15분 후 다시 시도하세요.", 429)

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
        return fail("인증코드 메일 발송에 실패했습니다. 관리자에게 메일 설정을 확인해 달라고 요청하세요.", 502)

    session["login_email"] = email
    session["login_next"] = nxt
    if cfg["DEV_SHOW_CODES"]:
        flash(f"[시험 모드] 인증코드: {code}", "info")
    return redirect(url_for("auth.verify"))


@bp.route("/login/verify", methods=["GET", "POST"])
def verify():
    if _mode() != "email":
        abort(404)
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
        audit(db, "LOGIN", f"user:{user['id']}", f"{user['email']} (메일 인증코드)", user_id=user["id"])
    return _start_session(user)


@bp.post("/logout")
def logout():
    session.clear()
    flash("로그아웃되었습니다.", "info")
    return redirect(url_for("auth.login"))
