# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

상품권 수불 관리 및 전자서명 시스템 — Python 3.12 + Flask + SQLite (`app/`), Jinja 서버 렌더링 + 순수 JS/CSS (외부 CDN 없음).
See `README.md` (기능·구조), `docs/DESIGN.md` (DB·흐름·보안), `docs/NAS_DEPLOY.md` (운영 설치), `CHANGELOG.md`.

- Production runs on the company Synology NAS (DS1019+, DSM 7.3) the same way as the 실적 대시보드: `network_mode: host`
  (bridge between containers does not work on that NAS), app bound to `127.0.0.1:${PORT}` (7030), DSM reverse proxy https 7031
  in front, read-only container as `APP_UID:APP_GID`, all data under `./data` (`voucher.db`, `signatures/`, `backups/`).
- Login is Microsoft Entra ID OIDC + PKCE (`app/oidc.py`, `AUTH_MODE=oidc`, tenant `bdo.kr`); users must already be in the
  `users` roster (matched by email on first login, then `sso_subject`). Entra app role `OIDC_ADMIN_ROLE` grants admin.
  `AUTH_MODE=email` (mail code login) is only a temporary fallback.
- Mail goes through Microsoft Graph `sendMail` (`MAIL_BACKEND=graph`) or SMTP; `console`/`memory` for testing.
- `config.check_production` refuses to start on unsafe settings unless `TESTING` or `DEV_MODE`.
- Stock/balance are never stored — computed with window functions in `services.py`. Ledger rows are never deleted (void only).
- Bump `VERSION` and add a `CHANGELOG.md` entry for every release delivered to IT.
- Tests: `pip install -r requirements-dev.txt && pytest` (OIDC is tested against a fake provider in `tests/test_oidc.py`).

## Coding guidelines

- **BAT file encoding**: When creating `.bat` files that contain Korean (한글) text, be careful with character encoding. Windows batch files default to the system codepage (often CP949/EUC-KR on Korean Windows, not UTF-8), which can corrupt Korean text (mojibake) if the file is saved as UTF-8 without a matching `chcp` setting. Either save as CP949/ANSI to match the default codepage, or add `chcp 65001` at the top of the script and save the file as UTF-8 (without BOM) if UTF-8 is required — and verify it actually displays correctly in `cmd.exe`, not just in an editor.
- **Efficiency**: Always write efficient code — avoid unnecessary loops, redundant computation, or repeated I/O/network calls when a simpler or cached approach works.
- **No hardcoding**: Do not hardcode values that vary by environment or deployment (paths, credentials, hostnames, ports, magic constants). Use configuration, environment variables, or parameters instead.
- **Security**: Always consider security when writing code — validate/sanitize external input, avoid injection vulnerabilities (command, SQL, script), and never commit secrets or credentials.
