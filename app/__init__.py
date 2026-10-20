import logging
import os
from datetime import timedelta

import click
from flask import Flask, render_template

from .config import Config, check_production

VERSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION")


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    check_production(app.config)
    try:
        with open(VERSION_FILE, encoding="utf-8") as fh:
            app.config["VERSION"] = fh.read().strip()
    except OSError:
        app.config["VERSION"] = "dev"
    os.makedirs(os.path.join(app.config["DATA_DIR"], "signatures"), exist_ok=True)
    app.permanent_session_lifetime = timedelta(hours=app.config["SESSION_HOURS"])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app.logger.info("상품권 수불 관리 %s 시작 (로그인: %s, 메일: %s)", app.config["VERSION"],
                    app.config["AUTH_MODE"], app.config["MAIL_BACKEND"])
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
        return dict(app_name=app.config["APP_NAME"], company_name=app.config["COMPANY_NAME"],
                    app_version=app.config["VERSION"])

    for code in (400, 403, 404, 410, 413, 429, 500):
        app.register_error_handler(code, _error_page)

    with app.app_context():
        db.init_db()
        db.sync_admins()

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
    @app.cli.command("backup")
    def backup():
        """지금 DB 사본 만들기:  flask --app wsgi backup  →  data/backups/manual-YYYYmmdd-HHMMSS.db"""
        from .backup import make_backup
        from .utils import now
        click.echo(f"백업 완료: {make_backup(app.config, f'manual-{now():%Y%m%d-%H%M%S}.db')}")
