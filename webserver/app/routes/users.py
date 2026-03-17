"""
user-related endpoints:
- GET /users
- POST /users
- PUT /users/reset-password
"""
from http import HTTPStatus
from fastapi import APIRouter, Depends, Request
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.helpers.exceptions import InvalidRequest
from app.helpers.keycloak import Keycloak
from app.helpers.wrappers import Auth, audit
from app.schemas.users import ResetPassword, UserPost
from app.helpers.base_model import get_db
from app.helpers.keycloak import Keycloak
from app.helpers.settings import settings, kc_settings


router = APIRouter(tags=["users"], prefix="/users")


@router.post('', status_code=HTTPStatus.CREATED, dependencies=[Depends(Auth("can_do_admin"))])
@audit
async def create_user(
    request: Request,
    body: UserPost,
    session: DBSession = Depends(get_db)
) -> dict[str, Any]:
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
            f"https://{settings.public_url}/users/reset-password"
    }

@router.put(
    '/reset-password',
    status_code=HTTPStatus.NO_CONTENT
)
async def reset_password(
    request: Request,
    body: ResetPassword,
    session: DBSession = Depends(get_db)
) -> None:
    """
    POST /users/reset-password endpoint. Interface to keycloak
        API, so we can change the credentials and make sure
        there are no pending action to undertake
    """
    kc = Keycloak()
    user = kc.get_user_by_email(email=body.email)
    kc.reset_user_pass(
        user_id=user["id"], username=user["username"],
        old_pass=body.temp_password,
        new_pass=body.new_password
    )


@router.get(
    '',
    status_code=HTTPStatus.OK,
    dependencies=[Depends(Auth("can_do_admin"))]
)
@audit
async def get_users_list(
    request: Request,
    session: DBSession = Depends(get_db)
) -> list[dict[str, Any]]:
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
        } for user in ls_users if user["username"] != kc_settings.keycloak_admin
    ]

    return normalised_list
