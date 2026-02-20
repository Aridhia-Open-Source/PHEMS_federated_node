"""
Entrypoint for the webserver.
All general configs are taken care in here:
    - Exception handlers
    - Blueprint used
    - pre and post request handlers
"""
import logging
import traceback
from flask_swagger_ui import get_swaggerui_blueprint
from pydantic import ValidationError
from sqlalchemy import exc
from werkzeug.exceptions import HTTPException

from app import (
    main, admin_api, datasets_api, tasks_api, requests_api,
    containers_api, registries_api, users_api
)
from app.helpers.base_model import build_sql_uri, db
from app.helpers.exceptions import LogAndException
from app.fn_flask import FNFlask


logging.basicConfig(level=logging.WARN)
logger = logging.getLogger('main')
logger.setLevel(logging.INFO)

def create_app():
    """
    Standard Flask initialization function
    """
    app = FNFlask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = build_sql_uri()
    app.config["TRAP_HTTP_EXCEPTIONS"] = True

    swagger_ui_blueprint = get_swaggerui_blueprint(
        "/docs",
        "/static/openapi.json",
        config={
            'app_name': "Federated Node"
        }
    )

    for excp in [LogAndException, HTTPException]:
        @app.errorhandler(excp)
        def exception_handler(e:LogAndException):
            error_response = {"error": e.description}
            if getattr(e, "extra_fields", None):
                error_response["details"] = e.extra_fields
            return error_response, getattr(e, 'code', 500)

    # Need to register the exception handler this way as we need access
    # to the db session
    @app.errorhandler(exc.IntegrityError)
    def handle_db_exceptions(error):
        logging.error(error)
        db.session.rollback()
        return {"error": "Record already exists"}, 500

    @app.errorhandler(ValidationError)
    # Special case, just so we won't return stacktraces
    def pydandic_validation_handler(e:ValidationError):
        list_of_messages = []
        for err in e.errors():
            list_of_messages.append({
                "type": err["type"],
                "field": err["loc"],
                "message": err["msg"]
            })
        return {"error": list_of_messages}, 400

    @app.errorhandler(Exception)
    # Special case, just so we won't return stacktraces
    def unknown_exception_handler(e:Exception):
        logger.error("\n".join(traceback.format_exception(e)))
        db.session.rollback()
        return {"error": "Internal Error"}, 500

    app.register_blueprint(swagger_ui_blueprint, url_prefix="/docs")
    app.config["PROPAGATE_EXCEPTIONS"] = True

    db.init_app(app)
    app.register_blueprint(main.bp)
    app.register_blueprint(datasets_api.bp)
    app.register_blueprint(requests_api.bp)
    app.register_blueprint(tasks_api.bp)
    app.register_blueprint(admin_api.bp)
    app.register_blueprint(containers_api.bp)
    app.register_blueprint(registries_api.bp)
    app.register_blueprint(users_api.bp)

    @app.teardown_appcontext
    # pylint: disable=unused-argument
    def shutdown_session(exception=None):
        db.session.remove()

    return app
