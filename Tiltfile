# Tilt configuration for federated_node development
# Manages image builds and live reloads for:
# - Webserver (Flask backend)
# - Dagster user code
# - Dagster daemon and webserver

#
# Prerequisites:
# - Kind cluster running (make cluster up)
# - Helm deployed (make deploy)
# Then: tilt up

load('ext://restart_process', 'docker_build_with_restart')
load('ext://dotenv', 'dotenv')

# Load environment config from .dev.env
dotenv('.dev.env')

DOCKER_REGISTRY = 'localhost:5001'
NAMESPACE = os.getenv('NAMESPACE', 'fn')
RELEASE_NAME = os.getenv('RELEASE_NAME', 'fn-dev')
DAGSTER_DEPLOYMENT = RELEASE_NAME + '-dagster-user-deployments-dagster-fn'

# Full entrypoint from dev.values.yaml dagsterApiGrpcArgs
DAGSTER_FULL_ENTRYPOINT = [
  'dagster', 'api', 'grpc',
]

# Allow Tilt to control what K8s cluster to deploy to
allow_k8s_contexts('kind-fn')

# K8s resources are managed by Helm via `make deploy`. Tilt needs to know about
# them to inject the restart wrapper.
k8s_yaml(local(
  'python3 scripts/tilt_manifests.py {ns} backend {dagster}'.format(
    ns=NAMESPACE,
    dagster=DAGSTER_DEPLOYMENT,
  ),
  quiet=True,
))

# ==============================================================================
# WEBSERVER BACKEND
# ==============================================================================
# Image ref has NO tag: Tilt assigns its own tag and injects it into the
# deployment, matching by the tag-stripped name.
docker_build_with_restart(
  '{}/webserver-fn'.format(DOCKER_REGISTRY),
  'webserver',
  entrypoint=[
    'python', '-m', 'flask', 'run',
    '--host=0.0.0.0', '--port=5000',
  ],
  only=[
    'app',
    'requirements.txt',
    'setup.py',
    'alembic.ini',
    'migrations',
  ],
  live_update=[
    # Dependency / packaging changes => full rebuild
    fall_back_on([
      'webserver/requirements.txt',
      'webserver/setup.py',
      'webserver/alembic.ini',
      'webserver/migrations',
    ]),
    # Python code changes => sync into the running container
    sync('webserver/app', '/webserver/app'),
  ],
)

# ==============================================================================
# DAGSTER USER CODE DEPLOYMENT
# ==============================================================================
# Entrypoint combines Tilt's base command with Helm's args.
# tilt_manifests.py clears the Kubernetes args field so they don't get appended.
docker_build_with_restart(
  '{}/dagster-fn'.format(DOCKER_REGISTRY),
  'dagster',
  entrypoint=[],
  only=[
    'app',
    'requirements.txt',
    'setup.py',
    'pyproject.toml',
  ],
  live_update=[
    fall_back_on([
      'dagster/requirements.txt',
      'dagster/setup.py',
      'dagster/pyproject.toml',
    ]),
    sync('dagster/app', '/opt/dagster/home/app'),
  ],
)

# ==============================================================================
# STATUS HELPERS
# ==============================================================================

# Watch for dagster code changes, restart the pod, and reload workspace
local_resource(
  'dagster-reload',
  serve_cmd='bash -c \'while inotifywait -r -e modify dagster/app; do echo "Restarting dagster pod..."; kubectl rollout restart deployment/{} -n {}; kubectl rollout status deployment/{} -n {} --timeout=60s >/dev/null 2>&1; echo "Pod restarted, refresh the UI to see changes"; done\''.format(DAGSTER_DEPLOYMENT, NAMESPACE, DAGSTER_DEPLOYMENT, NAMESPACE),
  labels=['dev'],
)

# Expose the backend locally
k8s_resource('backend', port_forwards=['5000:5000'])

# Dagster webserver UI is deployed by Helm but not rebuilt by Tilt, so it has
# no k8s_resource() of its own to attach a port_forward to -- forward it
# directly via kubectl instead.
local_resource(
  'dagster-ui-port-forward',
  serve_cmd='kubectl port-forward svc/fn-dev-dagster-webserver -n {ns} 3000:80'.format(ns=NAMESPACE),
  labels=['infrastructure'],
)

local_resource(
  'deployment-check',
  cmd='kubectl get deployment backend -n {ns} >/dev/null 2>&1 && echo "OK: deployments ready" || echo "MISSING: run make deploy"'.format(ns=NAMESPACE),
  trigger_mode=TRIGGER_MODE_MANUAL,
  labels=['infrastructure'],
)

local_resource(
  'helm-status',
  cmd='helm status {rel} -n {ns} >/dev/null 2>&1 && echo "OK: helm release {rel} deployed" || echo "MISSING: run make deploy"'.format(rel=RELEASE_NAME, ns=NAMESPACE),
  trigger_mode=TRIGGER_MODE_MANUAL,
  labels=['infrastructure'],
)
