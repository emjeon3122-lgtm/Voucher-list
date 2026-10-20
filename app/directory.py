"""회사 주소록(Microsoft 365 / Entra ID) 조회 — 수령자를 따로 명단으로 관리하지 않고 바로 찾습니다.

DIRECTORY_BACKEND
  graph : Microsoft Graph /users (Entra 앱에 User.Read.All(애플리케이션) 권한 필요). 사용 중지(퇴사)된 계정·게스트는 제외
  file  : DIRECTORY_FILE(JSON 목록)에서 찾기 — PC 시험·자동 테스트용
"""
import json
import re
import urllib.parse

from flask import current_app

from . import graph

FIELDS = "id,displayName,mail,userPrincipalName,department,jobTitle,employeeId,accountEnabled,userType"
MAX_RESULTS = 20


class DirectoryError(Exception):
    """주소록 서버 오류 (화면에 안내)."""


def _person(u):
    email = (u.get("mail") or u.get("userPrincipalName") or "").strip().lower()
    return {
        "id": u.get("id", ""),
        "name": (u.get("displayName") or "").strip(),
        "email": email,
        "department": (u.get("department") or "").strip(),
        "job_title": (u.get("jobTitle") or "").strip(),
        "employee_no": (u.get("employeeId") or "").strip(),
        "enabled": u.get("accountEnabled", True) is not False and u.get("userType", "Member") == "Member",
    }


def _allowed(p, domains):
    return p["enabled"] and "@" in p["email"] and (not domains or p["email"].split("@", 1)[1] in domains)


def search(query):
    """이름·메일 앞부분으로 재직 중인 직원 검색. 동명이인은 부서·직책·메일로 구분합니다."""
    cfg = current_app.config
    q = re.sub(r'["\\]', "", (query or "").strip())[:50]
    if not q:
        return []
    if cfg["DIRECTORY_BACKEND"] == "file":
        ql = q.lower()
        people = [p for p in map(_person, _load_file(cfg))
                  if p["name"].lower().startswith(ql) or p["email"].startswith(ql)]
    else:
        params = urllib.parse.urlencode({
            "$search": f'"displayName:{q}" OR "mail:{q}"',
            "$filter": "accountEnabled eq true and userType eq 'Member'",
            "$select": FIELDS, "$top": str(MAX_RESULTS), "$count": "true",
        }, quote_via=urllib.parse.quote)
        try:
            data = graph.request(cfg, "GET", f"/users?{params}", headers={"ConsistencyLevel": "eventual"})
        except Exception as e:  # noqa: BLE001
            current_app.logger.exception("주소록 검색 실패")
            raise DirectoryError("회사 주소록을 조회할 수 없습니다. 잠시 후 다시 시도하거나 전산 담당자에게 문의하세요.") from e
        people = [_person(u) for u in data.get("value", [])]
    people = [p for p in people if _allowed(p, cfg["ALLOWED_EMAIL_DOMAINS"])]
    people.sort(key=lambda p: (p["name"], p["department"], p["email"]))
    return people[:MAX_RESULTS]


def get(person_id):
    """주소록의 한 사람(현재 정보). 없거나 사용 중지(퇴사)·외부 계정이면 None."""
    cfg = current_app.config
    if not person_id or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", person_id):
        return None
    if cfg["DIRECTORY_BACKEND"] == "file":
        found = next((u for u in _load_file(cfg) if u.get("id") == person_id), None)
        p = _person(found) if found else None
    else:
        try:
            p = _person(graph.request(cfg, "GET", f"/users/{person_id}?$select={FIELDS}"))
        except graph.GraphError as e:
            if e.status == 404:
                return None
            current_app.logger.exception("주소록 조회 실패")
            raise DirectoryError("회사 주소록을 조회할 수 없습니다. 잠시 후 다시 시도해 주세요.") from e
        except Exception as e:  # noqa: BLE001
            current_app.logger.exception("주소록 조회 실패")
            raise DirectoryError("회사 주소록을 조회할 수 없습니다. 잠시 후 다시 시도해 주세요.") from e
    return p if p and _allowed(p, cfg["ALLOWED_EMAIL_DOMAINS"]) else None


def _load_file(cfg):
    with open(cfg["DIRECTORY_FILE"], encoding="utf-8") as fh:
        return json.load(fh)
