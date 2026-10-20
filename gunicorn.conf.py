# gunicorn 설정 (Docker 컨테이너 안에서 사용)
import os

# host 네트워크로 실행하므로 기본은 NAS 안에서만 열리는 127.0.0.1. 외부 접속은 DSM 역방향 프록시(https)가 넘겨준다.
bind = f"{os.environ.get('HOST', '127.0.0.1')}:{os.environ.get('PORT', '7030')}"
workers = 2
threads = 4
timeout = 60
preload_app = True          # DB 초기화를 한 번만 실행
worker_tmp_dir = "/tmp"     # 읽기 전용 컨테이너에서도 동작하도록 tmpfs 사용
control_socket_disable = True
accesslog = "-"
errorlog = "-"
# 서명 링크 토큰(?t=...)이 접속 로그에 남지 않도록 쿼리스트링을 뺀 경로만 기록
access_log_format = '%({x-forwarded-for}i)s %(h)s "%(m)s %(U)s" %(s)s %(b)s %(L)ss'


def when_ready(server):
    # 자동 백업은 마스터 프로세스에서 하나만 돌린다 (워커 수만큼 중복 실행되지 않게).
    from app.backup import start_scheduler
    start_scheduler(server.app.wsgi().config)
