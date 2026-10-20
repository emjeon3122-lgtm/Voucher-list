# 설계 문서

## 1. 전체 구성

```
 [직원 PC/모바일 브라우저] ──HTTP(S)──▶ [NAS: Docker 컨테이너 voucher-ledger]
                                         ├─ Gunicorn + Flask (포트 8000)
                                         ├─ /data/voucher.db       (SQLite)
                                         └─ /data/signatures/*.png (서명 이미지)
                                                   │
                                                   └──SMTP──▶ [Microsoft 365 / 사내 Exchange] ──▶ 직원 아웃룩 메일함
```

- **권한**
  - 관리자(admin): 수불 대장 조회, 입출고, 취소, 서명 요청, 엑셀, 직원/권종 관리, 감사 로그
  - 직원(staff): 내 수령 내역 조회, 본인 서명

## 2. DB 구조 (SQLite)

```
users ─┬─< transactions >── voucher_types
       │        │ sign_request_id
       │        ▼
       └─< signature_requests ─< signature_request_items >─ transactions
login_codes, audit_log
```

### users: 직원
| 컬럼 | 설명 |
|---|---|
| id | PK |
| email | 회사 메일 (로그인 ID, 대소문자 무시, 유일) |
| name / department / employee_no | 성명 / 부서 / 사번 |
| role | `admin` 관리자, `staff` 직원 |
| is_active | 0이면 로그인 불가, 수령자 선택 불가 (퇴사자는 삭제하지 않고 비활성화) |

### voucher_types: 상품권 종류 + 권종
| 컬럼 | 설명 |
|---|---|
| name | 상품권 종류 (예: 신세계상품권) |
| face_value | 권종 금액 (예: 50000). 기록 보호를 위해 등록 후 수정 불가 |
| sort_order, is_active | 표시 순서, 사용 여부 |

### transactions: 수불 대장 (핵심 테이블)
| 컬럼 | 설명 |
|---|---|
| txn_date | 입고일 / 지급일 (YYYY-MM-DD) |
| direction | `IN` 입고(+), `OUT` 출고(−) |
| voucher_type_id, face_value | 권종 (face_value 는 등록 시점 값을 복사) |
| quantity, amount | 수량, 금액 (= 수량 × 권종) |
| serial_no | 일련번호 (선택) |
| counterparty | 구매처 (입고) |
| giver_id / recipient_id | 지급자 / 수령자 |
| purpose | 용도, 비고 |
| sign_status | `NONE`(입고), `UNREQUESTED` 미요청, `REQUESTED` 서명대기, `SIGNED` 서명완료 |
| sign_request_id | 최근 서명 요청 (서명 이미지는 이 요청에 저장) |
| is_void, void_reason, voided_by, voided_at | 취소(정정) 정보. **행은 삭제하지 않음** |
| created_by, created_at, updated_at | 등록자, 등록·변경 시각 (updated_at 은 화면 실시간 반영에 사용) |

**재고와 잔액은 저장하지 않고 매번 계산합니다.** 그래서 취소나 과거 일자 입력이 있어도 숫자가 어긋나지 않습니다.

```sql
-- 권종별 누적 재고, 총 잔액 (대장 각 행)
SUM(CASE WHEN is_void=1 THEN 0 WHEN direction='IN' THEN quantity ELSE -quantity END)
    OVER (PARTITION BY voucher_type_id ORDER BY txn_date, id)  AS qty_balance,
SUM(CASE WHEN is_void=1 THEN 0 WHEN direction='IN' THEN amount   ELSE -amount   END)
    OVER (ORDER BY txn_date, id)                                AS amount_balance
```

### signature_requests / signature_request_items: 전자서명
| 컬럼 | 설명 |
|---|---|
| token_hash | 메일 링크 토큰의 SHA-256 값. 원문 토큰은 DB에 저장하지 않으므로 DB가 유출돼도 링크를 만들 수 없음 |
| recipient_id, email | 수령자 |
| status | `PENDING` 대기, `SIGNED` 완료, `CANCELLED` 재발송·취소로 무효 |
| expires_at | 만료 시각 (기본 7일) |
| mail_sent_at / mail_error | 메일 발송 결과 (대장에 '메일오류'로 표시) |
| signed_at, signer_name, signer_ip, signer_ua | 서명 시각, 입력한 성명, 접속 IP, 브라우저/기기 |
| signature_file, signature_sha256 | 서명 PNG 파일명, 위변조 확인용 해시 |

`signature_request_items` 는 요청 1건(메일 1통)과 출고 내역 여러 건을 연결합니다.

### login_codes, audit_log
- `login_codes`: 로그인 인증코드 (HMAC 해시만 저장, 10분 만료, 5회 오입력 시 무효, 15분에 5회까지 요청 가능)
- `audit_log`: 로그인, 입고, 출고, 취소, 서명 요청, 서명 완료, 직원·권종 변경 이력 (IP 포함)

## 3. 처리 흐름

### 입고 / 출고
1. 관리자가 대장에서 [입고 등록] 또는 [출고 등록]을 누르고 일자, 권종, 수량 등을 입력합니다. 금액은 화면에서 자동 계산됩니다.
2. 출고는 `BEGIN IMMEDIATE` 트랜잭션 안에서 재고를 검사합니다. 동시에 두 명이 출고해도 재고가 음수가 되지 않습니다.
   - 검사 기준: 해당 일자 시점의 재고 **와** 그 이후 모든 시점의 재고 중 가장 작은 값 ≥ 출고 수량
3. 기록 후 대장의 권종 재고와 총 잔액이 즉시 다시 계산됩니다.

### 취소(정정)
- 행은 그대로 두고 `is_void=1` 과 사유를 기록합니다. 화면과 엑셀에는 취소선으로 표시되고, 재고·잔액 계산에서만 빠집니다.
- 입고를 취소해서 이후 재고가 음수가 되면 거부합니다. 관련 출고를 먼저 취소해야 합니다.

### 전자서명
```
관리자 [서명 요청] ─▶ 수령자별로 signature_requests 생성 (토큰 → 해시 저장)
                   ─▶ 출고 행 sign_status = REQUESTED
                   ─▶ 백그라운드로 SMTP 메일 발송 (결과는 mail_sent_at / mail_error 에 기록)
직원 메일 링크 열기 (/sign?t=토큰)
   ─▶ 토큰 해시로 요청 조회 → 상태·만료 확인 → 수령 내역 표시
   ─▶ 동의 체크 + 성명 입력(등록된 성명과 일치해야 함) + 캔버스 서명
   ─▶ 서버: PNG 검증(형식, 크기, 빈 서명 여부) → 흰 배경 PNG로 정규화 → data/signatures 에 저장
          → 요청 SIGNED, 출고 행 SIGNED (한 트랜잭션)
관리자 대장 화면: 10초마다 /api/ledger/version 확인 → 바뀌었으면 자동 새로고침 (입력 중일 때는 안내만 표시)
```

본인 확인 단계
1. 링크가 수령자 본인의 회사 메일함으로만 발송됩니다. 토큰은 추측이 불가능한 256비트 값입니다.
2. 등록된 성명을 입력해야 합니다.
3. (선택) `.env` 의 `SIGN_REQUIRE_LOGIN=1` 로 설정하면, 링크를 연 사람도 회사 메일 인증코드로 로그인해야 하고 로그인 계정이 수령자 본인이어야 서명할 수 있습니다.

## 4. 보안

- 비밀번호를 저장하지 않습니다. 로그인은 메일 인증코드 방식입니다.
- CSRF 토큰으로 모든 POST 요청을 보호합니다. 세션 쿠키에는 HttpOnly와 SameSite=Lax를 설정합니다.
- CSP, X-Frame-Options, Referrer-Policy(same-origin) 헤더를 사용합니다. 서명 토큰이 외부로 새는 것을 막습니다.
- 서명 토큰을 경로가 아닌 쿼리스트링으로 전달하고, Gunicorn 접속 로그에는 쿼리스트링을 기록하지 않습니다.
- 서명 이미지는 로그인한 관리자와 수령자 본인만 볼 수 있습니다.
- 서명 파일의 SHA-256 값을 DB와 엑셀에 함께 남깁니다. 파일이 바뀌었는지 확인할 수 있습니다.
