from werkzeug.exceptions import HTTPException
from werkzeug.sansio.response import Response
import logging
import traceback

logger = logging.getLogger('exception_handler')
logger.setLevel(logging.INFO)

def exception_handler(e:HTTPException):
    return {"error": e.description}, getattr(e, 'code', 500)

# Special case, just so we won't return stacktraces
def unknown_exception_handler(e:Exception):
    logger.error("\n".join(traceback.format_exception(e)))
    return {"error": "Internal Error"}, 500

class LogAndException(HTTPException):
    code = 500
    def __init__(self, message:str = "", code=None, description: str | None = None, response: Response | None = None) -> None:
        super().__init__(description, response)
        traceback.print_exc()
        self.description = message or self.description
        if code:
            self.code = code

class InvalidDBEntry(LogAndException):
    code = 400

class DBError(LogAndException):
    code = 400

class DBRecordNotFoundError(LogAndException):
    code = 404

class InvalidRequest(LogAndException):
    code = 400

class AuthenticationError(LogAndException):
    code = 401
    description = "Unauthenticated"

class UnauthorizedError(LogAndException):
    code = 403
    description = "Unauthorized"

class KeycloakError(LogAndException):
    pass

class TaskImageException(LogAndException):
    pass

class TaskExecutionException(LogAndException):
    pass

class KubernetesException(LogAndException):
    pass

class ContainerRegistryException(LogAndException):
    pass
