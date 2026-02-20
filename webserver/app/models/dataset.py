import logging
import re
from sqlalchemy import Column, Integer, String
from app.helpers.base_model import BaseModel, db
from app.helpers.const import DEFAULT_NAMESPACE, PUBLIC_URL
from app.helpers.exceptions import DBRecordNotFoundError
from app.helpers.kubernetes import KubernetesClient
from kubernetes.client import V1Secret

from app.helpers.connection_string import Mssql, Postgres, Mysql, Oracle, MariaDB

logger = logging.getLogger("dataset_model")
logger.setLevel(logging.INFO)

SUPPORTED_ENGINES = {
    "mssql": Mssql,
    "postgres": Postgres,
    "mysql": Mysql,
    "oracle": Oracle,
    "mariadb": MariaDB
}


class Dataset(db.Model, BaseModel):
    __tablename__ = 'datasets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), unique=True, nullable=False)
    host = Column(String(256), nullable=False)
    port = Column(Integer, default=5432)
    schema_read = Column(String(256), nullable=True)
    schema_write = Column(String(256), nullable=True)
    type = Column(String(256), server_default="postgres", nullable=False)
    extra_connection_args = Column(String(4096), nullable=True)
    repository = Column(String(4096), nullable=True)

    catalogue = db.relationship("Catalogue", back_populates="dataset", uselist=False, cascade="all, delete-orphan")
    dictionaries = db.relationship("Dictionary", back_populates="dataset", cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        self.username = kwargs.pop("username", None)
        self.password = kwargs.pop("password", None)
        super().__init__(**kwargs)

    @property
    def slug(self):
        return re.sub(r'[\W_]+', '-', self.name)

    @property
    def url(self) -> str:
        return f"https://{PUBLIC_URL}/datasets/{self.slug}"

    def get_creds_secret_name(self, host=None, name=None):
        host = host or self.host
        name = name or self.name

        cleaned_up_host = re.sub('http(s)*://', '', host)
        return f"{cleaned_up_host}-{re.sub('\\s|_|#', '-', name.lower())}-creds"

    def get_connection_string(self):
        """
        From the helper classes, return the correct connection string
        """
        un, passw = self.get_credentials()
        return SUPPORTED_ENGINES[self.type](
            user=un,
            passw=passw,
            host=self.host,
            port=self.port,
            database=self.name,
            args=self.extra_connection_args
        ).connection_str

    def get_credentials(self) -> tuple:
        """
        Mostly used to create a direct connection to the DB, i.e. /beacon endpoint
        This is not involved in the Task Execution Service
        """
        v1 = KubernetesClient()
        secret:V1Secret = v1.read_namespaced_secret(
            self.get_creds_secret_name(), DEFAULT_NAMESPACE, pretty='pretty'
        )
        # Doesn't matter which key it's being picked up, the value it's the same
        # in terms of *USER or *PASSWORD
        user = KubernetesClient.decode_secret_value(secret.data['PGUSER'])
        password = KubernetesClient.decode_secret_value(secret.data['PGPASSWORD'])

        return user, password

    @classmethod
    def get_dataset_by_name_or_id(cls, id:int=None, name:str="") -> "Dataset":
        """
        Common function to get a dataset by name or id.
        If both arguments are provided, then tries to find as an AND condition
            rather than an OR.

        Returns:
         Dataset:

        Raises:
            DBRecordNotFoundError: if no record is found
        """
        if id and name:
            error_msg = f"Dataset \"{name}\" with id {id} does not exist"
            dataset = cls.query.filter((Dataset.name.ilike(name or "") & (Dataset.id == id))).one_or_none()
        else:
            error_msg = f"Dataset {name if name else id} does not exist"
            dataset = cls.query.filter((Dataset.name.ilike(name or "") | (Dataset.id == id))).one_or_none()

        if not dataset:
            raise DBRecordNotFoundError(error_msg)

        return dataset

    def __repr__(self):
        return f'<Dataset {self.name}>'
