# NAS 배포 가이드

Docker(컨테이너)를 지원하는 NAS라면 같은 방법으로 설치할 수 있습니다.

- Synology: DSM 7.2 이상 'Container Manager'
- QNAP: 'Container Station'
- 일반 리눅스 서버도 동일

## 0. 준비물 체크리스트

| 항목 | 예시 | 비고 |
|---|---|---|
| NAS 내부 IP | `192.168.0.10` | 고정 IP 권장 (DHCP 예약) |
| 사용할 포트 | `8000` | 다른 서비스와 겹치면 변경 |
| 최초 관리자 메일 | `admin@company.co.kr` | |
| 회사 메일 도메인 | `company.co.kr` | 이 도메인만 로그인 허용 |
| 메일 발송 계정 | `voucher@company.co.kr` | 전용 공용 사서함 권장 |

---

## 1. 소스 복사

1. NAS에 `docker/voucher` 폴더를 만듭니다. (Synology: File Station → `docker` 공유폴더 → 새 폴더 `voucher`)
2. 이 저장소의 전체 파일(`app/`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `requirements.txt`, `wsgi.py`, `gunicorn.conf.py`)을 그 폴더에 올립니다.
   - GitHub에서 ZIP으로 내려받아 압축을 푼 뒤 업로드하거나, SSH로 접속해 `git clone` 해도 됩니다.

## 2. 설정 파일(.env) 작성

`.env.example` 을 복사해 `.env` 로 이름을 바꾸고 아래 항목을 수정합니다. (File Station의 텍스트 편집기나 SSH의 `vi` 사용)

```ini
SECRET_KEY=여기에-아주-긴-무작위-문자열      # 반드시 변경!
BASE_URL=http://192.168.0.10:8000           # 직원이 메일 링크로 접속할 주소
ALLOWED_EMAIL_DOMAINS=company.co.kr
ADMIN_EMAILS=admin@company.co.kr:홍길동
```

`SECRET_KEY` 생성 예시 (SSH):
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
# 또는
openssl rand -hex 32
```

> **BASE_URL 이 중요합니다.** 메일 속 서명 링크가 이 주소로 만들어집니다.
> 직원이 **사내망(사내 Wi-Fi)** 에서만 서명하면 NAS 내부 IP로 충분합니다.
> 외부(모바일 데이터)에서도 서명하게 하려면 아래 [6. 외부 접속 + HTTPS](#6-외부-접속--https-선택) 를 참고하세요.

## 3. 실행

### 방법 A. Synology Container Manager (화면)
1. **Container Manager → 프로젝트 → 생성**
2. 프로젝트 이름 `voucher`, 경로 `/docker/voucher` 를 선택합니다.
3. 원본에서 '기존 docker-compose.yml 사용'을 선택합니다.
4. 다음 → 완료를 누르면 이미지 빌드와 실행이 진행됩니다. (첫 빌드는 1~3분)
5. 컨테이너 `voucher-ledger` 상태가 **정상(healthy)** 인지 확인합니다.

### 방법 B. QNAP Container Station
1. **Container Station → 애플리케이션 → 생성**
2. `docker-compose.yml` 내용을 붙여넣습니다. 볼륨 경로는 `./data` 대신 절대경로(예: `/share/Container/voucher/data:/data`)로 바꿉니다.
3. `build: .` 를 사용하려면 소스 폴더 경로가 필요하므로, SSH로 해당 폴더에서 `docker compose up -d --build` 를 실행하는 방법(방법 C)을 권장합니다.

### 방법 C. SSH 명령어 (모든 NAS 공통)
```bash
ssh admin@192.168.0.10
cd /volume1/docker/voucher           # QNAP: /share/Container/voucher
sudo docker compose up -d --build
sudo docker compose ps               # STATUS 에 (healthy) 표시 확인
sudo docker logs -f voucher-ledger   # 로그 보기 (Ctrl+C 로 종료)
```

> 구형 NAS에서 `docker compose` 가 없으면 `docker-compose` (하이픈)로 실행하세요.

## 4. 첫 로그인과 메일 설정

### 4-1. 메일 설정 전 (테스트)
`.env` 의 `SMTP_HOST` 가 비어 있으면 메일을 보내지 않고 **로그에 내용을 출력**합니다.

1. 브라우저에서 `http://192.168.0.10:8000` 에 접속해 관리자 메일을 입력합니다.
2. Container Manager의 컨테이너 → 로그, 또는 `docker logs voucher-ledger` 에서 `인증코드: 123456` 을 확인해 입력합니다.
3. 상품권 종류와 직원을 등록하고 입출고를 테스트합니다. 서명 요청 메일 내용(링크 포함)도 로그에서 확인할 수 있습니다.

### 4-2. 아웃룩(Microsoft 365) 메일 연동

`.env`:
```ini
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_STARTTLS=1
SMTP_USER=voucher@company.co.kr
SMTP_PASSWORD=사서함비밀번호
SMTP_FROM=voucher@company.co.kr
MAIL_FROM_NAME=상품권 수불관리
```

Microsoft 365에서 확인할 것:
1. **SMTP AUTH 허용**: Microsoft 365 관리 센터 → 사용자 → 발송 계정 선택 → 메일 → 이메일 앱 관리 → **인증된 SMTP** 체크
   (테넌트 전체에서 SMTP AUTH가 꺼져 있으면 Exchange 관리 센터나 PowerShell로 해당 사서함만 허용: `Set-CASMailbox -Identity voucher@company.co.kr -SmtpClientAuthenticationDisabled $false`)
2. **보안 기본값/MFA** 를 쓰는 테넌트는 기본 인증이 막힐 수 있습니다. 이때는 아래 둘 중 하나를 쓰세요.
   - 사내 Exchange/메일 릴레이 서버를 사용 (4-3)
   - 메일 발송 전용 계정을 조건부 액세스 예외로 지정 (IT 담당자와 협의)
3. `SMTP_FROM` 은 `SMTP_USER` 와 같은 주소로 맞추세요. 다른 주소로 보내려면 '다른 사람으로 보내기' 권한이 필요합니다.

### 4-3. 사내 Exchange / 메일 릴레이 (인증 없이 내부 IP 허용)
```ini
SMTP_HOST=mail.company.local
SMTP_PORT=25
SMTP_STARTTLS=0
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=voucher@company.co.kr
```
메일 서버의 수신 커넥터(릴레이)에 NAS IP를 허용해야 합니다. 서버가 자체서명 인증서를 쓰면서 STARTTLS를 사용한다면 `SMTP_TLS_VERIFY=0` 으로 설정합니다.

### 4-4. 설정 변경 반영
`.env` 를 수정한 뒤에는 컨테이너를 다시 만들어야 적용됩니다.
```bash
sudo docker compose up -d        # 변경 감지 후 재생성
```
(Container Manager: 프로젝트 → 작업 → 빌드 또는 재시작)

## 5. 직원 일괄 등록

1. 엑셀에서 아래 형식으로 작성합니다. 첫 줄 머리글은 있어도 되고 없어도 됩니다.

   | 이메일 | 성명 | 부서 | 사번 | 권한 |
   |---|---|---|---|---|
   | kim@company.co.kr | 김철수 | 영업팀 | 1001 | |
   | lee@company.co.kr | 이영희 | 총무팀 | 1002 | 관리자 |

2. **다른 이름으로 저장 → CSV(쉼표로 분리)** 를 선택합니다. 'CSV UTF-8'과 일반 CSV(CP949) 모두 됩니다.
3. 관리 화면 **직원 관리 → CSV 일괄 등록** 에서 업로드합니다.

> 서명할 때 입력한 성명이 여기 등록된 성명과 같아야 합니다. (띄어쓰기는 무시)

## 6. 외부 접속 + HTTPS (선택)

직원이 사내망 밖(모바일 데이터)에서도 메일 링크로 서명해야 한다면:

1. **Synology 역방향 프록시** 설정: 제어판 → 로그인 포털 → 고급 → 역방향 프록시 → 생성
   - 소스: `HTTPS`, 호스트 이름 `voucher.company.co.kr`(또는 DDNS 주소), 포트 `443`
   - 대상: `HTTP`, `localhost`, 포트 `8000`
2. 인증서: 제어판 → 보안 → 인증서에서 Let's Encrypt 인증서를 발급받고 해당 서비스에 지정합니다.
3. 공유기(방화벽)에서 443 포트를 NAS로 포워딩합니다. (8000 포트는 외부에 열지 마세요)
4. `.env` 수정 후 재시작:
   ```ini
   BASE_URL=https://voucher.company.co.kr
   SESSION_COOKIE_SECURE=1
   TRUST_PROXY=1
   ```

> 외부에 공개하는 경우 서명 이외 기능(대장)은 로그인으로 보호되지만, 회사 보안 정책을 먼저 확인하세요. 본인 확인을 강화하려면 `SIGN_REQUIRE_LOGIN=1` 을 함께 설정하세요.

## 7. 백업과 복구

모든 데이터는 `docker/voucher/data` 폴더 하나에 있습니다.

- **권장**: Synology Hyper Backup(또는 QNAP HBS)으로 `docker/voucher/data` 폴더를 매일 백업
- **수동 백업** (운영 중에도 안전한 DB 사본 생성):
  ```bash
  sudo docker exec voucher-ledger flask --app wsgi backup
  # → data/backups/voucher_YYYYmmdd_HHMMSS.db
  ```
  작업 스케줄러(제어판 → 작업 스케줄러 → 사용자 정의 스크립트)에 위 명령을 매일 실행하도록 등록하면 자동으로 백업됩니다.
- **복구**:
  ```bash
  sudo docker compose stop
  cp data/backups/voucher_20261020_020000.db data/voucher.db
  rm -f data/voucher.db-wal data/voucher.db-shm
  sudo docker compose start
  ```
  서명 이미지(`data/signatures/`)도 함께 백업과 복구 대상입니다.

## 8. 업데이트

```bash
cd /volume1/docker/voucher
# 새 소스 파일로 교체 (data/ 와 .env 는 그대로 두기)
sudo docker compose up -d --build
```
DB 스키마는 앱 시작 시 자동으로 확인합니다. 기존 데이터는 유지됩니다.

## 9. 문제 해결

| 증상 | 확인할 것 |
|---|---|
| 접속이 안 됨 | `docker compose ps` 상태, NAS 방화벽에서 8000 포트 허용 여부 |
| 인증코드 메일이 안 옴 | `docker logs voucher-ledger` 의 SMTP 오류, 정크 메일함, 4-2의 SMTP AUTH 허용 여부 |
| 대장에 '메일오류' 표시 | 배지에 마우스를 올리면 오류 내용이 보임. 설정을 고친 뒤 해당 행을 체크하고 다시 '서명 요청' |
| 메일 링크를 누르면 접속 불가 | `BASE_URL` 이 직원 PC/모바일에서 접속 가능한 주소인지 확인 |
| 관리자 계정이 잠김/퇴사 | `sudo docker exec voucher-ledger flask --app wsgi create-admin new@company.co.kr 홍길동` |
| `database is locked` | 백업 프로그램이 DB 파일을 잠그는지 확인. 백업은 `flask backup` 사본을 대상으로 지정 |
| `Permission denied: /data` | NAS 폴더 권한 확인. `docker/voucher/data` 폴더에 쓰기 권한이 있어야 함 |
