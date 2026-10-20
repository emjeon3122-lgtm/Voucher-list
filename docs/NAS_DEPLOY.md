# NAS 설치 안내 (IT 담당자)

실적 대시보드와 같은 NAS, 같은 방식(host 네트워크 + DSM 역방향 프록시 + Microsoft Entra ID 로그인)으로 설치합니다.

## 1. 구성

```
직원 PC·모바일 ──https──▶ DSM 역방향 프록시 :7031 ──http──▶ 127.0.0.1:7030 (voucher-ledger 컨테이너) ──▶ ./data
   (사내망 + SSL-VPN)                                               │
                                                                    ├─▶ login.microsoftonline.com  (로그인)
                                                                    └─▶ graph.microsoft.com        (서명 요청 메일 발송)
```

| 항목 | 값 (예시 — 실제 값으로 바꿔 쓰세요) |
|---|---|
| NAS | Synology DS1019+, DSM 7.3, Container Manager |
| 네트워크 | `network_mode: host` (이 NAS 는 컨테이너 간 bridge 통신 불가) |
| 앱 포트 | `127.0.0.1:7030` (http, NAS 안에서만). **실적 대시보드(7020/7021)와 겹치지 않게** |
| 사용자 주소 | `https://192.168.100.25:7031` (DSM 역방향 프록시 https 7031 → http://127.0.0.1:7030) |
| 접속 범위 | 사내망 + SSL-VPN. 인터넷 직접 공개 없음 |
| 로그인 | **관리자만** (Microsoft Entra ID, 허용 도메인 `bdo.kr`). 직원(수령자)은 로그인하지 않고 메일 링크로 서명만 함 |
| **리디렉션 URI** | **`https://192.168.100.25:7031/auth/callback`** (플랫폼: 웹) |
| 관리자 | `.env` 의 `ADMIN_EMAILS` (또는 화면에서 권한 '관리자', Entra 앱 역할 `Admin`) |
| 메일 발송 | Microsoft Graph (`Mail.Send`), 보내는 사서함 1개 |
| 자료 저장 | `./data` (SQLite DB 파일 1개 + 서명 이미지). 매일 자동 백업 `./data/backups` |

컨테이너 보안 설정은 실적 대시보드와 같습니다: 일반 계정으로 실행, 읽기 전용 파일시스템(`/data`·`/tmp` 만 쓰기),
`no-new-privileges`, `cap_drop: ALL`, 메모리 512MB·프로세스 200개 상한.

## 2. Microsoft Entra ID 앱 등록

1. Entra 관리 센터 › 앱 등록 › 새 등록
   - 이름: `상품권 수불 관리`
   - 지원되는 계정 유형: **이 조직 디렉터리의 계정만**(단일 테넌트)
   - 리디렉션 URI: 플랫폼 **웹**, `https://192.168.100.25:7031/auth/callback`
2. 인증서 및 암호 › 새 클라이언트 암호 → `.env` 의 `OIDC_CLIENT_SECRET` (**만료일을 기록해 두세요. 만료되면 로그인과 메일 발송이 멈춥니다**)
3. 개요 화면의 **디렉터리(테넌트) ID** → `OIDC_TENANT_ID`, **애플리케이션(클라이언트) ID** → `OIDC_CLIENT_ID`
4. (권장) 엔터프라이즈 애플리케이션 › 이 앱 › 속성 › **할당 필요 = 예**, 사용자 및 그룹에 **관리자 본인만** 할당합니다.
   접속하는 사람이 관리자 한 명뿐이므로, 다른 직원은 Microsoft 로그인 단계에서부터 막힙니다(앱도 관리자 외에는 거부합니다).
   관리자 지정은 `ADMIN_EMAILS` 로 충분하며, 앱 역할 `Admin` 은 관리자를 Entra 에서 관리하고 싶을 때만 만듭니다.
5. **메일 발송 권한** (서명 요청 메일을 Graph 로 보낼 때)
   - API 사용 권한 › 권한 추가 › Microsoft Graph › **애플리케이션 권한** › `Mail.Send` › **관리자 동의 허용**
   - `Mail.Send` 애플리케이션 권한은 기본적으로 **모든 사서함**으로 보낼 수 있으므로, Exchange Online 에서 보내는 사서함 1개로 제한하세요.
     ```powershell
     # Exchange Online PowerShell — 보내는 사서함만 들어 있는 메일 사용 보안 그룹을 먼저 만든 뒤
     New-ApplicationAccessPolicy -AppId <클라이언트 ID> -PolicyScopeGroupId voucher-senders@bdo.kr `
       -AccessRight RestrictAccess -Description "상품권 수불 관리: 발송 사서함만 허용"
     Test-ApplicationAccessPolicy -AppId <클라이언트 ID> -Identity voucher@bdo.kr   # Granted 확인
     ```
     (Exchange Online 의 'RBAC for Applications' 로 같은 제한을 걸어도 됩니다)
   - 메일 권한을 로그인용 앱에 주고 싶지 않으면 발송 전용 앱을 따로 등록하고 `GRAPH_TENANT_ID/GRAPH_CLIENT_ID/GRAPH_CLIENT_SECRET` 에 넣습니다.

로그인 흐름: Authorization Code + PKCE. ID 토큰 서명(RS256), 발급자, 대상, 만료, nonce, 테넌트(tid), 이메일 도메인을 검사합니다.
처음 로그인할 때 회사 메일로 명단의 관리자 계정과 연결하고, 이후로는 Microsoft 계정 고유값(oid)으로 찾습니다.

## 3. NAS 준비

1. 폴더 만들기: `/volume1/docker/voucher-ledger` (이 저장소 파일 전체를 여기에 복사)
2. 앱 실행 전용 계정을 만들고 이 폴더에만 읽기/쓰기 권한을 줍니다. SSH 에서 UID/GID 확인:
   ```sh
   id 계정명          # 예: uid=1030(voucher) gid=100(users)
   ```
3. 데이터 폴더를 만들고 소유자를 그 계정으로 지정합니다.
   ```sh
   cd /volume1/docker/voucher-ledger
   sudo mkdir -p data
   sudo chown -R 1030:100 data      # 위에서 확인한 UID:GID
   ```

## 4. 설정 (.env)

```sh
cp .env.example .env
vi .env
```

| 변수 | 내용 |
|---|---|
| `APP_UID`, `APP_GID` | 3번에서 확인한 실행 계정 UID/GID |
| `PUBLIC_URL` | `https://192.168.100.25:7031` |
| `PORT` / `HOST` | `7030` / `127.0.0.1` |
| `TRUST_PROXY` / `COOKIE_SECURE` | `true` / `true` |
| `SESSION_SECRET` | 32자 이상 임의 문자열 (`openssl rand -base64 48`). 바꾸면 모두 다시 로그인 |
| `ADMIN_EMAILS` | 관리자(접속하는 사람). 예: `eunmin.jeon@bdo.kr:전은민` |
| `AUTH_MODE` | `oidc` |
| `ALLOWED_EMAIL_DOMAINS` | `bdo.kr` |
| `OIDC_TENANT_ID` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | 2번 값 |
| `OIDC_ADMIN_ROLE` | `Admin` |
| `MAIL_BACKEND` | `graph` (설치 직후 시험은 `console` — 메일 대신 컨테이너 로그에 출력) |
| `MAIL_SENDER` | 보내는 사서함. 예: `voucher@bdo.kr` (공용 사서함 권장) |
| `BACKUP_HOUR` / `BACKUP_KEEP_DAYS` | 자동 백업 시각(기본 3시) / 보관 일수(30) |

비밀값은 `변수이름_FILE=/경로` 로 파일에서 읽게 할 수도 있습니다(`OIDC_CLIENT_SECRET_FILE` 등).

**설정이 위험하면 컨테이너가 시작되지 않고 로그에 이유가 나옵니다.**
(`SESSION_SECRET` 이 짧음, `AUTH_MODE=oidc` 인데 OIDC 값이 비었음, `PUBLIC_URL` 이 https 가 아님, 허용 도메인 없음 등)

## 5. 실행

**Container Manager:** 프로젝트 › 생성 › 경로 `/docker/voucher-ledger` › 기존 `docker-compose.yml` 사용 › 빌드·실행

**또는 SSH:**
```sh
cd /volume1/docker/voucher-ledger
sudo docker compose up -d --build
sudo docker compose ps                         # STATUS (healthy)
curl -s -D - -o /dev/null http://127.0.0.1:7030/healthz   # 200, X-App-Version: 버전
```

## 6. DSM 역방향 프록시·방화벽

1. DSM › 제어판 › 로그인 포털 › 고급 › 역방향 프록시 › 생성
   - 원본: `HTTPS`, 호스트 이름 `*`, 포트 `7031`
   - 대상: `HTTP`, `localhost`, 포트 `7030`
   - 사용자 지정 머리글 › `X-Forwarded-For` = `$proxy_add_x_forwarded_for` (서명자 IP 기록용)
2. 방화벽(들어오는 연결): TCP **7031** 만 사내망·VPN 대역에 엽니다. 7030 은 127.0.0.1 로만 열려 있어 외부에서 닿지 않습니다.
3. 나가는 연결(NAS → 외부)

   | 대상 | 용도 | 시점 |
   |---|---|---|
   | `login.microsoftonline.com:443` | 로그인, 메일 발송 토큰 | 상시 |
   | `graph.microsoft.com:443` | 서명 요청 메일 발송 (`MAIL_BACKEND=graph`) | 상시 |
   | Docker Hub (`registry-1.docker.io`, `auth.docker.io`, `production.cloudflare.docker.com`) | 기본 이미지 | 설치·업데이트 시 |
   | `pypi.org:443`, `files.pythonhosted.org:443` | 앱 의존성 설치 | 설치·업데이트 시 |

자체 서명 인증서라 브라우저에 "안전하지 않음" 경고가 뜨지만 로그인은 동작합니다(실적 대시보드와 같음).
정식 인증서·도메인이 정해지면 `PUBLIC_URL` 과 Entra 리디렉션 URI 만 바꾸면 됩니다.

> **모바일 서명:** 사용자 주소가 사내망 주소이므로, 직원 휴대폰이 **회사 Wi-Fi 또는 SSL-VPN** 에 연결돼 있어야 메일의 서명 링크가 열립니다.
> 서명 링크(`/sign`)는 로그인이 필요 없으므로 직원 쪽에서는 Microsoft 로그인 화면이 나오지 않습니다.

## 7. 처음 사용

1. `ADMIN_EMAILS` 의 관리자가 `https://192.168.100.25:7031` 에 접속 → **Microsoft 365 계정으로 로그인**
2. **수령자 명단** › "현재 명단 엑셀로 받기" → 상품권을 받을 직원의 이메일·성명·부서·사번을 채워 올리기 (엑셀에 없는 사람은 지워지지 않음)
3. **상품권 종류** 에서 권종 등록 (예: 신세계상품권 50,000 / 10,000)
4. **수불 대장** 에서 입고 → 출고(지급) + 서명 요청
5. `MAIL_BACKEND=console` 로 시험 중이면 서명 링크가 `docker logs voucher-ledger` 에 나옵니다. 확인 후 `graph` 로 바꾸고 `sudo docker compose up -d`.

직원은 메일의 링크를 누르면 로그인 없이 바로 서명 화면이 열립니다. 수령 확인 동의, 본인 성명 입력(명단의 성명과 같아야 함), 서명 순서입니다.

## 8. 백업과 복구

- 서버가 **매일 `BACKUP_HOUR` 시 이후 한 번** `data/backups/voucher-backup-YYYYMMDD.db` 를 만들고 `BACKUP_KEEP_DAYS` 일 지난 사본은 지웁니다.
- 지금 바로 사본 만들기: `sudo docker exec voucher-ledger flask --app wsgi backup` → `data/backups/manual-*.db`
- 서명 이미지(`data/signatures/`)는 한 번 저장되면 바뀌지 않는 파일이므로 사본을 따로 만들지 않습니다.
  **`data` 폴더 전체를 Snapshot Replication 또는 Hyper Backup 으로 백업**하세요.
- 복구:
  ```sh
  sudo docker compose stop
  cp data/backups/voucher-backup-20261020.db data/voucher.db
  rm -f data/voucher.db-wal data/voucher.db-shm
  sudo docker compose start
  ```

## 9. 업데이트

```sh
cd /volume1/docker/voucher-ledger
# 새 소스로 교체 (data/ 와 .env 는 그대로) — git 이면 git pull
sudo docker compose up -d --build
curl -s -D - -o /dev/null http://127.0.0.1:7030/healthz | grep -i x-app-version   # 새 버전 확인
```
DB 구조 변경은 시작할 때 자동 적용되고 기존 자료는 그대로입니다. 바뀐 점은 `CHANGELOG.md` 를 보세요.

## 10. 문제 해결

| 증상 | 확인할 것 |
|---|---|
| 컨테이너가 계속 재시작 | `docker logs voucher-ledger` 의 `운영 설정 오류` → `.env` 수정 |
| `Permission denied: /data` | `data` 폴더 소유자가 `APP_UID:APP_GID` 인지 (3번) |
| 로그인 버튼 → "Microsoft 로그인 서버에 연결할 수 없습니다" | NAS 에서 `login.microsoftonline.com:443` 나가는 연결, `OIDC_TENANT_ID` |
| Microsoft 화면에서 `AADSTS50011` | Entra 리디렉션 URI 가 `PUBLIC_URL` + `/auth/callback` 과 글자 하나까지 같은지 |
| "관리자 계정이 아닙니다" | 수령자 명단에서 그 계정의 권한이 '관리자'이고 '사용' 체크인지 (또는 `ADMIN_EMAILS`) |
| 대장에 '메일오류' | 배지에 마우스를 올리면 사유. `403`: Mail.Send 관리자 동의 / 사서함 제한 정책. `401`: 클라이언트 암호 만료. 고친 뒤 해당 행 체크 → '서명 요청' 다시 |
| 휴대폰에서 서명 링크가 안 열림 | 회사 Wi-Fi 또는 VPN 연결 |
| 관리자가 아무도 없음 | `sudo docker exec voucher-ledger flask --app wsgi create-admin 메일@bdo.kr 이름` |

## 부록: Entra 앱 등록 전 임시 운영

Entra 앱 등록이 늦어지면 `AUTH_MODE=email` 로 회사 메일 인증코드 로그인을 쓸 수 있습니다.
이때 인증코드도 메일로 나가므로 `MAIL_BACKEND` 가 동작해야 합니다(`console` 이면 코드가 컨테이너 로그에만 나옴).
SMTP 로 보내려면 `MAIL_BACKEND=smtp` 와 `SMTP_*` 를 채웁니다. Microsoft 365 는 테넌트에서 SMTP AUTH 를 막아 둔 경우가 많아
사내 메일 릴레이(`SMTP_PORT=25`, `SMTP_STARTTLS=false`, 인증 없음, NAS IP 허용)를 권장합니다.
