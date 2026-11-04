import logging
import traceback
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import exc
from starlette.exceptions import HTTPException

from app.helpers.base_model import session
from app.helpers.exceptions import LogAndException

logger = logging.getLogger('main')


def _validation_message(error: RequestValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in e['loc'] if part != 'body') or 'body'}: {e['msg']}" for e in error.errors()
    )


def register_error_handlers(app: FastAPI):
    @app.exception_handler(LogAndException)
    def log_and_exception(_: Request, e: LogAndException):
        body = {"error": e.description}
        if e.extra_fields:
            body["details"] = e.extra_fields
        return JSONResponse(body, status_code=e.code)

    @app.exception_handler(HTTPException)
    def http_exception(_: Request, e: HTTPException):
        return JSONResponse({"error": e.detail}, status_code=e.status_code, headers=e.headers)

    @app.exception_handler(RequestValidationError)
    def validation_error(_: Request, e: RequestValidationError):
        # The previous backend's <int:...> route converters made a non-integer id a route miss
        if any(error["loc"][0] == "path" for error in e.errors()):
            return JSONResponse({"error": "Not Found"}, status_code=HTTPStatus.NOT_FOUND)
        return JSONResponse({"error": _validation_message(e)}, status_code=HTTPStatus.BAD_REQUEST)

    @app.exception_handler(exc.IntegrityError)
    def integrity_error(_: Request, e: exc.IntegrityError):
        logger.error(e)
        session.rollback()
        return JSONResponse({"error": "Record already exists"}, status_code=HTTPStatus.CONFLICT)

    @app.exception_handler(Exception)
    async def unknown_exception(_: Request, e: Exception):
        # The session middleware has rolled back already; this one runs outside it
        logger.error("\n".join(traceback.format_exception(e)))
        return JSONResponse({"error": "Internal Error"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
