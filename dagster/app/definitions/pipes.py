import os
import logging
import base64
from typing import cast

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx
from dagster_k8s import PipesK8sClient
from dagster._core.pipes.client import PipesClientCompletedInvocation
from kubernetes import client
from kubernetes.client import V1Secret
from kubernetes.config import load_incluster_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dg.op(
    config_schema={
        "docker_image": dg.Field(str),
        "env": dg.Field(dict, default_value={}, is_required=False),
        "dataset_secret_name": dg.Field(str, is_required=False),
        "dataset_name": dg.Field(str, is_required=False),
        "dataset_host": dg.Field(str, is_required=False),
        "dataset_port": dg.Field(int, is_required=False),
        "dataset_type": dg.Field(str, is_required=False),
        "dataset_schema": dg.Field(str, is_required=False),
        "dataset_schema_write": dg.Field(str, is_required=False),
    }
)
def k8s_pipes_op(context: OpExecCtx, k8s_pipes_client: PipesK8sClient) -> dg.Output:
    pipe = K8sPipe(client=k8s_pipes_client, context=context)
    return pipe().output


class K8sPipe:
    def __init__(self, client: PipesK8sClient, context: OpExecCtx, ext_env=None):
        self.client = client
        self.context = context
        self.run_id = context.run_id
        self.config = context.op_config
        self.service_account_name = os.environ["DAGSTER_USER_SERVICE_ACCOUNT_NAME"]
        self.namespace = os.environ["DAGSTER_DEPLOYMENT_NAMESPACE"]
        self.pvc_name = os.environ["DAGSTER_ARTIFACTS_PVC_NAME"]
        self.mnt_base_path = os.environ["DAGSTER_ARTIFACT_MOUNT_PATH"]
        self.image = self.config['docker_image']
        self.name = f"pipes-{self.run_id}"
        self.artifact_path = f"{self.mnt_base_path}/{self.run_id}"
        self.dataset = self._setup_dataset()
        self.env = self._setup_env(ext_env)

    def _setup_dataset(self):
        if not self.config.get('dataset_name'):
            return {}

        keys = ['secret_name', 'name', 'host', 'port', 'type', 'schema', 'schema_write']
        dataset = {k: self.config.get(f'dataset_{k}') for k in keys}

        if not all(dataset.values()):
            raise ValueError("Incomplete dataset configuration provided.")
        return dataset

    def _setup_env(self, ext_env=None):
        env = {
            **(self.config.get('env') or {}),
            **(ext_env or {}),
            'ARTIFACT_PATH': self.artifact_path,
        }
        if self.dataset:
            env['CDM_SCHEMA'] = self.dataset['schema']
            env['WRITE_SCHEMA'] = self.dataset['schema_write']
        return env

    def __call__(self):
        self.log(f"Pipes op starting - {self.image}")
        self.log(f"ARIFACT_PATH: {self.artifact_path}")
        result = self.client.run(
            base_pod_spec=self._build_base_pod_spec(),
            namespace=self.namespace,
            context=self.context,
            image=self.image,
        )

        self.log("Pipes op completed")

        return K8sPipesResponse(
            run_id=self.run_id,
            image=self.image,
            result=result,
            artifact_path=self.artifact_path,
        )

    def log(self, message: str):
        self.context.log.info(f"[{self.run_id}] - {message}")

    def _build_base_pod_spec(self):
        return {
            "serviceAccountName": self.service_account_name,
            "volumes": self._pod_volumes(),
            "containers": [
                {
                    "name": self.name,
                    "env": self._pod_env(),
                    "volumeMounts": self._pod_volume_mounts(),
                }
            ],
        }

    def _pod_volumes(self):
        return [
            {
                "name": self.pvc_name,
                "persistentVolumeClaim": {"claimName": self.pvc_name},
            }
        ]

    def _pod_env(self):
        env = _dict_to_pod_env(self.env)
        if self.dataset:
            creds = self._get_dataset_creds()
            connstr = self._get_conn_str(**creds)
            env.append({"name": "CONNECTION_STRING", "value": connstr})
        return env

    def _pod_volume_mounts(self):
        return [
            {
                "name": self.pvc_name,
                "mountPath": self.mnt_base_path,
            }
        ]

    def _get_conn_str(self, username, password):
        return (
            f"server={self.dataset['host']};database={self.dataset['name']};"
            f"port={self.dataset['port']};uid={username};pwd={password};"
        )

    def _get_dataset_creds(self):
        username = self._get_k8s_dataset_secret("USERNAME")
        password = self._get_k8s_dataset_secret("PASSWORD")
        return {'username': username, 'password': password}

    def _get_k8s_dataset_secret(self, key: str) -> str:
        return _get_k8s_secret(self.dataset['secret_name'], self.namespace, key)


class K8sPipesResponse:
    def __init__(
        self,
        run_id: str,
        image: str,
        artifact_path: str,
        result: PipesClientCompletedInvocation,
    ):
        self.run_id = run_id
        self.result = result
        self.output = dg.Output(
            value={"artifacts_path": artifact_path},
            metadata={
                "run_id": run_id,
                "image": image,
                "artifacts_path": artifact_path,
            },
        )


def _get_k8s_secret(secret_name: str, namespace: str, key: str) -> str:
    load_incluster_config()
    v1 = client.CoreV1Api()
    secret = cast(V1Secret, v1.read_namespaced_secret(secret_name, namespace))
    if secret.data is None:
        raise ValueError(f"Secret {secret_name} has no data")
    return base64.b64decode(secret.data[key].encode()).decode()


def _dict_to_pod_env(env: dict):
    return [{"name": str(k).upper(), "value": str(v)} for k, v in env.items()]


RESOURCES = {
    "k8s_pipes_client": PipesK8sClient(poll_interval=1.0),
}
