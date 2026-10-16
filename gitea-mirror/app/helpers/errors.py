from http import HTTPStatus
from flask import jsonify
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException
from app.helpers.base_model import db


class ApiError(Exception):
    def __init__(self, message: str, status: HTTPStatus):
        super().__init__(message)
        self.message = message
        self.status = status


class BadRequest(ApiError):
    def __init__(self, message: str):
        super().__init__(message, HTTPStatus.BAD_REQUEST)


class NotFound(ApiError):
    def __init__(self, message: str):
        super().__init__(message, HTTPStatus.NOT_FOUND)


class Conflict(ApiError):
    def __init__(self, message: str):
        super().__init__(message, HTTPStatus.CONFLICT)


class Unauthorized(ApiError):
    def __init__(self):
        super().__init__('Missing or invalid bearer token', HTTPStatus.UNAUTHORIZED)


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify({'error': err.message}), err.status

    @app.errorhandler(IntegrityError)
    def handle_integrity_error(err):
        db.session.rollback()
        return jsonify({'error': 'Conflicts with an existing record'}), HTTPStatus.CONFLICT

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        return jsonify({'error': err.description}), err.code
