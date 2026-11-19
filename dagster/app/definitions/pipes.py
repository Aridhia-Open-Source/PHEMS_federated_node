import os
import logging
from pathlib import Path

from dagster_k8s import PipesK8sClient
import dagster as dg
from dagster import OpExecutionContext as OpExecCtx
from dagster._core.pipes.client import PipesClientCompletedInvocation

from app.backend import BackendAPI
from app.config import PipesSecurityContextConfig
from app.models import TaskResources

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Analytical containers flushing results to the shared volume need longer than the
# 30s default to exit before SIGKILL.
TERMINATION_GRACE_PERIOD_SECONDS = 300

# What the pod, the Secret and the ConfigMap of a run are labelled with, so nexus-api finds the Secret and the
# ConfigMap to delete when the task ends (RUN_LABEL and TASK_LABEL in nexus/api/app/helpers/task_resources.py).
RUN_LABEL = "fn/run_id"
TASK_LABEL = "fn/task_id"

# A task's config, when its spec has one, is a single read-only file in the task pod, from a ConfigMap that
# nexus-api makes for the run and deletes when the task ends. The file is the ConfigMap's one key (CONFIG_FILE_NAME
# in nexus/api/app/helpers/task_resources.py).
CONFIG_FILE_NAME = "config.json"
CONFIG_FILE_PATH = f"/etc/task/{CONFIG_FILE_NAME}"
CONFIG_VOLUME_NAME = "task-config"

# ODBC driver per dataset type, as the legacy node's connection_string helper (and the task
# images, e.g. ghcr.io/aridhia-open-source/r-base) name them.
ODBC_DRIVERS = {
    "mssql": "ODBC Driver 18 for SQL Server",
    "postgres": "PostgreSQL ANSI",
    "mysql": "MySQL ODBC 9.3 ANSI Driver",
    "mariadb": "MariaDB ODBC 3.2 Driver",
}


@dg.op(
    config_schema={
        "docker_image": dg.Field(str),
        "env": dg.Field(dict, default_value={}, is_required=False),
        "compute": dg.Field(dict, default_value={}, is_required=False),
        "config": dg.Field(dict, is_required=False),
        "image_pull_secret": dg.Field(str, is_required=False),
        "dataset": dg.Field(
            dg.Shape(
                {
                    "name": str,
                    "host": str,
                    "port": int,
                    "type": str,
                    "read_schema": dg.Noneable(str),
                    "write_schema": dg.Noneable(str),
                }
            ),
            is_required=False,
        ),
    },
    required_resource_keys={"k8s_pipes_client", "backend_api"},
)
def k8s_pipes_op(context: OpExecCtx) -> dg.Output:
    pipe = K8sPipe(client=context.resources.k8s_pipes_client, backend_api=context.resources.backend_api, context=context)
    return pipe().output


class K8sPipe:
    def __init__(self, client: PipesK8sClient, backend_api: BackendAPI, context: OpExecCtx, ext_env=None):
        self.client = client
        self.backend_api = backend_api
        self.context = context
        self.run_id = context.run_id
        self.task_id = context.dagster_run.tags['fn/task_id']
        self.project_id = int(context.dagster_run.tags['fn/project_id'])
        self.config = context.op_config
        self.namespace = os.environ["DAGSTER_DEPLOYMENT_NAMESPACE"]
        # Task pods run apart from the release namespace, which holds the backend,
        # Keycloak and the Dagster infrastructure.
        self.task_namespace = os.environ.get("DAGSTER_TASK_NAMESPACE") or self.namespace
        self.pvc_name = os.environ["DAGSTER_ARTIFACTS_PVC_NAME"]
        self.mnt_base_path = os.environ["DAGSTER_ARTIFACT_MOUNT_PATH"]
        self.active_deadline_seconds = int(os.environ["DAGSTER_TASK_ACTIVE_DEADLINE_SECONDS"])
        self.image = self.config['docker_image']
        self.image_pull_secret = self.config.get('image_pull_secret')
        self.task_config = self.config.get('config')
        self.name = f"pipes-{self.run_id}"
        self.artifact_path = f"{self.mnt_base_path}/{self.run_id}"
        self.security_context = PipesSecurityContextConfig().to_pod_security_context()
        self.container_security_context = PipesSecurityContextConfig().to_container_security_context()
        self.dataset = self._setup_dataset()
        self.env = self._setup_env(ext_env)
        self.compute = self.config.get('compute')

    def _setup_dataset(self):
        dataset = self.config.get('dataset')
        if not dataset:
            return {}

        required = {k: v for k, v in dataset.items() if k not in ("read_schema", "write_schema")}
        if not all(required.values()):
            raise ValueError("Incomplete dataset configuration provided.")
        return dataset

    def _setup_env(self, ext_env=None):
        env = {
            **(self.config.get('env') or {}),
            **(ext_env or {}),
            'ARTIFACT_PATH': self.artifact_path,
        }
        if self.task_config is not None:
            env['CONFIG_PATH'] = CONFIG_FILE_PATH
        if self.dataset:
            if self.dataset['read_schema']:
                env['CDM_SCHEMA'] = self.dataset['read_schema']
            if self.dataset['write_schema']:
                env['WRITE_SCHEMA'] = self.dataset['write_schema']
        return env

    def __call__(self):
        self.log(f"Pipes op starting - {self.image}")
        self.log(f"ARIFACT_PATH: {self.artifact_path}")
        self._prepare_artifact_dir()
        # nexus-api makes the run's Secret and ConfigMap, labelled with the run, and deletes them when the task ends.
        # The pod only names them.
        resources = self.backend_api.create_task_resources(self.project_id, self.task_id, self.run_id)
        base_pod_spec = self._build_base_pod_spec(resources)
        result = self.client.run(
            base_pod_spec=base_pod_spec,
            # The name is not ours to set: PipesK8sClient overrides the one in base_pod_meta
            base_pod_meta={"labels": {RUN_LABEL: self.run_id, TASK_LABEL: self.task_id}},
            namespace=self.task_namespace,
            context=self.context,
            image=self.image,
            # The pod is killed at its deadline, and Kubernetes then takes up to the grace period to stop it
            pod_wait_timeout=self.active_deadline_seconds + TERMINATION_GRACE_PERIOD_SECONDS,
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
        Pod Security Standard would force non-root - so a failure here is raised rather
        than swallowed: nothing else in the cluster can fix it, since the task pod only
        mounts this folder, and the kubelet would create a missing one root-owned.

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
            raise RuntimeError(
                f"Could not create {self.artifact_path} as "
                f"uid={os.geteuid()} gid={os.getegid()} ({exc}). "
                f"Mount root {self.mnt_base_path}: {owner}. "
                "The shared artifacts volume needs to be made writable by this pod."
            ) from exc

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

    def _build_base_pod_spec(self, resources: TaskResources):
        # No service account: the task pod runs partner code and never talks to the
        # Kubernetes API, so it gets no token and no identity to borrow.
        spec = {
            "automountServiceAccountToken": False,
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": TERMINATION_GRACE_PERIOD_SECONDS,
            # Kubernetes kills a pod past this, which is what ends a hung task: the Pipes client
            # follows the pod's logs until the container exits, so its own timeout cannot.
            "activeDeadlineSeconds": self.active_deadline_seconds,
            "volumes": self._pod_volumes(resources),
            "containers": [
                {
                    "name": self.name,
                    "imagePullPolicy": "Always",
                    "securityContext": self.container_security_context,
                    "env": self._pod_env(resources),
                    "volumeMounts": self._pod_volume_mounts(),
                }
            ],
        }
        if self.compute:
            spec["containers"][0]["resources"] = self.compute
        if self.image_pull_secret:
            spec["imagePullSecrets"] = [{"name": self.image_pull_secret}]
        if self.security_context:
            spec["securityContext"] = self.security_context
        return spec

    def _pod_volumes(self, resources: TaskResources):
        volumes = [
            {
                "name": self.pvc_name,
                "persistentVolumeClaim": {"claimName": self.pvc_name},
            }
        ]
        if self.task_config is not None:
            volumes.append({"name": CONFIG_VOLUME_NAME, "configMap": {"name": resources.config_map}})
        return volumes

    def _pod_env(self, resources: TaskResources):
        env = _dict_to_pod_env(self.env)
        if self.dataset:
            # The kubelet expands $(NAME) from the variables defined above it in the list.
            env += [
                self._secret_env("DB_USERNAME", resources.secret, "USERNAME"),
                self._secret_env("DB_PASSWORD", resources.secret, "PASSWORD"),
                {"name": "CONNECTION_STRING", "value": self._get_conn_str("$(DB_USERNAME)", "$(DB_PASSWORD)")},
            ]
        return env

    def _secret_env(self, name: str, secret_name: str | None, key: str):
        return {"name": name, "valueFrom": {"secretKeyRef": {"name": secret_name, "key": key}}}

    def _pod_volume_mounts(self):
        # Only this run's folder, not the volume: a task must not reach other runs' results
        mounts = [
            {
                "name": self.pvc_name,
                "mountPath": self.artifact_path,
                "subPath": self.run_id,
            }
        ]
        if self.task_config is not None:
            mounts.append(
                {"name": CONFIG_VOLUME_NAME, "mountPath": CONFIG_FILE_PATH, "subPath": CONFIG_FILE_NAME, "readOnly": True}
            )
        return mounts

    def _get_conn_str(self, username, password):
        """A full ODBC connection string for the dataset's type, as the legacy node built it."""
        host, port, name = self.dataset['host'], self.dataset['port'], self.dataset['name']
        if self.dataset['type'] == "oracle":
            return f"driver={{Oracle ODBC Driver}};Uid={username};PSW={password};DBQ={host}:{port}/{name};"
        driver = ODBC_DRIVERS[self.dataset['type']]
        return f"driver={{{driver}}};Uid={username};Pwd={password};Server={host},{port};Database={name};"


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


def _dict_to_pod_env(env: dict):
    return [{"name": str(k).upper(), "value": str(v)} for k, v in env.items()]


RESOURCES = {
    "k8s_pipes_client": PipesK8sClient(poll_interval=1.0),
}
