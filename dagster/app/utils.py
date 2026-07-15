import requests as req


class HttpClient:
    auth_type: str = "bearer"

    def __init__(self, base_uri: str, token: str = "", session=None):
        self._base_uri = base_uri.rstrip("/")
        self._session = session or req.Session()
        self._token = token
        self.setup_auth()

    @property
    def token(self) -> str:
        return self._token

    @token.setter
    def token(self, value: str):
        self._token = value
        self.setup_auth()

    def setup_auth(self):
        if not self._token:
            raise ValueError("Token must be initialized for setup")
        if not self.auth_type:
            raise ValueError("Auth type must be specified for setup")

        if self.auth_type.lower() == "bearer":
            self._set_bearer_token()
        else:
            raise ValueError(f"`Unsupported` auth type: {self.auth_type}")

    def _set_bearer_token(self):
        self._session.headers.update(
            {"Authorization": f"Bearer {self._token}"}
        )

    def request(
        self,
        method: str,
        path: str,
        raise_for_status: bool = True,
        **kwargs,
    ) -> req.Response:
        url = f"{self._base_uri}/{path.lstrip('/')}"
        response = self._session.request(method, url, timeout=10, **kwargs)
        if raise_for_status:
            response.raise_for_status()
        return response

    def get(self, path: str, **kwargs) -> req.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> req.Response:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs) -> req.Response:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs) -> req.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> req.Response:
        return self.request("DELETE", path, **kwargs)
