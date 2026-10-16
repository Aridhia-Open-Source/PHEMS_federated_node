import os
from flask import Flask
from app.helpers.base_model import db
from app.helpers.const import build_sql_uri
from app import main, mirrors
from app.clients import UnconfiguredGiteaClient, UnconfiguredGithubClient
from app.helpers.auth import check_bearer_token
from app.helpers.errors import register_error_handlers


def create_app(github_client=None, gitea_client=None):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = build_sql_uri()

    api_token = os.environ['GITEA_MIRROR_API_TOKEN']
    app.extensions['github_client'] = github_client or UnconfiguredGithubClient()
    app.extensions['gitea_client'] = gitea_client or UnconfiguredGiteaClient()

    db.init_app(app)
    register_error_handlers(app)
    app.before_request(lambda: check_bearer_token(api_token))
    app.register_blueprint(main.bp)
    app.register_blueprint(mirrors.bp)

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        db.session.remove()

    return app
