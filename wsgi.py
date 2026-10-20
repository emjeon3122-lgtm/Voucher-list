from app import create_app

app = create_app()

if __name__ == "__main__":
    # 개발용 실행: python wsgi.py  (운영은 gunicorn 사용)
    app.run(host="0.0.0.0", port=8000, debug=False)
