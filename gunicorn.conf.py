# gunicorn 설정 (Docker 컨테이너 안에서 사용)
bind = "0.0.0.0:8000"
workers = 2
threads = 4
timeout = 60
preload_app = True  # DB 초기화를 한 번만 실행
accesslog = "-"
errorlog = "-"
# 서명 링크 토큰(?t=...)이 접속 로그에 남지 않도록 쿼리스트링을 뺀 경로만 기록
access_log_format = '%(h)s "%(m)s %(U)s" %(s)s %(b)s %(L)ss'
