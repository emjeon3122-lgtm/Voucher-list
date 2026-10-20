"""수불 관리 대장 화면 / 입출고 / 서명 요청 / 엑셀 다운로드."""
import os

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request,
                   send_file, url_for)

from . import directory, mailer
from .auth import admin_required
from .db import get_db
from .services import (LedgerError, create_sign_requests, create_transaction, export_xlsx, ledger_rows,
                       ledger_totals, ledger_version, refresh_people, signature_dir, stock_summary,
                       void_transaction)
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
@admin_required
def home():
    return redirect(url_for("ledger.index"))


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
        # 화면에서 보낸 이름·메일은 믿지 않고, 고른 사람의 ID로 회사 주소록을 다시 조회합니다(퇴사자 차단).
        oid = request.form.get("recipient_oid", "")
        recipient = directory.get(oid) if oid else None
        if oid and recipient is None:
            raise LedgerError("선택한 수령자를 회사 주소록에서 찾을 수 없습니다(퇴사·계정 중지). 다시 검색해 주세요.")
        txn_id = create_transaction(db, "OUT", request.form, g.user, recipient)
    except (LedgerError, directory.DirectoryError) as e:
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
    db = get_db()
    try:
        recheck_recipients(db, request.form.getlist("txn_ids"))
        results = create_sign_requests(db, request.form.getlist("txn_ids"), g.user)
        send_request_mails(results)
        names = ", ".join(r["name"] for r in results)
        flash(f"서명 요청 메일 {len(results)}통 발송: {names}", "success")
    except (LedgerError, directory.DirectoryError) as e:
        flash(str(e), "error")
    return _back()


def recheck_recipients(db, txn_ids):
    """서명 요청 직전에 수령자를 회사 주소록에서 다시 확인합니다 (퇴사·메일 변경 반영)."""
    ids = [int(x) for x in txn_ids if str(x).isdigit()][:500]
    if not ids:
        return
    rows = db.execute(
        f"""SELECT DISTINCT u.id, u.directory_id FROM transactions t JOIN users u ON u.id = t.recipient_id
             WHERE t.id IN ({','.join('?' * len(ids))}) AND u.directory_id IS NOT NULL""", ids,
    ).fetchall()
    refresh_people(db, {r["id"]: directory.get(r["directory_id"]) for r in rows})


@bp.get("/api/directory/search")
@admin_required
def directory_search():
    try:
        people = directory.search(request.args.get("q", ""))
    except directory.DirectoryError as e:
        return jsonify(error=str(e)), 502
    return jsonify(results=[{k: p[k] for k in ("id", "name", "email", "department", "job_title")} for p in people])


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
@admin_required
def signature_image(txn_id):
    row = get_db().execute(
        """SELECT t.recipient_id, sr.signature_file FROM transactions t
             JOIN signature_requests sr ON sr.id = t.sign_request_id
            WHERE t.id = ? AND t.sign_status = 'SIGNED'""",
        (txn_id,),
    ).fetchone()
    if row is None or not row["signature_file"]:
        abort(404)
    path = os.path.join(signature_dir(), os.path.basename(row["signature_file"]))
    if not os.path.exists(path):
        abort(404)
    resp = send_file(path, mimetype="image/png", max_age=0)
    resp.headers["Cache-Control"] = "private, no-store"
    return resp
