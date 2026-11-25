"""
user-related endpoints:
- GET /global/users
- POST /global/users
- PUT /global/users/reset-password (on reset_password_router, which needs no token: the temp-password flow)
"""
from http import HTTPStatus

from fastapi import APIRouter, Body, Depends

from app.config import settings
from app.dtos.user import NewUserDTO, NewUserRequest, UserDTO
from app.helpers.exceptions import InvalidRequest, UnauthorizedError
from app.clients.keycloak import Keycloak
from app.rules.authz import ADMIN_UNCHECKED, Access, Action
from app.helpers.wrappers import Caller, get_caller
from app.models.node_role import NodeRole

router = APIRouter(prefix='/global/users', tags=["users"])
# Unchecked: a new user swaps their temporary password, with no token and no record
reset_password_router = APIRouter(
    prefix='/global/users', tags=["users"], dependencies=[Depends(Access(action=Action.UNCHECKED))]
)


# Unchecked: users are Keycloak accounts, not records with grants; the admin roles gate it
@router.post(
    '', status_code=HTTPStatus.CREATED, response_model=NewUserDTO,
    dependencies=ADMIN_UNCHECKED,
)
def create_user(body: NewUserRequest, caller: Caller = Depends(get_caller)):
    """
    POST /global/users endpoint. Creates a KC user, and sets a temp
        password for them. The role is Users (default) or Administrator, which only the SuperUser may give.
    """
    if body.role == NodeRole.ADMINISTRATOR and caller.role != NodeRole.SUPERUSER:
        raise UnauthorizedError("Only the SuperUser can create an Administrator")
    data = body.model_dump(exclude_none=True) | {"username": body.username or body.email, "role": str(body.role)}

    kc = Keycloak()
    if kc.get_user_by_email(email=data["email"]):
        raise InvalidRequest("User already exists")
    user_info = kc.create_user(set_temp_pass=True, **data)

    return {
        "email": data["email"],
        "username": user_info["username"],
        "tempPassword": user_info["password"],
        "info": "The user should change the temp password at " \
            f"https://{settings.node.public_url}/global/users/reset-password"
    }


@reset_password_router.put('/reset-password', status_code=HTTPStatus.NO_CONTENT)
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


# Unchecked: Keycloak accounts, not records with grants; the admin roles gate it
@router.get('', response_model=list[UserDTO], dependencies=ADMIN_UNCHECKED)
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
        } for user in ls_users if user["username"] not in (settings.keycloak.admin, settings.keycloak.service_user)
    ]
