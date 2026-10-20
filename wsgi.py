from app import create_app

app = create_app()

if __name__ == "__main__":
    # 개발용 실행: python wsgi.py  (운영은 gunicorn 사용)
    import os
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")), debug=False)
