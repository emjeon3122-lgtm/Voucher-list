"""관리자: 상품권 종류/권종, 감사 로그. (수령자는 회사 주소록에서 바로 찾으므로 명단 관리가 없습니다)"""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from .auth import admin_required
from .db import get_db, write_tx
from .services import audit
from .utils import now_str, parse_int

bp = Blueprint("admin", __name__, url_prefix="/admin")


# --------------------------------------------------------------------------- 상품권 종류/권종

@bp.get("/types")
@admin_required
def types():
    rows = get_db().execute(
        """SELECT vt.*, (SELECT COUNT(*) FROM transactions t WHERE t.voucher_type_id = vt.id) AS used
             FROM voucher_types vt ORDER BY vt.sort_order, vt.name, vt.face_value DESC"""
    ).fetchall()
    return render_template("admin/types.html", types=rows)


@bp.post("/types")
@admin_required
def type_create():
    db = get_db()
    name = (request.form.get("name") or "").strip()[:100]
    face = parse_int(request.form.get("face_value"))
    if not name or not face or face <= 0:
        flash("상품권 종류와 권종 금액을 입력하세요.", "error")
        return redirect(url_for("admin.types"))
    with write_tx(db):
        if db.execute("SELECT 1 FROM voucher_types WHERE name = ? AND face_value = ?", (name, face)).fetchone():
            flash(f"이미 등록된 권종입니다: {name} {face:,}원", "error")
            return redirect(url_for("admin.types"))
        db.execute("INSERT INTO voucher_types (name, face_value, sort_order, created_at) VALUES (?, ?, ?, ?)",
                   (name, face, parse_int(request.form.get("sort_order"), 0), now_str()))
        audit(db, "TYPE_CREATE", name, f"{face:,}원")
    flash(f"{name} {face:,}원권을 추가했습니다.", "success")
    return redirect(url_for("admin.types"))


@bp.post("/types/<int:type_id>")
@admin_required
def type_update(type_id):
    """종류명/정렬/사용여부만 변경 가능. 권종 금액은 기존 기록 보호를 위해 수정하지 않습니다."""
    db = get_db()
    name = (request.form.get("name") or "").strip()[:100]
    if not name:
        flash("상품권 종류명을 입력하세요.", "error")
        return redirect(url_for("admin.types"))
    with write_tx(db):
        cur = db.execute("SELECT face_value FROM voucher_types WHERE id = ?", (type_id,)).fetchone()
        dup = cur and db.execute("SELECT 1 FROM voucher_types WHERE name = ? AND face_value = ? AND id != ?",
                                 (name, cur["face_value"], type_id)).fetchone()
        if cur is None or dup:
            flash("같은 이름·권종이 이미 있거나 존재하지 않는 항목입니다.", "error")
            return redirect(url_for("admin.types"))
        db.execute("UPDATE voucher_types SET name=?, sort_order=?, is_active=? WHERE id=?",
                   (name, parse_int(request.form.get("sort_order"), 0),
                    1 if request.form.get("is_active") else 0, type_id))
        audit(db, "TYPE_UPDATE", f"type:{type_id}", name)
    flash("수정했습니다.", "success")
    return redirect(url_for("admin.types"))


# --------------------------------------------------------------------------- 감사 로그

@bp.get("/audit")
@admin_required
def audit_log():
    rows = get_db().execute(
        """SELECT a.*, u.name AS user_name, u.email AS user_email
             FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
            ORDER BY a.id DESC LIMIT 1000"""
    ).fetchall()
    return render_template("admin/audit.html", rows=rows)
