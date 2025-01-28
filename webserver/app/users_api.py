"""
user-related endpoints:
- GET /users
- POST /users
- PUT /users/reset-password
"""
from flask import Blueprint, request

from app.helpers.exceptions import InvalidRequest
from app.helpers.keycloak import KEYCLOAK_ADMIN, Keycloak
from app.helpers.const import PUBLIC_URL
from app.helpers.wrappers import audit, auth

bp = Blueprint('users', __name__, url_prefix='/users')


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_do_admin')
def create_user():
    """
    POST /users endpoint. Creates a KC user, and sets a temp
        password for them.
    """
    if not request.is_json:
        raise InvalidRequest("Request body should be a json")

    data = request.json
    if data.get("email") is None:
        raise InvalidRequest("An email should be provided")

    # If a username is not provided, use the email
    if data.get("username") is None:
        data["username"] = data["email"]

    kc = Keycloak()
    if kc.get_user_by_email(email=request.json.get("email")):
        raise InvalidRequest("User already exists")
    user_info = kc.create_user(set_temp_pass=True, **data)

    return {
        "email": data["email"],
        "username": user_info["username"],
        "tempPassword": user_info["password"],
        "info": "The user should change the temp password at " \
            f"https://{PUBLIC_URL}/users/reset-password"
    }, 201


@bp.route('reset-password', methods=['PUT'])
def reset_password():
    """
    POST /users/reset-password endpoint. Interface to keycloak
        API, so we can change the credentials and make sure
        there are no pending action to undertake
    """
    kc = Keycloak()
    user = kc.get_user_by_email(email=request.json.get("email"))
    kc.reset_user_pass(
        user_id=user["id"], username=user["username"],
        old_pass=request.json.get("tempPassword"),
        new_pass=request.json.get("newPassword")
    )
    return '', 204

@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_do_admin')
def get_users_list():
    """
    GET /users/ endpoint. This is a simplified version
    of what keycloak returns as a user list.
    """
    kc = Keycloak()
    ls_users = kc.list_users()
    normalised_list = [{
            "username": user["username"],
            "email": user["email"],
            "firstName": user.get("firstName", ''),
            "lastName": user.get("lastName", ''),
            "role": kc.get_user_role(user["id"]),
            "needs_to_reset_password": user.get("requiredActions", []) != []
        } for user in ls_users if user["username"] != KEYCLOAK_ADMIN
    ]

    return normalised_list, 200
