"""Microsoft Graph 공통: 앱 전용(client credentials) 토큰과 요청 도우미. 메일 발송·회사 주소록 조회가 함께 씁니다."""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

GRAPH_URL = "https://graph.microsoft.com/v1.0"
_lock = threading.Lock()
_tokens = {}  # (tenant, client) -> (토큰, 만료 시각)


class GraphError(Exception):
    def __init__(self, status, message):
        super().__init__(f"Graph {status}: {message}")
        self.status = status


def token(cfg):
    """만료 5분 전까지 재사용합니다."""
    key = (cfg["GRAPH_TENANT_ID"], cfg["GRAPH_CLIENT_ID"])
    with _lock:
        cached = _tokens.get(key)
        if cached and cached[1] - 300 > time.time():
            return cached[0]
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials", "client_id": cfg["GRAPH_CLIENT_ID"],
            "client_secret": cfg["GRAPH_CLIENT_SECRET"], "scope": "https://graph.microsoft.com/.default",
        }).encode("ascii")
        url = f"https://login.microsoftonline.com/{cfg['GRAPH_TENANT_ID']}/oauth2/v2.0/token"
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        _tokens[key] = (data["access_token"], time.time() + int(data.get("expires_in", 3600)))
        return data["access_token"]


def request(cfg, method, path, payload=None, headers=None):
    """Graph 호출. 응답 JSON(본문 없으면 None). 오류는 GraphError."""
    hdrs = {"Authorization": f"Bearer {token(cfg)}", **(headers or {})}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(GRAPH_URL + path, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise GraphError(e.code, e.read().decode("utf-8", "replace")[:300]) from e
    return json.loads(raw.decode("utf-8")) if raw else None
