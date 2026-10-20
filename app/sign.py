"""전자서명 페이지. 직원은 로그인 없이 메일로 받은 링크(1회용 토큰)로만 접근합니다."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from .db import get_db
from .services import LedgerError, complete_signature, find_request_by_token, request_lines
from .utils import now_str

bp = Blueprint("sign", __name__, url_prefix="/sign")


def _invalid(message, status=400):
    return render_template("sign_invalid.html", message=message), status


def _handle(req, self_url):
    db = get_db()
    if req is None:
        return _invalid("유효하지 않은 서명 링크입니다. 메일의 링크를 다시 확인해 주세요.", 404)
    recipient = db.execute("SELECT * FROM users WHERE id = ?", (req["recipient_id"],)).fetchone()
    if req["status"] == "SIGNED":
        return render_template("sign_done.html", req=req, recipient=recipient, lines=request_lines(db, req["id"]))
    if req["status"] == "CANCELLED":
        return _invalid("이 서명 요청은 취소되었거나 새 요청으로 대체되었습니다. 가장 최근에 받은 메일의 링크를 이용해 주세요.", 410)
    if req["expires_at"] < now_str():
        return _invalid("서명 기한이 지났습니다. 상품권 담당자에게 서명 요청을 다시 보내 달라고 요청해 주세요.", 410)
    lines = request_lines(db, req["id"])
    if not lines:
        return _invalid("서명할 내역이 없습니다. (지급 내역이 취소되었습니다)", 410)

    status = 200
    if request.method == "POST":
        if not request.form.get("agree"):
            flash("수령 확인 내용에 동의(체크)해 주세요.", "error")
            status = 400
        else:
            try:
                complete_signature(db, req["id"], request.form.get("signature"), request.form.get("signer_name"),
                                   request.headers.get("User-Agent"))
                return redirect(self_url)
            except LedgerError as e:
                flash(str(e), "error")
                status = 400
    return render_template("sign.html", req=req, recipient=recipient, lines=lines,
                           total=sum(r["amount"] for r in lines), action=self_url), status


@bp.route("", methods=["GET", "POST"])
def by_token():
    # 토큰은 경로가 아닌 쿼리스트링(?t=)으로 받아 웹서버 접속 로그에 남지 않게 합니다.
    token = request.args.get("t", "")
    req = find_request_by_token(get_db(), token)
    return _handle(req, url_for("sign.by_token", t=token))
