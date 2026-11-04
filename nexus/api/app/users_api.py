"""
user-related endpoints:
- GET /global/users
- POST /global/users
- PUT /global/users/reset-password
"""
from http import HTTPStatus

from fastapi import APIRouter, Body, Depends

from app.dtos.user import NewUserDTO, UserDTO
from app.helpers.const import PUBLIC_URL
from app.helpers.exceptions import InvalidRequest
from app.helpers.keycloak import KEYCLOAK_ADMIN, KEYCLOAK_SERVICE_USER, Keycloak
from app.helpers.wrappers import require_scope

router = APIRouter(prefix='/global/users', tags=["users"])


@router.post(
    '/', status_code=HTTPStatus.CREATED, response_model=NewUserDTO,
    dependencies=[Depends(require_scope('can_do_admin'))]
)
@router.post(
    '', status_code=HTTPStatus.CREATED, response_model=NewUserDTO,
    dependencies=[Depends(require_scope('can_do_admin'))]
)
def create_user(data: dict = Body(default_factory=dict)):
    """
    POST /global/users endpoint. Creates a KC user, and sets a temp
        password for them.
    """
    if data.get("email") is None:
        raise InvalidRequest("An email should be provided")

    # If a username is not provided, use the email
    if data.get("username") is None:
        data["username"] = data["email"]

    kc = Keycloak()
    if kc.get_user_by_email(email=data["email"]):
        raise InvalidRequest("User already exists")
    user_info = kc.create_user(set_temp_pass=True, **data)

    return {
        "email": data["email"],
        "username": user_info["username"],
        "tempPassword": user_info["password"],
        "info": "The user should change the temp password at " \
            f"https://{PUBLIC_URL}/global/users/reset-password"
    }


@router.put('/reset-password', status_code=HTTPStatus.NO_CONTENT)
def reset_password(body: dict = Body(default_factory=dict)):
    """
    PUT /global/users/reset-password endpoint. Interface to keycloak
        API, so we can change the credentials and make sure
        there are no pending action to undertake
    """
    kc = Keycloak()
    user = kc.get_user_by_email(email=body.get("email"))
    kc.reset_user_pass(
        user_id=user["id"], username=user["username"],
        old_pass=body.get("tempPassword"),
        new_pass=body.get("newPassword")
    )


@router.get('/', response_model=list[UserDTO], dependencies=[Depends(require_scope('can_do_admin'))])
@router.get('', response_model=list[UserDTO], dependencies=[Depends(require_scope('can_do_admin'))])
def get_users_list():
    """
    GET /global/users/ endpoint. This is a simplified version
    of what keycloak returns as a user list.
    """
    kc = Keycloak()
    ls_users = kc.list_users()
    return [{
            "username": user["username"],
            "email": user["email"],
            "firstName": user.get("firstName", ''),
            "lastName": user.get("lastName", ''),
            "role": kc.get_user_role(user["id"]),
            "needs_to_reset_password": user.get("requiredActions", []) != []
        } for user in ls_users if user["username"] not in (KEYCLOAK_ADMIN, KEYCLOAK_SERVICE_USER)
    ]
