import json
import traceback


class LogAndException(Exception):
    """Turned into {"error": description, "details"?: extra_fields} with its code by app/errors.py."""
    code = 500
    description = None
    extra_fields = None

    def __init__(self, message:str = "", code=None, description: str | None = None) -> None:
        traceback.print_exc()
        self.description = message or getattr(self, "description") or description
        if code:
            self.code = code
        super().__init__(self.description)

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
    code = 403

class NotImplementedException(LogAndException):
    code = 501
    description = "Not implemented"

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

class DagsterError(LogAndException):
    code = 502

class ContainerRegistryException(LogAndException):
    pass

class FeatureNotAvailableException(LogAndException):
    code = 400
    def __init__(self, feature:str):
        description = f"The {feature} feature is not available on this Federated Node"
        super().__init__("", self.code, description)
