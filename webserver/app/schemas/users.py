from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class UserPost(BaseModel):
    email: str
    username: Optional[str] = None
    role: Optional[str] = "Users"


class ResetPassword(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)
    email: str
    temp_password: str
    new_password: str
