"""
Entrypoint for the webserver.
All general configs are taken care in here:
    - Exception handlers
    - Blueprint used
    - pre and post request handlers
"""
import logging
from flask import Flask
from flask_swagger_ui import get_swaggerui_blueprint
from sqlalchemy import exc
from werkzeug.exceptions import NotFound

from app import (
    main, admin_api, datasets_api, tasks_api, requests_api,
    containers_api, registries_api, users_api
)
from app.helpers.base_model import build_sql_uri, db
from app.helpers.exceptions import (
    InvalidDBEntry, DBError, DBRecordNotFoundError, InvalidRequest,
    AuthenticationError, UnauthorizedError, KeycloakError, TaskImageException,
    ContainerRegistryException, TaskExecutionException, KubernetesException,
    exception_handler, unknown_exception_handler
)
from app.fn_flask import FNFlask


logging.basicConfig(level=logging.WARN)

def create_app():
    """
    Standard Flask initialization function
    """
    app = FNFlask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = build_sql_uri()

    swagger_ui_blueprint = get_swaggerui_blueprint(
        "/docs",
        "/static/openapi.json",
        config={
            'app_name': "Federated Node"
        }
    )

    app.register_blueprint(swagger_ui_blueprint, url_prefix="/docs")

    db.init_app(app)
    app.register_blueprint(main.bp)
    app.register_blueprint(datasets_api.bp)
    app.register_blueprint(requests_api.bp)
    app.register_blueprint(tasks_api.bp)
    app.register_blueprint(admin_api.bp)
    app.register_blueprint(containers_api.bp)
    app.register_blueprint(registries_api.bp)
    app.register_blueprint(users_api.bp)

    app.register_error_handler(InvalidDBEntry, exception_handler)
    app.register_error_handler(DBError, exception_handler)
    app.register_error_handler(DBRecordNotFoundError, exception_handler)
    app.register_error_handler(InvalidRequest, exception_handler)
    app.register_error_handler(AuthenticationError, exception_handler)
    app.register_error_handler(UnauthorizedError, exception_handler)
    app.register_error_handler(KeycloakError, exception_handler)
    app.register_error_handler(TaskImageException, exception_handler)
    app.register_error_handler(TaskExecutionException, exception_handler)
    app.register_error_handler(KubernetesException, exception_handler)
    app.register_error_handler(ContainerRegistryException, exception_handler)
    app.register_error_handler(NotFound, exception_handler)
    app.register_error_handler(Exception, unknown_exception_handler)

    # Need to register the exception handler this way as we need access
    # to the db session
    @app.errorhandler(exc.IntegrityError)
    def handle_db_exceptions(error):
        logging.error(error)
        db.session.rollback()
        return {"error": "Record already exists"}, 500

    @app.teardown_appcontext
    # pylint: disable=unused-argument
    def shutdown_session(exception=None):
        db.session.remove()

    return app
