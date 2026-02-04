import os
import logging
from functools import cached_property

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx
from dagster_k8s import PipesK8sClient
from dagster._core.pipes.client import PipesClientCompletedInvocation

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dg.op(
    config_schema={
        "image": str,
    }
)
def k8s_pipes_op(context: OpExecCtx, k8s_pipes_client: PipesK8sClient) -> dg.Output:
    pipe = K8sPipeOP(client=k8s_pipes_client, context=context)
    return pipe().output


class K8sPipeOP:
    service_account_name = os.environ["DAGSTER_USER_SERVICE_ACCOUNT_NAME"]
    namespace = os.environ["DAGSTER_DEPLOYMENT_NAMESPACE"]
    pvc_name = os.environ["DAGSTER_ARTIFACTS_PVC_NAME"]
    mnt_base_path = os.environ["DAGSTER_ARTIFACT_MOUNT_PATH"]

    def __init__(self, client: PipesK8sClient, context: OpExecCtx):
        self.client = client
        self.context = context
        self.run_id = context.run_id
        self.config = context.op_config
        self.image = self.config['image']

    @property
    def env(self) -> dict:
        return {
            "RUN_ID": self.run_id,
            "ARTIFACT_PATH": self.artifact_path,
            "IMAGE": self.image,
        }

    @cached_property
    def artifact_path(self) -> str:
        image_string = self.image.replace("/", "_").replace(":", "_")
        return f"{self.mnt_base_path}/{image_string}/{self.run_id}"

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
            artifact_path=self.artifact_path,
            result=result,
        )

    def log(self, message: str):
        self.context.log.info(f"[PARENT][{self.run_id}] - {message}")
        logger.info(f"[PARENT][{self.run_id}] - {message}")

    def _load_base_pod_spec(self):
        return {
            "serviceAccountName": self.service_account_name,
            "volumes": [
                {
                    "name": self.pvc_name,
                    "persistentVolumeClaim": {"claimName": self.pvc_name},
                }
            ],
            "containers": [
                {
                    "name": "main",
                    "env": [
                        {"name": k, "value": v}
                        for k, v in self.env.items()
                    ],
                    "volumeMounts": [
                        {
                            "name": self.pvc_name,
                            "mountPath": self.mnt_base_path,
                        }
                    ],
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
