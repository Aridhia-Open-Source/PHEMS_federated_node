from werkzeug.exceptions import HTTPException
from werkzeug.sansio.response import Response
import logging
import json
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

class TaskCRDExecutionException(LogAndException):
    """
    For the specific use case of CRD creation.
    Since we are reformatting the k8s exception body
    to be less verbose and more useful to the end user.
    Another benefit is that CRD validation happens at k8s level
    and we can just pick info up and be sure is accurate.
    """
    details = "Could not activate automatic delivery"

    def __init__(self, description = None, code=None, response = None):
        super().__init__(description, code, response)
        req_values = []
        unsupp_values = []
        for mess in json.loads(description)["details"]["causes"]:
            if "Unsupported value" in mess["message"]:
                unsupp_values.append(mess["message"])
            else:
                pass
        if req_values:
            self.description = {"Missing values": req_values}
            self.code = 400
        if unsupp_values:
            self.description = unsupp_values
            self.code = 400


class KubernetesException(LogAndException):
    pass

class ContainerRegistryException(LogAndException):
    pass

class FeatureNotAvailableException(LogAndException):
    description = "This feature is not available on this Federated Node"
    code = 400
