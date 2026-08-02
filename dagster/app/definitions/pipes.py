import os
import logging

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx
from dagster_k8s import PipesK8sClient
from dagster._core.pipes.client import PipesClientCompletedInvocation

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
    }
)
def k8s_pipes_op(context: OpExecCtx, k8s_pipes_client: PipesK8sClient) -> dg.Output:
    pipe = K8sPipe(client=k8s_pipes_client, context=context)
    return pipe().output


class K8sPipe:
    def __init__(self, client: PipesK8sClient, context: OpExecCtx, ext_env=None):
        self.service_account_name = os.environ["DAGSTER_USER_SERVICE_ACCOUNT_NAME"]
        self.namespace = os.environ["DAGSTER_DEPLOYMENT_NAMESPACE"]
        self.pvc_name = os.environ["DAGSTER_ARTIFACTS_PVC_NAME"]
        self.mnt_base_path = os.environ["DAGSTER_ARTIFACT_MOUNT_PATH"]
        self.client = client
        self.context = context
        self.run_id = context.run_id
        self.config = context.op_config
        self.image = self.config['docker_image']
        self.artifact_path = f"{self.mnt_base_path}/{self.run_id}"
        self.dataset_secret_name = self.config.get('dataset_secret_name')
        self.dataset_name = self.config.get('dataset_name')
        self.dataset_host = self.config.get('dataset_host')
        self.dataset_port = self.config.get('dataset_port')
        self.dataset_type = self.config.get('dataset_type')
        self.env = self._setup_env(ext_env)

    def _setup_env(self, ext_env=None):
        return {
            **(self.config.get('env') or {}),
            **(ext_env or {}),
            'ARTIFACT_PATH': self.artifact_path,
        }

    def __call__(self):
        self.log(f"Pipes op starting - {self.image}")

        result = self.client.run(
            base_pod_spec=self._load_base_pod_spec(),
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

    def _load_base_pod_spec(self):
        volumes = [
            {
                "name": self.pvc_name,
                "persistentVolumeClaim": {"claimName": self.pvc_name},
            }
        ]
        if self.dataset_secret_name:
            volumes.append({
                "name": "dataset-creds",
                "secret": {"secretName": self.dataset_secret_name},
            })

        volume_mounts = [
            {
                "name": self.pvc_name,
                "mountPath": self.mnt_base_path,
            }
        ]
        if self.dataset_secret_name:
            volume_mounts.append({
                "name": "dataset-creds",
                "mountPath": "/var/secrets/db",
            })

        return {
            "serviceAccountName": self.service_account_name,
            "volumes": volumes,
            "containers": [
                {
                    "name": "main",
                    "env": [
                        {"name": k, "value": str(v)}
                        for k, v in self.env.items()
                    ],
                    "volumeMounts": volume_mounts,
                }
            ],
        }


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


RESOURCES = {
    "k8s_pipes_client": PipesK8sClient(poll_interval=1.0),
}
