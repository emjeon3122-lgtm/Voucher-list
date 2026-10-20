"""회사 주소록 연동: 동명이인 구분, 퇴사자 차단, 지급 당시 정보 보존."""
from app.db import connect, db_path
from conftest import DIRECTORY, sign_link, write_directory


def q(app, sql, *args):
    conn = connect(db_path(app))
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def issue(c, oid, qty=1, send=False):
    data = {"txn_date": "2026-01-10", "voucher_type_id": 1, "quantity": qty, "recipient_oid": oid}
    if send:
        data["send_request"] = "1"
    return c.post("/ledger/out", data=data)


def stock(c, qty=10):
    c.post("/ledger/in", data={"txn_date": "2026-01-05", "voucher_type_id": 1, "quantity": qty})


def test_search_shows_namesakes_and_hides_leavers(admin_client):
    res = admin_client.get("/api/directory/search?q=김철").get_json()["results"]
    assert [(p["name"], p["department"], p["email"]) for p in res] == [
        ("김철수", "개발팀", "kim.cs@co.kr"), ("김철수", "영업팀", "kim@co.kr")]
    assert admin_client.get("/api/directory/search?q=박퇴").get_json()["results"] == []   # 퇴사(사용 중지)
    assert admin_client.get("/api/directory/search?q=외부").get_json()["results"] == []   # 게스트
    assert admin_client.get("/api/directory/search?q=kim.cs").get_json()["results"][0]["id"] == "oid-kim2"


def test_search_requires_admin(app):
    assert app.test_client().get("/api/directory/search?q=김").status_code == 302


def test_issue_to_namesake_goes_to_right_person(app, admin_client, outbox):
    stock(admin_client)
    issue(admin_client, "oid-kim2", send=True)
    assert outbox[-1]["To"] == "kim.cs@co.kr"
    row = q(app, "SELECT rcpt_name, rcpt_email, rcpt_dept FROM transactions WHERE direction='OUT'")[0]
    assert tuple(row) == ("김철수", "kim.cs@co.kr", "개발팀")
    assert q(app, "SELECT COUNT(*) FROM users WHERE directory_id IS NOT NULL")[0][0] == 1  # 자동 저장, 명단 관리 불필요


def test_cannot_issue_to_leaver_or_unknown(app, admin_client):
    stock(admin_client)
    issue(admin_client, "oid-gone")
    issue(admin_client, "nobody")
    issue(admin_client, "")
    assert q(app, "SELECT COUNT(*) FROM transactions WHERE direction='OUT'")[0][0] == 0


def test_leaver_blocked_at_sign_request_time(app, admin_client, outbox, tmp_path):
    stock(admin_client)
    issue(admin_client, "oid-lee")  # 서명 요청은 나중에
    people = [dict(p) for p in DIRECTORY]
    next(p for p in people if p["id"] == "oid-lee")["accountEnabled"] = False  # 그 사이 퇴사
    write_directory(tmp_path / "directory.json", people)
    n = len(outbox)
    r = admin_client.post("/ledger/sign-request", data={"txn_ids": ["2"]}, follow_redirects=True)
    assert "퇴사" in r.get_data(as_text=True)
    assert len(outbox) == n
    assert q(app, "SELECT sign_status FROM transactions WHERE id=2")[0][0] == "UNREQUESTED"


def test_history_keeps_info_at_issue_time(app, admin_client, outbox, tmp_path):
    stock(admin_client)
    issue(admin_client, "oid-kim")
    people = [dict(p) for p in DIRECTORY]
    moved = next(p for p in people if p["id"] == "oid-kim")
    moved.update(department="전략팀", mail="kim.new@co.kr")  # 부서 이동·메일 변경
    write_directory(tmp_path / "directory.json", people)
    admin_client.post("/ledger/sign-request", data={"txn_ids": ["2"]})
    assert outbox[-1]["To"] == "kim.new@co.kr"  # 메일은 최신 주소로
    html = admin_client.get("/ledger").get_data(as_text=True)
    assert "영업팀" in html  # 대장에는 지급 당시 부서
    assert sign_link(outbox[-1])


def test_admin_list_follows_admin_emails(tmp_path):
    from app import create_app
    write_directory(tmp_path / "d.json", DIRECTORY)
    base = {"TESTING": True, "DATA_DIR": str(tmp_path), "MAIL_BACKEND": "memory", "DIRECTORY_BACKEND": "file",
            "DIRECTORY_FILE": str(tmp_path / "d.json")}
    create_app({**base, "ADMIN_EMAILS": "a@co.kr:가,b@co.kr:나"})
    app = create_app({**base, "ADMIN_EMAILS": "b@co.kr:나"})  # a 를 관리자에서 뺌
    roles = dict(q(app, "SELECT email, role FROM users"))
    assert roles == {"a@co.kr": "staff", "b@co.kr": "admin"}
