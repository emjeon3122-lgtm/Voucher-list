# 변경 내역

버전은 화면 맨 아래와 `/healthz` 응답 머리글 `X-App-Version` 에 표시됩니다. 위쪽이 최신입니다.

## 2026.10.20
사내 NAS 운영 방식(실적 대시보드·경조사 화환 앱)에 맞춰 정리한 첫 운영 버전.
- **로그인**: Microsoft 365(Entra ID) 회사 계정 로그인(`AUTH_MODE=oidc`). Authorization Code + PKCE, ID 토큰 서명·발급자·대상·만료·nonce·테넌트·이메일 도메인 검사, state 1회용.
  직원 명단에 있는 사람만, 첫 로그인 때 메일로 연결 후 Microsoft 계정 고유값(oid)으로 찾음. Entra 앱 역할 `Admin` = 관리자.
  메일 인증코드 로그인은 Entra 앱 등록 전 임시용(`AUTH_MODE=email`)으로 남김.
- **전자서명 본인 확인**: 서명 링크를 연 사람이 Microsoft 로그인한 수령자 본인이어야 서명 가능(oidc 모드 기본).
- **메일**: Microsoft Graph `sendMail` 발송 추가(`MAIL_BACKEND=graph`, 권장). SMTP·console 도 유지.
- **NAS 배포**: host 네트워크 + 127.0.0.1:7030 + DSM 역방향 프록시 https 7031. 일반 계정(APP_UID/APP_GID) 실행, 읽기 전용,
  `no-new-privileges`, `cap_drop: ALL`, 메모리·프로세스 상한, 로그 10MB×3.
- **운영 설정 검사**: 짧은 `SESSION_SECRET`, 빈 OIDC 값, https 아닌 `PUBLIC_URL`, 허용 도메인 없음 등이면 시작하지 않음.
- **자동 백업**: 매일 `BACKUP_HOUR` 시 이후 DB 사본, `BACKUP_KEEP_DAYS` 일 보관.
- **직원 명단 엑셀**: 현재 명단 엑셀로 받기 / 엑셀(.xlsx)·CSV 일괄 등록(없는 직원은 지우지 않음).
- 보안 머리글 추가(COOP, Permissions-Policy, HSTS, no-store), 비밀값 `_FILE` 지원, 버전 표시.
- 설정 이름 변경: `BASE_URL` → `PUBLIC_URL`, `SECRET_KEY` → `SESSION_SECRET`, `SMTP_FROM` → `MAIL_SENDER` (옛 이름도 읽음).
- `data/` 형식 호환: 이전 DB 는 시작할 때 `users.sso_subject` 컬럼만 추가.
