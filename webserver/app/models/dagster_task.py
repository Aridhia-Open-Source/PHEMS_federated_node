from datetime import datetime
from http import HTTPStatus

from sqlalchemy import Column, Integer, DateTime, String, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.helpers.const import ENABLE_IMAGE_WHITELIST
from app.helpers.base_model import BaseModel, db
from app.helpers.keycloak import Keycloak
from app.helpers.exceptions import InvalidRequest, TaskImageException
from app.models.dataset import Dataset
from app.models.container import Container
from app.models.registry import Registry
from app.models.request import Request

REVIEW_STATUS = {
    True: "Approved Release",
    False: "Blocked Release",
    None: "Pending Review"
}


class DagsterTask(db.Model, BaseModel):
    """
    A user-submitted request to run an experiment, handed off to Dagster.
    This model holds only domain metadata (who/what/which dataset/review
    status). Run state (running/succeeded/failed, logs, timing) is NOT
    stored here - it lives in Dagster's own run store, looked up via
    `dagster_run_id`.
    """
    __tablename__ = 'dagster_tasks'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    docker_image = Column(String(256), nullable=False)
    description = Column(String(4096))
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(DateTime(timezone=False), onupdate=func.now())
    requested_by = Column(String(256), nullable=False)
    review_status = Column(Boolean, nullable=True)
    dataset_id = Column(Integer, ForeignKey(Dataset.id, ondelete='CASCADE'))
    dataset = relationship("Dataset")

    # Set once the Dagster run has actually been launched. Nullable because
    # there may be a brief window between writing the row and the run
    # actually being submitted.
    dagster_run_id = Column(String(64), nullable=True)

    db_query = Column(JSON, default=dict)
    tags = Column(JSON, default=dict)

    def __init__(self,
                 name: str,
                 docker_image: str,
                 requested_by: str,
                 dataset: Dataset,
                 db_query: dict = None,
                 tags: dict = None,
                 description: str = '',
                 **kwargs):
        self.name = name
        self.docker_image = docker_image
        self.requested_by = requested_by
        self.dataset = dataset
        self.description = description
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.db_query = db_query or {}
        self.tags = tags or {}

    @classmethod
    def validate(cls, data: dict):
        data["name"] = (data.get("name") or "").replace(" ", "")
        if not data["name"]:
            raise InvalidRequest("name is a mandatory field")

        kc_client = Keycloak()
        user_token = Keycloak.get_token_from_headers()

        decoded_token = kc_client.decode_token(user_token)
        data["requested_by"] = kc_client.get_user_by_email(decoded_token["email"])["id"]
        user = kc_client.get_user_by_id(data["requested_by"])

        # Support only for one image at a time, the standard is executors == list
        executors = data["executors"][0]
        data["docker_image"] = executors["image"]
        repository = data.pop("repository", None)

        data = super().validate(data)

        # --- Dataset resolution ---
        if repository:
            from app.models.repository import Repository
            repo = Repository.query.filter(Repository.uri == repository.lower()).one_or_none()
            data["dataset"] = Dataset.query.filter(Dataset.repository_id == repo.id).one_or_none() if repo else None
            if data["dataset"] is None:
                raise InvalidRequest(f"No datasets linked with the repository {repository}")

        elif kc_client.is_user_admin(user_token):
            ds_id = data.get("tags", {}).get("dataset_id")
            ds_name = data.get("tags", {}).get("dataset_name")
            if ds_name or ds_id:
                data["dataset"] = Dataset.get_dataset_by_name_or_id(name=ds_name, id=ds_id)
            else:
                raise InvalidRequest("Administrators need to provide `tags.dataset_id` or `tags.dataset_name`")
        else:
            data["dataset"] = Request.get_active_project(
                data["project_name"],
                user["id"]
            ).dataset

        # --- Docker image validation ---
        Container.validate_image_format(data["docker_image"], data["docker_image"])

        if ENABLE_IMAGE_WHITELIST:
            if not Container.validate_image_whitelisted(data["docker_image"]):
                raise TaskImageException(f"Image {data['docker_image']} is not whitelisted", code=HTTPStatus.FORBIDDEN)

        if not Registry.validate_image_exist(data["docker_image"]):
            raise TaskImageException(f"Image {data['docker_image']} not found on our repository", code=HTTPStatus.NOT_FOUND)

        if data.get("db_query") is not None and "query" not in data["db_query"]:
            raise InvalidRequest("`db_query` field must include a `query`")

        return data

    def get_review_status(self) -> str:
        return REVIEW_STATUS[self.review_status]

    def sanitized_dict(self):
        san_dict = super().sanitized_dict()
        san_dict["review_status"] = self.get_review_status()
        return san_dict
