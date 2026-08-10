import os
import logging
import base64
from pathlib import Path
from typing import cast

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx
from dagster_k8s import PipesK8sClient
from dagster._core.pipes.client import PipesClientCompletedInvocation
from kubernetes import client
from kubernetes.client import V1Secret
from kubernetes.config import load_incluster_config

from app.config import PipesSecurityContextConfig

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
        self.security_context = PipesSecurityContextConfig().to_pod_security_context()
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
        self._prepare_artifact_dir()
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

    def warn(self, message: str):
        self.context.log.warning(f"[{self.run_id}] - {message}")

    def _prepare_artifact_dir(self):
        """
        Create the per-run artifact directory from here, in the run pod, which mounts
        the volume root.

        This is what lets a non-root analytical image write its results on the storage
        backends where the mount root is root-owned 0755 - local, NFS, EFS. On Azure
        Files it is belt-and-braces: dir_mode=0777 means the task pod could create the
        directory itself whatever uid it runs as, so nothing here depends on privilege.

        Elsewhere it does depend on this pod being able to write the volume root, which
        today means running as root (the dagster image declares no USER). That is not
        guaranteed - k8sRunLauncher.securityContext can override it, and a restricted
        Pod Security Standard would force non-root - so a failure here is reported
        rather than swallowed: nothing else in the cluster can fix it, since the task
        pod is no more privileged than we are.

        Deliberately not a root initContainer on the task pod: that would require root
        in the pod running partner code, which a restricted Pod Security Standard
        rejects outright, and it would cost a container start on every run.
        """
        try:
            Path(self.artifact_path).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            try:
                st = os.stat(self.mnt_base_path)
                owner = f"owner {st.st_uid}:{st.st_gid} mode {oct(st.st_mode & 0o777)}"
            except OSError:
                owner = "could not stat mount root"
            self.warn(
                f"Could not pre-create {self.artifact_path} as "
                f"uid={os.geteuid()} gid={os.getegid()} ({exc}). "
                f"Mount root {self.mnt_base_path}: {owner}. "
                "The analytical container will have to create it itself, which will "
                "fail unless it runs as a uid that can write there. "
                "In which case the shared artifacts volume will need to be "
                "made writable by the analytical container manually."
            )
            return

        # The run dir must be writable, and the mount root must be traversable, for the
        # task pod to reach it. Both are no-ops on CIFS, which rejects chmod and already
        # mounts 0777.
        for path, mode in ((self.mnt_base_path, 0o755), (self.artifact_path, 0o777)):
            try:
                current = os.stat(path).st_mode & 0o777
                if current & mode != mode:
                    os.chmod(path, current | mode)
            except OSError:
                pass

    def _build_base_pod_spec(self):
        spec = {
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
        if self.security_context:
            spec["securityContext"] = self.security_context
        return spec

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
