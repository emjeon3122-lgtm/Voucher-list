"""DB 자동 백업: 매일 BACKUP_HOUR 시 이후 하루 한 번 DATA_DIR/backups 에 사본을 만들고 오래된 사본은 지웁니다.

서명 이미지(data/signatures)는 한 번 저장되면 바뀌지 않는 파일이라 사본을 따로 만들지 않습니다.
data 폴더 전체를 NAS 스냅샷/Hyper Backup 으로 백업하세요.
"""
import glob
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
PREFIX = "voucher-backup-"


def backup_dir(cfg):
    return cfg["BACKUP_DIR"] or os.path.join(cfg["DATA_DIR"], "backups")


def make_backup(cfg, name):
    """운영 중에도 안전한 SQLite 온라인 백업 (임시 파일에 쓴 뒤 이름 변경)."""
    out_dir = backup_dir(cfg)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, name)
    tmp = out + ".tmp"
    src = sqlite3.connect(os.path.join(cfg["DATA_DIR"], "voucher.db"), timeout=30)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, out)
    return out


def run_daily(cfg, now=None):
    """오늘 백업이 없고 BACKUP_HOUR 가 지났으면 백업합니다. 만든 파일 경로 또는 None."""
    now = now or datetime.now(ZoneInfo(cfg["TIMEZONE"]))
    if now.hour < cfg["BACKUP_HOUR"]:
        return None
    out_dir = backup_dir(cfg)
    name = f"{PREFIX}{now:%Y%m%d}.db"
    made = None
    if not os.path.exists(os.path.join(out_dir, name)):
        made = make_backup(cfg, name)
        log.info("자동 백업 완료: %s", made)
    cutoff = f"{PREFIX}{now - timedelta(days=cfg['BACKUP_KEEP_DAYS']):%Y%m%d}.db"
    for path in glob.glob(os.path.join(out_dir, PREFIX + "*.db")):
        if os.path.basename(path) < cutoff:
            os.remove(path)
    return made


def start_scheduler(cfg):
    """30분마다 확인하는 백그라운드 스레드 (gunicorn 마스터 프로세스에서 1개만 실행)."""
    cfg = dict(cfg)

    def loop():
        while True:
            try:
                run_daily(cfg)
            except Exception:  # noqa: BLE001 - 백업 실패가 서비스를 멈추지 않게
                log.exception("자동 백업 실패")
            time.sleep(30 * 60)

    threading.Thread(target=loop, name="auto-backup", daemon=True).start()
