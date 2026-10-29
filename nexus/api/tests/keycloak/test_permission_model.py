import pytest
import responses
from responses import matchers
from datetime import datetime as dt, timedelta as td
from app.helpers.exceptions import KeycloakError
from app.helpers.keycloak import URLS, Keycloak
from tests.keycloak.test_keycloak_helper import TestKeycloakMixin


class TestKeycloakPolicies(TestKeycloakMixin):
  """
  """
  payload = {
      "name": "1-dataset Admin Policy",
      "description": f"List of users allowed to administrate the dataset dataset",
      "logic": "POSITIVE",
      "users": ["user_id"]
  }

  def test_get_policy_fails(self, keycloak_login_request_mock):
    """
    Simply tests that exceptions are raised with an unsuccessful response
    """
    keycloak_login_request_mock.add(
      responses.GET,
      URLS["policies"] % "clientid",
      match=[matchers.query_string_matcher(f"permission=False&name={self.payload["name"]}")],
      status=400
    )
    with pytest.raises(KeycloakError) as exc:
      Keycloak().get_policy(self.payload["name"])
    assert exc.value.description == "Error when fetching the policies from Keycloak"

  def test_create_policy(self, keycloak_login_request_mock):
    """
    Simply tests that no exceptions are raised with a successful response
    """
    keycloak_login_request_mock.add(
      responses.POST,
      (URLS["policies"] % "clientid") + "/user",
      json={"id": "policy_id"}
    )
    Keycloak().create_policy(self.payload, "/user")

  def test_create_policy_409_accepted(self, keycloak_login_request_mock):
    """
    Simply tests that no exceptions are raised with a 409 response. It also
    checks that the existing policy is fetched
    """
    keycloak_login_request_mock.add(
      responses.POST,
      (URLS["policies"] % "clientid") + "/user",
      json={"id": "policy_id"},
      status=409
    )
    keycloak_login_request_mock.add(
      responses.GET,
      URLS["policies"] % "clientid",
      json=[{"id": "policy_id"}],
      match=[matchers.query_string_matcher(f"permission=False&name={self.payload["name"]}")],
      status=200
    )
    Keycloak().create_policy(self.payload, "/user")

  def test_create_policy_failed_request(self, keycloak_login_request_mock):
    """
    Simply tests that exceptions are raised with an unsuccessful response
    """
    keycloak_login_request_mock.add(
      responses.POST,
      (URLS["policies"] % "clientid") + "/user",
      status=400
    )
    with pytest.raises(KeycloakError) as exc:
      Keycloak().create_policy(self.payload, "/user")
    assert exc.value.description == "Failed to create a project's policy"


class TestKeycloakScopes(TestKeycloakMixin):
  """
  """
  def test_get_scope_fails(self, keycloak_login_request_mock):
    """
    Simply tests that exceptions are raised with an unsuccessful response
    """
    keycloak_login_request_mock.add(
      responses.GET,
      URLS["scopes"] % "clientid",
      json=[{"id": "scope_id"}],
      match=[matchers.query_string_matcher(f"permission=False&name=can_admin_dataset")],
      status=400
    )
    with pytest.raises(KeycloakError) as exc:
      Keycloak().get_scope("can_admin_dataset")
    assert exc.value.description == "Error when fetching the scopes from Keycloak"

  def test_create_scope(self, keycloak_login_request_mock):
    """
    Simply tests that no exceptions are raised with a successful response
    """
    keycloak_login_request_mock.add(
      responses.POST,
      URLS["scopes"] % "clientid",
      json={"id": "permission_id"}
    )
    Keycloak().create_scope("can_admin_dataset")

  def test_create_scope_409_accepted(self, keycloak_login_request_mock):
    """
    Simply tests that no exceptions are raised with a 409 response
    """
    keycloak_login_request_mock.add(
      responses.POST,
      URLS["scopes"] % "clientid",
      json={"id": "permission_id"},
      status=409
    )
    keycloak_login_request_mock.add(
      responses.GET,
      URLS["scopes"] % "clientid",
      json=[{"id": "scope_id"}],
      status=200
    )
    Keycloak().create_scope("can_admin_dataset")

  def test_create_scope_failed_request(self, keycloak_login_request_mock):
    """
    Simply tests that exceptions are raised with an unsuccessful response
    """
    keycloak_login_request_mock.add(
      responses.POST,
      URLS["scopes"] % "clientid",
      status=400
    )
    with pytest.raises(KeycloakError) as exc:
      Keycloak().create_scope("can_admin_dataset")
    assert exc.value.description == "Failed to create a project's scope"


class TestKeycloakPermissions(TestKeycloakMixin):
  """
  """
  payload = {
    "name": "1-dataset Admin Permission",
    "description": "List of policies that will allow certain users or roles to administrate the dataset",
    "type": "resource",
    "logic": "POSITIVE",
    "decisionStrategy": "AFFIRMATIVE",
    "policies": ["admin_policy", "sys_policy", "policy"],
    "resources": ["resource_ds"],
    "scopes": ["scope_id"]
  }

  def test_create_permission(self, keycloak_login_request_mock):
    """
    Simply tests that no exceptions are raised with a successful response
    """
    keycloak_login_request_mock.add(
      responses.POST,
      URLS["permission"] % "clientid",
      json={"id": "permission_id"}
    )
    Keycloak().create_permission(self.payload)

  def test_create_permission_409_accepted(self, keycloak_login_request_mock):
    """
    Simply tests that no exceptions are raised with a 409 response
    """
    keycloak_login_request_mock.add(
      responses.POST,
      URLS["permission"] % "clientid",
      json={"id": "permission_id"},
      status=409
    )
    Keycloak().create_permission(self.payload)

  def test_create_permission_failed_request(self, keycloak_login_request_mock):
    """
    Simply tests that exceptions are raised with an unsuccessful response
    """
    keycloak_login_request_mock.add(
      responses.POST,
      URLS["permission"] % "clientid",
      status=400
    )
    with pytest.raises(KeycloakError) as exc:
      Keycloak().create_permission(self.payload)
    assert exc.value.description == "Failed to create a project's permission"

class TestKeycloakTimePolicy(TestKeycloakMixin):
  """
  Time policies are treated differently than a normal policy.
    - policy doesn't exist => create a new one
    - policy already exists => fetch it and update the time constraints
  """
  payload = {
      "name": "user_id Date access policy",
      "description": "Date range to allow the user to access a dataset within this project",
      "logic": "POSITIVE",
      "notBefore": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
      "notOnOrAfter": (dt.now() + td(days=1)).strftime("%Y-%m-%d %H:%M:%S")
  }

  def test_create_or_update_time_policy(self, keycloak_login_request_mock):
    """
    - policy doesn't exist => create a new one
    """
    keycloak_login_request_mock.add(
      responses.POST,
      (URLS["policies"] % "clientid") + "/time",
      json={"id": "policy_id"}
    )
    Keycloak().create_or_update_time_policy(self.payload, "/time")

  def test_create_or_update_time_policy_exists(self, keycloak_login_request_mock):
    """
    - policy already exists => fetch it and update the time constraints
    """
    keycloak_login_request_mock.add(
      responses.POST,
      (URLS["policies"] % "clientid") + "/time",
      status=409
    )
    keycloak_login_request_mock.add(
      responses.GET,
      URLS["policies"] % "clientid",
      match=[matchers.query_string_matcher(f"permission=False&name={self.payload["name"]}")],
      json=[{"id": "policy_id", "config": {"noa": "01/01/2025", "nbf": "02-01-2025"}}]
    )
    keycloak_login_request_mock.add(
      responses.PUT,
      (URLS["policies"] % "clientid") + "/policy_id"
    )
    Keycloak().create_or_update_time_policy(self.payload, "/time")

  def test_create_or_update_time_policy_fails(self, keycloak_login_request_mock):
    """
    policy patching fails
    """
    keycloak_login_request_mock.add(
      responses.POST,
      (URLS["policies"] % "clientid") + "/time",
      status=409
    )
    keycloak_login_request_mock.add(
      responses.GET,
      URLS["policies"] % "clientid",
      match=[matchers.query_string_matcher(f"permission=False&name={self.payload["name"]}")],
      json=[{"id": "policy_id", "config": {"noa": "01/01/2025", "nbf": "02-01-2025"}}]
    )
    keycloak_login_request_mock.add(
      responses.PUT,
      (URLS["policies"] % "clientid") + "/policy_id",
      status=400
    )
    with pytest.raises(KeycloakError) as exc:
      Keycloak().create_or_update_time_policy(self.payload, "/time")
    assert exc.value.description == "Failed to create a project's policy"
