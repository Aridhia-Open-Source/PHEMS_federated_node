import logging
import re
import requests
from sqlalchemy import Column, Integer, String
from kubernetes.client.exceptions import ApiException
from kubernetes.client import V1ConfigMap, V1Secret

from app.helpers.base_model import BaseModel, db
from app.helpers.connection_string import Mssql, Postgres, Mysql, Oracle, MariaDB
from app.helpers.const import DEFAULT_NAMESPACE, TASK_NAMESPACE, PUBLIC_URL
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest, DatasetError
from app.helpers.keycloak import Keycloak
from app.helpers.kubernetes import KubernetesClient

logger = logging.getLogger("dataset_model")
logger.setLevel(logging.INFO)


SUPPORTED_AUTHS = [
    "standard",
    "kerberos"
]
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
    schema = Column(String(256), nullable=True)
    type = Column(String(256), server_default="postgres", nullable=False)
    auth_type = Column(String(256), server_default="standard", nullable=False)
    extra_connection_args = Column(String(4096), nullable=True)

    def __init__(self,
                 name:str,
                 host:str,
                 username:str="",
                 password:str="",
                 port:int=5432,
                 schema:str=None,
                 type:str="postgres",
                 auth_type:str="standard",
                 kerberos_secret:str=None,
                 extra_connection_args:str=None,
                 **kwargs
            ):
        self.name = requests.utils.unquote(name).lower()
        self.slug = self.slugify_name()
        self.url = f"https://{PUBLIC_URL}/datasets/{self.slug}"
        self.host = host
        self.port = port
        self.schema = schema
        self.type = type
        self.username = username
        self.password = password
        self.extra_connection_args = extra_connection_args
        self.auth_type = auth_type.lower()
        self.kerberos_secret = kerberos_secret

    @classmethod
    def validate(cls, data):
        data = super().validate(data)
        auth_type = data.get("auth_type", "standard").lower()

        if auth_type not in SUPPORTED_AUTHS:
            raise InvalidRequest(f"{auth_type} is not supported. Try one of {SUPPORTED_AUTHS}")

        if data.get("type", "postgres").lower() not in SUPPORTED_ENGINES:
            raise InvalidRequest(f"DB type {data["type"]} is not supported.")

        if not data.get("username"):
            raise InvalidRequest("`username` field is mandatory")

        if auth_type == "standard" and not data.get("password"):
            raise InvalidRequest("With standard auth_type, username and password must be provided")

        if auth_type == "kerberos" and not data.get("kerberos", {}).get("secret_name"):
            raise InvalidRequest(
                "With kerberos auth_type, a secret containing krb5.conf and principal.keytab keys is needed"
            )

        if auth_type == "kerberos":
            v1 = KubernetesClient()
            try:
                data["kerberos_secret"] = v1.read_namespaced_secret(
                    name=data["kerberos"]["secret_name"],
                    namespace=DEFAULT_NAMESPACE
                )
                if "krb5.conf" not in data["kerberos_secret"].data:
                    raise InvalidRequest("Secret doesn't have `krb5.conf` as a data field")

                if "principal.keytab" not in data["kerberos_secret"].data:
                    raise InvalidRequest("Secret doesn't have `principal.keytab` as a data field")

            except ApiException as apie:
                if apie.status == 404:
                    raise InvalidRequest(
                        f"Secret {data["kerberos"]["secret_name"]} not found in the {DEFAULT_NAMESPACE} namespace"
                    ) from apie

        return data

    def get_kerberos_secret_name(self) -> str:
        """
        Instead of returning the whole object, return it's name only
        """
        v1 = KubernetesClient()
        try:
            secret = v1.list_namespaced_secret(
                namespace=DEFAULT_NAMESPACE,
                label_selector=f"fn_dataset={self.name},fn_dataset_host={self.host}"
            )
        except ApiException as apie:
            logging.error(apie.body)
            raise DatasetError("An error occurred while fetching the kerberos secret") from apie

        return secret.items[0].metadata.name if len(secret.items) else None


    def get_kerberos_secret(self, namespace=DEFAULT_NAMESPACE) -> V1Secret:
        """
        Retrieve the secret with the db connection
        config files in it.
        """
        v1 = KubernetesClient()
        try:
            secret = v1.list_namespaced_secret(
                namespace=namespace,
                label_selector=f"fn_dataset={self.name},fn_dataset_host={self.host}"
            )
        except ApiException as apie:
            logging.error(apie.body)
            raise DatasetError("An error occurred while fetching the kerberos secret") from apie

        return secret.items[0] if len(secret.items) else None

    def get_cm_name(self) -> str:
        """
        Retrieve the configmap with the db connection
        config file in it and return the name
        """
        cm = self.get_connection_cm()
        return cm.metadata.name

    def label_new_kerberos_secret(self, secret:V1Secret=None):
        v1 = KubernetesClient()
        if secret is None:
            secret = self.kerberos_secret

        if secret.metadata.labels is None:
            secret.metadata.labels = {}

        secret.metadata.labels["fn_dataset"] = self.name
        secret.metadata.labels["fn_dataset_host"] = self.host
        try:
            v1.patch_namespaced_secret(
                name=secret.metadata.name,
                namespace=DEFAULT_NAMESPACE,
                body=secret
            )
            secret.metadata.namespace = TASK_NAMESPACE
            secret.metadata.creation_timestamp = None
            secret.metadata.resource_version = None

            v1.create_namespaced_secret(
                body=secret,
                namespace=TASK_NAMESPACE
            )
        except ApiException as apie:
            if apie.status != 409:
                raise DatasetError(f"Cannot re create the connection config map in the {TASK_NAMESPACE} namespace")

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

    def sanitized_dict(self):
        dataset = super().sanitized_dict()
        dataset.pop("kerberos_secret", None)
        dataset["slug"] = self.slugify_name()
        dataset["url"] = f"https://{PUBLIC_URL}/datasets/{dataset["slug"]}"
        return dataset

    def slugify_name(self) -> str:
        """
        Based on the provided name, it will return the slugified name
        so that it will be sade to save on the DB
        """
        return re.sub(r'[\W_]+', '-', self.name)

    def get_credentials(self) -> tuple:
        """
        Mostly used to create a direct connection to the DB, i.e. /beacon endpoint
        This is not involved in the Task Execution Service
        """
        v1 = KubernetesClient()
        secret = v1.read_namespaced_secret(self.get_creds_secret_name(), DEFAULT_NAMESPACE, pretty='pretty')
        # Doesn't matter which key it's being picked up, the value it's the same
        # in terms of *USER or *PASSWORD
        user = KubernetesClient.decode_secret_value(secret.data['PGUSER'])
        password = KubernetesClient.decode_secret_value(secret.data['PGPASSWORD'])

        return user, password

    def add(self, commit=True, user_id=None):
        super().add(commit)

        v1 = KubernetesClient()
        if self.needs_secret:
            # create secrets
            v1.create_secret(
                name=self.get_creds_secret_name(),
                values={
                    "PGPASSWORD": self.password,
                    "PGUSER": self.username,
                    "MSSQL_PASSWORD": self.password,
                    "MSSQL_USER": self.username
                },
                namespaces=[DEFAULT_NAMESPACE]
            )
            delattr(self, "username")
            delattr(self, "password")
        elif self.auth_type == "kerberos":
            # Add the username to the existing secret
            self.kerberos_secret.data["PGUSER"] = v1.encode_secret_value(self.username)
            # Label the secret
            self.label_new_kerberos_secret()
            delattr(self, "kerberos_secret")

        # Add to keycloak
        kc_client = Keycloak()
        admin_policy = kc_client.get_policy('admin-policy')
        sys_policy = kc_client.get_policy('system-policy')

        admin_ds_scope = []
        admin_ds_scope.append(kc_client.get_scope('can_admin_dataset'))
        admin_ds_scope.append(kc_client.get_scope('can_access_dataset'))
        admin_ds_scope.append(kc_client.get_scope('can_exec_task'))
        admin_ds_scope.append(kc_client.get_scope('can_admin_task'))
        admin_ds_scope.append(kc_client.get_scope('can_send_request'))
        admin_ds_scope.append(kc_client.get_scope('can_admin_request'))
        policy = kc_client.create_policy({
            "name": f"{self.id} - {self.name} Admin Policy",
            "description": f"List of users allowed to administrate the {self.name} dataset",
            "logic": "POSITIVE",
            "users": [user_id]
        }, "/user")

        resource_ds = kc_client.create_resource({
            "name": f"{self.id}-{self.name}",
            "displayName": f"{self.id} - {self.name}",
            "scopes": admin_ds_scope,
            "uris": []
        })
        kc_client.create_permission({
            "name": f"{self.id}-{self.name} Admin Permission",
            "description": "List of policies that will allow certain users or roles to administrate the dataset",
            "type": "resource",
            "logic": "POSITIVE",
            "decisionStrategy": "AFFIRMATIVE",
            "policies": [admin_policy["id"], sys_policy["id"], policy["id"]],
            "resources": [resource_ds["_id"]],
            "scopes": [scope["id"] for scope in admin_ds_scope]
        })

    def update(self, **kwargs):
        """
        Updates the instance with new values. These should be
        already validated.
        """
        # Nothing to validate, i.e updating the dictionaries only
        if not kwargs:
            return

        kc_client = Keycloak()
        v1 = KubernetesClient()
        new_username = kwargs.pop("username", None)

        # If the dataset to update has the configmap for connection
        if kwargs.get("auth_type", self.auth_type) == "kerberos":
            kerb_secret_name = kwargs.pop("kerberos", {}).get("secret_name")
            old_sec = self.get_kerberos_secret()
            if kerb_secret_name:
                try:
                    new_kerb_secret: V1Secret = v1.read_namespaced_secret(
                        name=kerb_secret_name,
                        namespace=DEFAULT_NAMESPACE
                    )
                except ApiException as apie:
                    logging.error(apie.body)
                    raise DatasetError(
                        f"An error occurred while fetching the new kerberos secret {kerb_secret_name}"
                    ) from apie

                # Checking for the right keys to be present
                if not ("krb5.conf" in new_kerb_secret.data and "principal.keytab" in new_kerb_secret.data):
                    raise InvalidRequest(
                        "Mandatory keys missing in the secret. Make sure krb5.conf and principal.keytab are there"
                    )

                if new_username:
                    new_kerb_secret.data["PGUSER"] = KubernetesClient.encode_secret_value(new_username)
                else:
                    new_kerb_secret.data["PGUSER"] = old_sec.data["PGUSER"]

                self.label_new_kerberos_secret(new_kerb_secret)

                if old_sec:
                    for ns in [DEFAULT_NAMESPACE, TASK_NAMESPACE]:
                        v1.delete_namespaced_secret(
                            name=old_sec.metadata.name,
                            namespace=ns
                        )
            elif new_username:
                for ns in [DEFAULT_NAMESPACE, TASK_NAMESPACE]:
                    old_sec = self.get_kerberos_secret(ns)
                    old_sec.data["PGUSER"] = KubernetesClient.encode_secret_value(new_username)
                    v1.patch_namespaced_secret(
                        body=old_sec,
                        name=old_sec.metadata.name,
                        namespace=ns
                    )

        elif self.needs_secret:
            # Get existing secret
            secret = v1.read_namespaced_secret(self.get_creds_secret_name(), DEFAULT_NAMESPACE, pretty='pretty')
            secret_task = v1.read_namespaced_secret(self.get_creds_secret_name(), TASK_NAMESPACE, pretty='pretty')

            secret_task.data = secret.data

            new_name = kwargs.get("name", None)
            new_host = kwargs.get("host", None)
            new_pass = kwargs.pop("password", None)

            # Check secret names
            new_host = kwargs.get("host", None)
            try:
                for ns in [DEFAULT_NAMESPACE, TASK_NAMESPACE]:
                    # Create new secret if name is different
                    if (new_host != self.host and new_host) or (new_name != self.name and new_name):
                        secret.metadata = {'name': self.get_creds_secret_name(new_host, new_name)}
                        secret_task.metadata = secret.metadata
                        v1.create_namespaced_secret(ns, body=secret, pretty='true')
                        v1.delete_namespaced_secret(namespace=ns, name=self.get_creds_secret_name())
                    else:
                        v1.patch_namespaced_secret(namespace=ns, name=self.get_creds_secret_name(), body=secret)
            except ApiException as e:
                # Host and name are unique so there shouldn't be duplicates. If so
                # let the exception to be re-raised with the internal one
                raise InvalidRequest(e.reason)

            if new_username:
                secret.data["PGUSER"] = KubernetesClient.encode_secret_value(new_username)
            if new_pass:
                secret.data["DBPASSWORD"] = KubernetesClient.encode_secret_value(new_pass)
            # Check resource names on KC and update them
            if new_name and new_name != self.name:
                update_args = {
                    "name": f"{self.id}-{kwargs["name"]}",
                    "displayName": f"{self.id} - {kwargs["name"]}"
                }
                kc_client.patch_resource(f"{self.id}-{self.name}", **update_args)

        # Update table
        if kwargs:
            self.query.filter(Dataset.id == self.id).update(kwargs, synchronize_session='evaluate')
            db.session.commit()

    @classmethod
    def get_dataset_by_name_or_id(cls, id:int=None, name:str="") -> "Dataset":
        """
        Common funcion to get a dataset by name or id.
        If both arguments are provided, then tries to find as an AND condition
            rather than an OR.

        Returns:
         Datset:

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

    @property
    def needs_secret(self):
        return self.auth_type == "standard"

    def __repr__(self):
        return f'<Dataset {self.name}>'
