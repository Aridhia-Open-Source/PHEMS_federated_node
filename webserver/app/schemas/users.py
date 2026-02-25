from typing import Optional

from pydantic import BaseModel


class UserPost(BaseModel):
    email: str
    username: Optional[str] = None
    role: Optional[str] = "Users"


class ResetPassword(BaseModel):
    email: str
    temp_password: str
    new_password: str
