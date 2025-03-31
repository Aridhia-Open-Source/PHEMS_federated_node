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
    def __init__(self, description: str | None = None, code=None, response: Response | None = None) -> None:
        super().__init__(description, response)
        logger.info(description)
        self.description = description
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
    description = "An internal Keycloak error occurred"

class TaskImageException(LogAndException):
    description = "An error occurred with the Task's docker image"

class TaskExecutionException(LogAndException):
    description = "An error occurred with the Task execution"

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
    description = "A kubernetes error occurred. Check the logs for more info"

class ContainerRegistryException(LogAndException):
    description = "Failed to communicate with the Container Registry"
