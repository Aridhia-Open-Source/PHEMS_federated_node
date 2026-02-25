from pydantic import BaseModel


class BeaconPost(BaseModel):
    dataset_id: int
    query: str
