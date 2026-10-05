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
# The code server is part of the Federated Node chart (templates/dagster-code-server.yaml),
# so it is <release>-<fnDagster.codeServer.name>, not the dagster subchart's
# <release>-dagster-user-deployments-dagster-<name>.
DAGSTER_LOCATION = os.getenv('DAGSTER_USER_DEPLOYMENT', 'dagster-fn')
DAGSTER_DEPLOYMENT = RELEASE_NAME + '-' + DAGSTER_LOCATION

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
    'alembic.ini',
    'migrations',
  ],
  live_update=[
    # Dependency / packaging changes => full rebuild
    fall_back_on([
      'webserver/requirements.txt',
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
# The image has no ENTRYPOINT or CMD: the chart passes the gRPC command as the container
# args (templates/dagster-code-server.yaml), which tilt_manifests.py clears so they don't
# get appended to the restart wrapper. The command is therefore set here, and must match
# the chart's (fnDagster.codeServer.port and .module, 3030 and app.definitions by default).
docker_build_with_restart(
  '{}/dagster-fn'.format(DOCKER_REGISTRY),
  'dagster',
  entrypoint=[
    'dagster', 'api', 'grpc',
    '-h', '0.0.0.0', '-p', '3030', '-m', 'app.definitions',
  ],
  only=[
    'app',
    'requirements.txt',
    'pyproject.toml',
    'dagster.yaml',
    'workspace.yaml',
  ],
  live_update=[
    fall_back_on([
      'dagster/requirements.txt',
      'dagster/pyproject.toml',
      'dagster/dagster.yaml',
      'dagster/workspace.yaml',
    ]),
    sync('dagster/app', '/opt/dagster/home/app'),
  ],
)

# ==============================================================================
# STATUS HELPERS
# ==============================================================================

# Watch for dagster code changes, restart the pod, then reload the code location
# via the Dagster GraphQL API so the UI updates immediately.
local_resource(
  'dagster-reload',
  serve_cmd='bash tilt/scripts/dagster_reload.sh {location}'.format(
    location=DAGSTER_LOCATION,
  ),
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
  'db-internal-port-forward',
  serve_cmd='kubectl port-forward svc/db -n {ns} 5432:5432'.format(ns=NAMESPACE),
  labels=['infrastructure'],
)

local_resource(
  'gitea-port-forward',
  serve_cmd='kubectl port-forward svc/gitea -n {ns} 4000:3000'.format(ns=NAMESPACE),
  labels=['infrastructure'],
)

local_resource(
  'db-datasets-port-forward',
  serve_cmd='kubectl port-forward svc/db-datasets -n {ns} 5433:5432'.format(ns=NAMESPACE),
  labels=['infrastructure'],
)

local_resource(
  'keycloak-port-forward',
  serve_cmd='kubectl port-forward svc/keycloak -n keycloak 8080:80',
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
