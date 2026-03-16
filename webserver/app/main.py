"""
Entrypoint for the webserver.
All general configs are taken care in here:
    - Exception handlers
    - Blueprint used
    - pre and post request handlers
"""
import logging
import traceback
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import exc
from werkzeug.exceptions import HTTPException

from app.helpers.exceptions import LogAndException
from app.helpers.base_model import SessionLocal
from app.routes import (
    general, admin, users, datasets, containers,
    tasks, registries
)

logging.basicConfig(level=logging.WARN)
logger: logging.Logger = logging.getLogger('main')
logger.setLevel(logging.INFO)

app = FastAPI()

for excp in [LogAndException, HTTPException]:
    @app.exception_handler(excp)
    async def exception_handler(_, e:LogAndException) -> JSONResponse:
        error_response = {"error": e.description}
        if getattr(e, "extra_fields", None):
            error_response["details"] = e.extra_fields
        return JSONResponse(error_response, status_code=getattr(e, 'code', 500))

# Need to register the exception handler this way as we need access
# to the db session
@app.exception_handler(exc.IntegrityError)
async def handle_db_exceptions(_, excp:exc.IntegrityError) -> JSONResponse:
    logging.error(excp)
    async with SessionLocal() as db:
        await db.rollback()
    return JSONResponse({"error": "Record already exists"}, status_code=500)

@app.exception_handler(RequestValidationError)
# Special case, just so we won't return stacktraces
async def pydandic_validation_handler(_, e:RequestValidationError) -> JSONResponse:
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
async def unknown_exception_handler(_, e:Exception) -> JSONResponse:
    logger.error("\n".join(traceback.format_exception(e)))
    async with SessionLocal() as db:
        await db.rollback()
    return JSONResponse({"error": "Internal Error"}, status_code=500)

app.include_router(admin.router)
app.include_router(containers.router)
app.include_router(datasets.router)
app.include_router(general.router)
app.include_router(registries.router)
app.include_router(tasks.router)
app.include_router(users.router)
