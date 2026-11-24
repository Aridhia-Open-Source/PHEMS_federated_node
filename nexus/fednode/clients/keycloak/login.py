"""
The OpenID Connect endpoints of one Keycloak realm: the token endpoint (every grant) and introspection.

A reply comes back as the response whatever its status: a refused login is an answer the caller reads and maps to its
own errors (ADR 0021), not an error of this client. A timeout or a connection failure is a ClientTimeout or a
ClientError. No credential is kept: the grants carry theirs, and the session has no Authorization header.
"""

from requests import Response

from fednode.http import DEFAULT_TIMEOUT, HttpClient


class KeycloakLogin(HttpClient):
    TOKEN_TYPE_PREFIX = "urn:ietf:params:oauth:token-type:"

    def __init__(self, base_uri: str, realm: str, session=None, timeout: tuple[float, float] = DEFAULT_TIMEOUT):
        super().__init__(base_uri, session=session, timeout=timeout)
        self._realm = realm

    @property
    def _openid(self) -> str:
        return f"/realms/{self._realm}/protocol/openid-connect"

    def realm_info(self) -> Response:
        """The realm's public page. A master realm that answers is a Keycloak that is up."""
        return self.get(f"/realms/{self._realm}", raise_for_status=False)

    def token(self, data: dict, headers: dict | None = None) -> Response:
        """Any grant: the form posted to the token endpoint."""
        return self.post(f"{self._openid}/token", data=data, headers=headers, raise_for_status=False)

    def password_grant(
        self, client_id: str, username: str, password: str, client_secret: str | None = None
    ) -> Response:
        """A public client (admin-cli) has no secret."""
        data = {"client_id": client_id, "grant_type": "password", "username": username, "password": password}
        if client_secret is not None:
            data["client_secret"] = client_secret
        return self.token(data)

    def refresh_grant(self, client_id: str, client_secret: str, refresh_token: str) -> Response:
        return self.token({
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })

    def exchange_grant(
        self,
        client_id: str,
        client_secret: str,
        subject_token: str,
        audience: str,
        requested_token_type: str,
        requested_subject: str | None = None,
    ) -> Response:
        """
        Token exchange: a token for the audience client, or for another user (`requested_subject`, an impersonation).
        `requested_token_type` is `access_token` or `refresh_token`.
        """
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "requested_token_type": f"{self.TOKEN_TYPE_PREFIX}{requested_token_type}",
            "subject_token": subject_token,
            "audience": audience,
        }
        if requested_subject is not None:
            data["requested_subject"] = requested_subject
        return self.token(data)

    def permission_decision(self, access_token: str, audience: str, permission: str) -> Response:
        """Whether the access token's owner holds `<resource id>#<scope>` on the audience client."""
        return self.token(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:uma-ticket",
                "audience": audience,
                "response_mode": "decision",
                "permission": permission,
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def introspect(self, client_id: str, client_secret: str, token: str) -> Response:
        return self.post(
            f"{self._openid}/token/introspect",
            data={"client_id": client_id, "client_secret": client_secret, "token": token},
            raise_for_status=False,
        )
