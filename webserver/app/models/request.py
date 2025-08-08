from datetime import datetime
import logging
from sqlalchemy import Column, Integer, DateTime, String, ForeignKey, update
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.exc import IntegrityError
from app.helpers.base_model import BaseModel, db
from app.models.dataset import Dataset
from app.helpers.keycloak import Keycloak
from app.helpers.exceptions import DBError, InvalidRequest, LogAndException


logger = logging.getLogger('request_model')
logger.setLevel(logging.INFO)


class Request(db.Model, BaseModel):
    __tablename__ = 'requests'
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    description = Column(String(4096))
    requested_by = Column(String(256), nullable=False)
    project_name = Column(String(256), nullable=False)
    status = Column(String(256), default='pending')
    proj_start = Column(DateTime(timezone=False), nullable=False)
    proj_end = Column(DateTime(timezone=False), nullable=False)
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(DateTime(timezone=False), onupdate=func.now())

    dataset_id = Column(Integer, ForeignKey(Dataset.id, ondelete='CASCADE'))
    dataset = relationship("Dataset")
    STATUSES = {
        'approved': 'approved',
        'pending': 'pending',
        'denied': 'denied'
    }

    def __init__(self,
                 title:str,
                 project_name:str,
                 dataset:Dataset,
                 requested_by:str,
                 proj_start:datetime,
                 proj_end:datetime,
                 description:str='',
                 **kwargs
        ):
        self.title = title
        self.description = description
        self.project_name = project_name
        # Not sure how to track the dataset yet, as DAR provider will have different IDs from the internal ones
        self.dataset = dataset
        self.requested_by = requested_by
        self.proj_start = proj_start
        self.proj_end = proj_end
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def _get_client_name(self, user_id:str):
        return f"Request {user_id} - {self.project_name}"

    @classmethod
    def validate(cls, data:dict):
        validated = super().validate(data)
        overlaps = cls.query.filter(
            cls.project_name == data["project_name"],
            cls.proj_end >= func.now(),
            cls.requested_by == data["requested_by"]
        ).one_or_none()

        if overlaps:
            raise InvalidRequest(f"User already belongs to the active project {data["project_name"]}")

        return validated

    def approve(self):
        """
        Method to orchestrate the Keycloak objects creation
        """
        session = db.session
        self.proj_end = self.proj_end.replace(hour=23, minute=59)
        try:
            global_kc_client = Keycloak()
            user = global_kc_client.get_user_by_id(self.requested_by)

            admin_global_policy = global_kc_client.get_role('Administrator')
            system_global_policy = global_kc_client.get_role('System')

            new_client_name = self._get_client_name(user["email"])
            token_lifetime = (self.proj_end - datetime.now()).seconds

            logger.info("Creating client %s", new_client_name)
            global_kc_client.create_client(new_client_name, token_lifetime)

            logger.info("%s - Getting admin token", new_client_name)
            kc_client = Keycloak(new_client_name)
            logger.info("%s - Token exchange", new_client_name)
            kc_client.enable_token_exchange()

            scopes = ["can_admin_dataset","can_exec_task", "can_admin_task", "can_access_dataset"]

            logger.info("%s - Creating scopes", new_client_name)
            created_scopes = []
            for scope in scopes:
                created_scopes.append(kc_client.create_scope(scope))

            ds = Dataset.query.filter(Dataset.id == self.dataset_id).one_or_none()

            logger.info("%s - Creating resource", new_client_name)
            resource = kc_client.create_resource({
                "name": f"{ds.id}-{ds.name}",
                "owner": {"id": kc_client.client_id, "name": new_client_name},
                "displayName": f"{ds.id} {ds.name}",
                "scopes": created_scopes,
                "uris": []
            })

            logger.info("%s - Creating policies", new_client_name)
            policies = []
            # Create admin policy
            policies.append(kc_client.create_policy({
                "name": f"{ds.id} - {ds.name} Admin Policy",
                "description": f"List of users allowed to administrate the {ds.name} dataset",
                "logic": "POSITIVE",
                "roles": [{"id": admin_global_policy["id"], "required": False}]
            }, "/role"))
            # Create system policy
            policies.append(kc_client.create_policy({
                "name": f"{ds.id} - {ds.name} System Policy",
                "description": f"List of users allowed to perform automated actions on the {ds.name} dataset",
                "logic": "POSITIVE",
                "roles": [{"id": system_global_policy["id"], "required": False}]
            }, "/role"))
            # Create the requester's policy
            user_policy = kc_client.create_policy({
                "name": f"{ds.id} - {ds.name} User {user["id"]} Policy",
                "description": f"User specific permission to perform actions on the {ds.name} dataset",
                "logic": "POSITIVE",
                "decisionStrategy": "UNANIMOUS",
                "type": "user",
                "users": [user["id"]]
            }, "/user")
            # Create project date policy
            date_range_policy = kc_client.create_or_update_time_policy({
                "name": f"{user["id"]} Date access policy",
                "description": "Date range to allow the user to access a dataset within this project",
                "logic": "POSITIVE",
                "notBefore": self.proj_start.strftime("%Y-%m-%d %H:%M:%S"),
                "notOnOrAfter": self.proj_end.strftime("%Y-%m-%d %H:%M:%S")
            }, "/time")

            logger.info("%s - Creating permissions", new_client_name)
            # Admin permission
            kc_client.create_permission({
                "name": f"{ds.id}-{ds.name} Administration Permission",
                "description": "List of policies that will allow certain users or roles to administrate the dataset",
                "type": "resource",
                "logic": "POSITIVE",
                "decisionStrategy": "AFFIRMATIVE",
                "policies": [pol["id"] for pol in policies],
                "resources": [resource["_id"]],
                "scopes": [scope["id"] for scope in created_scopes]
            })
            # User permission
            kc_client.create_permission({
                "name": f"{ds.id}-{ds.name} User {user["id"]} Permission",
                "description": "List of policies that will allow certain users or roles to administrate the dataset",
                "type": "resource",
                "logic": "POSITIVE",
                "decisionStrategy": "UNANIMOUS",
                "policies": [user_policy["id"], date_range_policy["id"]],
                "resources": [resource["_id"]],
                "scopes": [scope["id"] for scope in created_scopes]
            })

            logger.info("%s - Impersonation token", new_client_name)
            ret_response = {"token": kc_client.get_impersonation_token(user["id"])}

            logger.info("Updating DB")
            query = update(Request).\
                where(Request.id == self.id).\
                values(status=self.STATUSES["approved"], requested_by=user["id"])
            session.execute(query)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise DBError(f"Failed to approve request {self.id}") from exc
        except LogAndException as exc:
            self.delete(commit=True)
            raise exc

        return ret_response

    @classmethod
    def get_active_project(cls, proj_name:str, user_id:str):
        """
        Get the active project by namme and user
        """
        dar = cls.query.filter(
            cls.project_name == proj_name,
            cls.requested_by == user_id,
            cls.proj_start <= func.now(),
            cls.proj_end > func.now()
        ).one_or_none()
        if dar is None:
            raise DBError("User does not belong to a valid project")
        return dar
