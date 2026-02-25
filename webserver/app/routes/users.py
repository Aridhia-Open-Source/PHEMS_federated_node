"""
user-related endpoints:
- GET /users
- POST /users
- PUT /users/reset-password
"""
from http import HTTPStatus
from fastapi import APIRouter, Depends, Request

from app.helpers.exceptions import InvalidRequest
from app.helpers.keycloak import KEYCLOAK_ADMIN, Keycloak
from app.helpers.const import PUBLIC_URL
from app.helpers.wrappers import Auth, audit
from app.schemas.users import ResetPassword, UserPost

router = APIRouter(tags=["users"], prefix="/users")


@router.post('', dependencies=[Depends(Auth("can_do_admin"))])
@audit
async def create_user(request: Request, body: UserPost):
    """
    POST /users endpoint. Creates a KC user, and sets a temp
        password for them.
    """
    # If a username is not provided, use the email
    if body.username is None:
        body.username = body.email

    kc = Keycloak()
    if kc.get_user_by_email(email=body.email):
        raise InvalidRequest("User already exists")
    user_info = kc.create_user(set_temp_pass=True, **body.model_dump())

    return {
        "email": body.email,
        "username": user_info["username"],
        "tempPassword": user_info["password"],
        "info": "The user should change the temp password at " \
            f"https://{PUBLIC_URL}/users/reset-password"
    }, HTTPStatus.CREATED


@router.put(
    '/reset-password',
    status_code=HTTPStatus.NO_CONTENT,
    dependencies=[Depends(Auth("can_do_admin"))]
)
async def reset_password(request: Request, body: ResetPassword):
    """
    POST /users/reset-password endpoint. Interface to keycloak
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


@router.get(
    '',
    status_code=HTTPStatus.OK,
    dependencies=[Depends(Auth("can_do_admin"))]
)
@audit
async def get_users_list(request: Request):
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

    return normalised_list
