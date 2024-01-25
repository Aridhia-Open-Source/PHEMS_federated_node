from flask import Flask
from .helpers.db import build_sql_uri, db
from .exceptions import (
    InvalidDBEntry, DBError, DBRecordNotFoundError, InvalidRequest,
    handle_500
)


def create_app(test_config=None):
    app = Flask(__name__)
    # if test_config is not None:
    #     app.config.from_mapping(test_config)
    app.config["SQLALCHEMY_DATABASE_URI"] = build_sql_uri()
    db.init_app(app)
    from . import main, datasets, requests, admin, tasks
    app.register_blueprint(main.bp)
    app.register_blueprint(datasets.bp)
    app.register_blueprint(requests.bp)
    app.register_blueprint(tasks.bp)
    app.register_blueprint(admin.bp)

    app.register_error_handler(InvalidDBEntry, handle_500)
    app.register_error_handler(DBError, handle_500)
    app.register_error_handler(DBRecordNotFoundError, handle_500)
    app.register_error_handler(InvalidRequest, handle_500)

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        db.session.remove()

    return app
