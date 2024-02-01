from flask import Flask
from .helpers.db import build_sql_uri, db
from .exceptions import (
    InvalidDBEntry, DBError, DBRecordNotFoundError, InvalidRequest,
    AuthenticationError, KeycloakError, exception_handler
)


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = build_sql_uri()
    db.init_app(app)
    from . import main, datasets, requests, admin, tasks
    app.register_blueprint(main.bp)
    app.register_blueprint(datasets.bp)
    app.register_blueprint(requests.bp)
    app.register_blueprint(tasks.bp)
    app.register_blueprint(admin.bp)

    app.register_error_handler(InvalidDBEntry, exception_handler)
    app.register_error_handler(DBError, exception_handler)
    app.register_error_handler(DBRecordNotFoundError, exception_handler)
    app.register_error_handler(InvalidRequest, exception_handler)
    app.register_error_handler(AuthenticationError, exception_handler)
    app.register_error_handler(KeycloakError, exception_handler)

    @app.teardown_appcontext
    def shutdown_session():
        db.session.remove()

    return app
