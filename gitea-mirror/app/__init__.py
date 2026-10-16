from flask import Flask
from app.helpers.base_model import db
from app.helpers.const import build_sql_uri
from app import main


def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = build_sql_uri()

    db.init_app(app)
    app.register_blueprint(main.bp)

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        db.session.remove()

    return app
