"""수불 관리 대장 화면 / 입출고 / 서명 요청 / 엑셀 다운로드."""
import os

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request,
                   send_file, url_for)

from . import mailer
from .auth import admin_required, login_required
from .db import get_db
from .services import (LedgerError, create_sign_requests, create_transaction, export_xlsx, ledger_rows,
                       ledger_totals, ledger_version, signature_dir, stock_summary, void_transaction)
from .utils import now_str, safe_next, today_str

bp = Blueprint("ledger", __name__)
FILTER_KEYS = ("date_from", "date_to", "type_id", "direction", "sign", "q")


def _filters():
    f = {k: (request.args.get(k) or "").strip() for k in FILTER_KEYS}
    f["hide_void"] = request.args.get("hide_void") == "1"
    return f


def _back():
    return redirect(safe_next(request.form.get("back")) or url_for("ledger.index"))


def send_request_mails(results):
    cfg = current_app.config
    messages = []
    for r in results:
        link = f"{cfg['PUBLIC_URL']}{url_for('sign.by_token', t=r['token'])}"
        msg = mailer.build(
            r["email"],
            f"[{cfg['APP_NAME']}] 상품권 수령 확인 서명 요청 ({r['name']}님)",
            "email/sign_request",
            req=r, link=link, requester=g.user,
        )
        messages.append((msg, r["request_id"]))
    if messages:
        mailer.send_sign_requests(messages, now_str())


@bp.route("/healthz", methods=["GET", "HEAD"])
def healthz():
    get_db().execute("SELECT 1").fetchone()
    return "ok", 200, {"X-App-Version": current_app.config["VERSION"], "Content-Type": "text/plain"}


@bp.get("/favicon.ico")
def favicon():
    return "", 204


@bp.get("/")
@login_required
def home():
    return redirect(url_for("ledger.index" if g.user["role"] == "admin" else "ledger.my"))


@bp.get("/ledger")
@admin_required
def index():
    db = get_db()
    f = _filters()
    rows = ledger_rows(db, f)
    stock = stock_summary(db)
    counts = db.execute(
        """SELECT SUM(sign_status = 'REQUESTED') AS requested, SUM(sign_status = 'UNREQUESTED') AS unrequested
             FROM transactions WHERE direction = 'OUT' AND is_void = 0"""
    ).fetchone()
    return render_template(
        "ledger.html",
        rows=rows, totals=ledger_totals(rows), stock=stock, f=f,
        total_qty=sum(s["qty"] for s in stock), total_balance=sum(s["balance"] for s in stock),
        requested=counts["requested"] or 0, unrequested=counts["unrequested"] or 0,
        types=db.execute("SELECT * FROM voucher_types ORDER BY sort_order, name, face_value DESC").fetchall(),
        users=db.execute("SELECT * FROM users WHERE is_active = 1 ORDER BY name, email").fetchall(),
        stock_by_type={s["id"]: s["qty"] for s in stock},
        today=today_str(), version=ledger_version(db),
    )


@bp.post("/ledger/in")
@admin_required
def add_in():
    try:
        txn_id = create_transaction(get_db(), "IN", request.form, g.user)
        flash(f"입고 등록 완료 (No.{txn_id})", "success")
    except LedgerError as e:
        flash(str(e), "error")
    return _back()


@bp.post("/ledger/out")
@admin_required
def add_out():
    db = get_db()
    try:
        txn_id = create_transaction(db, "OUT", request.form, g.user)
    except LedgerError as e:
        flash(str(e), "error")
        return _back()
    flash(f"출고(지급) 등록 완료 (No.{txn_id})", "success")
    if request.form.get("send_request"):
        try:
            results = create_sign_requests(db, [txn_id], g.user)
            send_request_mails(results)
            flash(f"{results[0]['name']}님에게 서명 요청 메일을 발송했습니다.", "success")
        except LedgerError as e:
            flash(f"서명 요청 실패: {e}", "error")
    return _back()


@bp.post("/ledger/<int:txn_id>/void")
@admin_required
def void(txn_id):
    try:
        void_transaction(get_db(), txn_id, request.form.get("reason"), g.user)
        flash(f"No.{txn_id} 내역을 취소 처리했습니다. (기록은 대장에 그대로 남습니다)", "success")
    except LedgerError as e:
        flash(str(e), "error")
    return _back()


@bp.post("/ledger/sign-request")
@admin_required
def sign_request():
    try:
        results = create_sign_requests(get_db(), request.form.getlist("txn_ids"), g.user)
        send_request_mails(results)
        names = ", ".join(r["name"] for r in results)
        flash(f"서명 요청 메일 {len(results)}통 발송: {names}", "success")
    except LedgerError as e:
        flash(str(e), "error")
    return _back()


@bp.get("/ledger/export.xlsx")
@admin_required
def export():
    db = get_db()
    bio = export_xlsx(ledger_rows(db, _filters()), stock_summary(db), current_app.config["APP_NAME"])
    return send_file(
        bio, as_attachment=True, download_name=f"상품권_수불대장_{today_str().replace('-', '')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.get("/api/ledger/version")
@admin_required
def version():
    return jsonify(version=ledger_version(get_db()))


@bp.get("/signature/<int:txn_id>.png")
@login_required
def signature_image(txn_id):
    row = get_db().execute(
        """SELECT t.recipient_id, sr.signature_file FROM transactions t
             JOIN signature_requests sr ON sr.id = t.sign_request_id
            WHERE t.id = ? AND t.sign_status = 'SIGNED'""",
        (txn_id,),
    ).fetchone()
    if row is None or not row["signature_file"]:
        abort(404)
    if g.user["role"] != "admin" and g.user["id"] != row["recipient_id"]:
        abort(403)
    path = os.path.join(signature_dir(), os.path.basename(row["signature_file"]))
    if not os.path.exists(path):
        abort(404)
    resp = send_file(path, mimetype="image/png", max_age=0)
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


@bp.get("/my")
@login_required
def my():
    db = get_db()
    pending = db.execute(
        """SELECT sr.*, (SELECT COUNT(*) FROM signature_request_items i JOIN transactions t ON t.id = i.transaction_id
                          WHERE i.request_id = sr.id AND t.is_void = 0) AS line_count
             FROM signature_requests sr
            WHERE sr.recipient_id = ? AND sr.status = 'PENDING' AND sr.expires_at >= ?
            ORDER BY sr.requested_at DESC""",
        (g.user["id"], now_str()),
    ).fetchall()
    rows = ledger_rows(db, {"recipient_id": g.user["id"]})
    return render_template("my.html", pending=[p for p in pending if p["line_count"]], rows=rows)
