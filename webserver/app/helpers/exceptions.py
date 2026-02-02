from http.client import HTTPException
from werkzeug.sansio.response import Response
import json
import re
import traceback


class LogAndException(HTTPException):
    code = 500
    description = None

    def __init__(self, message:str = "", code=None, description: str | None = None, response: Response | None = None) -> None:
        traceback.print_exc()
        self.description = message or getattr(self, "description") or description
        if code:
            self.code = code
        super().__init__(self.description, response)

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
        elif unsupp_values:
            self.description = unsupp_values
            self.code = 400
        else:
            self.code = 500
            self.description = self.details

class KubernetesException(LogAndException):
    def __init__(self, body:dict|str = None, code:int = None):
        try:
            body_json: dict = json.loads(body)
            self.code = body_json.pop("code")
            self.description = "".join("An unexpected kubernetes error occurred. Check the details field")
            self.extra_fields = body_json["details"]["causes"]
        except json.decoder.JSONDecodeError:
            self.description = body
        super().__init__()

class ContainerRegistryException(LogAndException):
    pass

class FeatureNotAvailableException(LogAndException):
    code = 400
    def __init__(self, feature:str, response = None):
        description = f"The {feature} feature is not available on this Federated Node"
        super().__init__("", self.code, description, response)
