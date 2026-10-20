import logging
import os
import sqlite3
from datetime import timedelta

import click
from flask import Flask, render_template

from .config import Config


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    os.makedirs(os.path.join(app.config["DATA_DIR"], "signatures"), exist_ok=True)
    app.permanent_session_lifetime = timedelta(hours=app.config["SESSION_HOURS"])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if app.config["SECRET_KEY"] == "dev-insecure-change-me":
        app.logger.warning("SECRET_KEY 가 기본값입니다. 운영 환경에서는 반드시 .env 에서 변경하세요.")
    if app.config["TRUST_PROXY"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    from . import admin, auth, db, ledger, security, sign
    db.init_app(app)
    security.init_app(app)
    for bp in (auth.bp, ledger.bp, sign.bp, admin.bp):
        app.register_blueprint(bp)

    @app.template_filter("won")
    def won(v):
        return f"{int(v or 0):,}"

    @app.context_processor
    def _globals():
        return dict(app_name=app.config["APP_NAME"], company_name=app.config["COMPANY_NAME"])

    for code in (400, 403, 404, 410, 413, 429, 500):
        app.register_error_handler(code, _error_page)

    with app.app_context():
        db.init_db()
        db.seed_admins()

    _register_cli(app)
    return app


ERROR_TITLES = {400: "잘못된 요청", 403: "권한이 없습니다", 404: "페이지를 찾을 수 없습니다", 410: "만료된 요청",
                413: "파일이 너무 큽니다", 429: "요청이 너무 많습니다", 500: "서버 오류"}


def _error_page(e):
    code = getattr(e, "code", 500) or 500
    desc = getattr(e, "description", "")
    if code == 500:
        desc = "잠시 후 다시 시도하거나 관리자에게 문의하세요."
    elif desc == getattr(type(e), "description", None):
        desc = ""  # werkzeug 기본 영문 설명은 숨김
    return render_template("error.html", code=code, title=ERROR_TITLES.get(code, "오류"), description=desc), code


def _register_cli(app):
    @app.cli.command("create-admin")
    @click.argument("email")
    @click.argument("name")
    def create_admin(email, name):
        """관리자 계정 생성/승격:  flask --app wsgi create-admin a@company.co.kr 홍길동"""
        from .db import connect, db_path, upsert_admin, write_tx
        conn = connect(db_path())
        with write_tx(conn):
            upsert_admin(conn, email, name)
        conn.close()
        click.echo(f"관리자 등록 완료: {email} ({name})")

    @app.cli.command("backup")
    def backup():
        """DB 온라인 백업:  flask --app wsgi backup  →  data/backups/voucher_YYYYmmdd_HHMMSS.db"""
        from .db import db_path
        from .utils import now
        out_dir = os.path.join(app.config["DATA_DIR"], "backups")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"voucher_{now():%Y%m%d_%H%M%S}.db")
        src, dst = sqlite3.connect(db_path()), sqlite3.connect(out)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        click.echo(f"백업 완료: {out}")
