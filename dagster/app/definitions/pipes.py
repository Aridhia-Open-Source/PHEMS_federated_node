import os
import uuid
import logging

import dagster as dg
from dagster_k8s import PipesK8sClient
from dagster._core.pipes.client import PipesClientCompletedInvocation

from app.resources.minio import MinioManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
minio = MinioManager()


NAMESPACE = os.environ['DAGSTER_DEPLOYMENT_NAMESPACE']
PVC_NAME = os.environ['DAGSTER_ARTIFACTS_PVC_NAME']
SERVICE_ACCOUNT_NAME = os.environ['DAGSTER_USER_SERVICE_ACCOUNT_NAME']
S3_BASE_PATH = f"s3://{os.environ['DAGSTER_MINIO_BUCKET']}/artifacts"
MNT_BASE_PATH = os.environ['DAGSTER_ARTIFACT_MOUNT_PATH']
JULIA_MODEL_DOCKER_IMAGE = os.environ['DAGSTER_PIPES_JULIA_IMAGE']


@dg.asset
def k8s_pipes_asset(context: dg.AssetExecutionContext, k8s_pipes_client: PipesK8sClient):
    task = K8sPipeAsset(k8s_pipes_client, context)
    run = task(image=JULIA_MODEL_DOCKER_IMAGE)
    return run.output


class K8sPipeAsset:
    def __init__(
            self,
            client: PipesK8sClient,
            context: dg.AssetExecutionContext,
    ):
        self.client = client
        self.context = context

    def __call__(self, image, **kwargs) -> 'K8sPipesResponse':
        return self._run_task(image, **kwargs)

    def _run_task(self, image, env=None, **kwargs) -> 'K8sPipesResponse':
        task_id = str(uuid.uuid4())
        env = {**(env or {}), 'TASK_ID': task_id}

        self._log(task_id, "Task Starting")
        result = self.client.run(
            base_pod_spec=self._load_base_pod_spec(),
            namespace=NAMESPACE,
            context=self.context,
            image=image,
            env=env,
            **kwargs
        )
        self._log(task_id, "Task Completed")

        response = K8sPipesResponse(task_id, image, result)
        self._upload_result(response)
        return response

    def _upload_result(self, response: 'K8sPipesResponse'):
        source_dir = f"{MNT_BASE_PATH}/{response.task_id}"
        target_prefix = f"artifacts/{response.task_id}"
        minio.upload_dir(source_dir=source_dir, target_prefix=target_prefix)
        self._log(response.task_id, f"Uploaded {source_dir} to {target_prefix}")

    def _log(self, task_id: str, message: str):
        self.context.log.info(f"[PARENT][DAGSTER][INFO][{task_id}] - {message}")
        logger.info(f"[PARENT][PYTHON][INFO][{task_id}] - {message}")
        logger.error(f"[PARENT][PYTHON][ERROR][{task_id}] - {message}")

    def _load_base_pod_spec(self):
        return {
            "nodeSelector": {
                "kubernetes.io/hostname": "fn-control-plane",
            },
            "volumes": [
                {
                    "name": PVC_NAME,
                    "persistentVolumeClaim": {
                        "claimName": PVC_NAME
                    },
                }
            ],
            "containers": [
                {
                    "name": "main",  # dagster convention
                    "volumeMounts": [
                        {
                            "name": PVC_NAME,
                            "mountPath": MNT_BASE_PATH,
                        }
                    ],
                }
            ],
            "serviceAccountName": SERVICE_ACCOUNT_NAME,
        }


class K8sPipesResponse:
    output: dg.Output

    def __init__(self, task_id, image, result: PipesClientCompletedInvocation):
        self.task_id = task_id
        self.result = result
        self.output = dg.Output(
            metadata={'task_id': task_id, 'image': image},
            value={'artifacts': f"{S3_BASE_PATH}/{task_id}"},
        )
