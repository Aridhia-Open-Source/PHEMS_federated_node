from pydantic import BaseModel


class DeliverySecretPost(BaseModel):
    auth: str
