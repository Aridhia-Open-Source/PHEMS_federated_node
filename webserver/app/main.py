"""
Entrypoint for the webserver.
All general configs are taken care in here:
    - Exception handlers
    - Blueprint used
    - pre and post request handlers
"""
import logging
import traceback
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import exc
from werkzeug.exceptions import HTTPException

from app.helpers.exceptions import LogAndException
from app.helpers.base_model import get_db

from fastapi import FastAPI


logging.basicConfig(level=logging.WARN)
logger = logging.getLogger('main')
logger.setLevel(logging.INFO)


app = FastAPI()

for excp in [LogAndException, HTTPException]:
    @app.exception_handler(excp)
    async def exception_handler(request, e:LogAndException) -> JSONResponse:
        error_response = {"error": e.description}
        if getattr(e, "extra_fields", None):
            error_response["details"] = e.extra_fields
        return JSONResponse(error_response, status_code=getattr(e, 'code', 500))

# Need to register the exception handler this way as we need access
# to the db session
@app.exception_handler(exc.IntegrityError)
async def handle_db_exceptions(request, excp:exc.IntegrityError) -> JSONResponse:
    logging.error(excp)
    with get_db() as db:
        db.rollback()
    return JSONResponse({"error": "Record already exists"}, status_code=500)

@app.exception_handler(ValidationError)
# Special case, just so we won't return stacktraces
async def pydandic_validation_handler(request, e:ValidationError) -> JSONResponse:
    list_of_messages = []
    for err in e.errors():
        list_of_messages.append({
            "type": err["type"],
            "field": err["loc"],
            "message": err["msg"]
        })
    return JSONResponse({"error": list_of_messages}, status_code=400)

@app.exception_handler(Exception)
# Special case, just so we won't return stacktraces
async def unknown_exception_handler(request, e:Exception) -> JSONResponse:
    logger.error("\n".join(traceback.format_exception(e)))
    with get_db() as db:
        db.rollback()
    return JSONResponse({"error": "Internal Error"}, status_code=500)

from app.routes import (
    general, admin, users, containers, tasks, registries
)
app.include_router(admin.router)
app.include_router(containers.router)
app.include_router(general.router)
app.include_router(registries.router)
app.include_router(tasks.router)
app.include_router(users.router)
