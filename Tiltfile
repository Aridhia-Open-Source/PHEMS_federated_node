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

def get_helm_entrypoint(deployment_name):
  # Try command field first, then args field
  cmd = str(local(
    'kubectl get deployment %s -n %s -o jsonpath="{.spec.template.spec.containers[0].command[*]}" 2>/dev/null || echo ""' % (deployment_name, NAMESPACE),
    quiet=True
  )).strip()
  if cmd:
    return cmd.split()

  args = str(local(
    'kubectl get deployment %s -n %s -o jsonpath="{.spec.template.spec.containers[0].args[*]}" 2>/dev/null || echo ""' % (deployment_name, NAMESPACE),
    quiet=True
  )).strip()
  if args:
    return args.split()

  return None

DAGSTER_ENTRYPOINT = get_helm_entrypoint(DAGSTER_DEPLOYMENT)

# Allow Tilt to control what K8s cluster to deploy to
allow_k8s_contexts('kind-fn')

# K8s resources are managed by Helm via `make deploy`. Tilt needs to know about
# them to inject the restart wrapper.
k8s_yaml(local(
  'python3 scripts/tilt_manifests.py {ns} backend {dagster}'.format(
    ns=NAMESPACE, dagster=DAGSTER_DEPLOYMENT,
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
    'waitress-serve',
    '--host=0.0.0.0',
    '--port=5000',
    '--call',
    'app:create_app',
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
# The gRPC code server loads user code at process start, so a code change must
# restart the process to be picked up. docker_build_with_restart re-runs the
# entrypoint after syncing, giving fast reloads without a full image rebuild.
docker_build_with_restart(
  '{}/dagster-fn'.format(DOCKER_REGISTRY),
  'dagster',
  entrypoint=DAGSTER_ENTRYPOINT if DAGSTER_ENTRYPOINT else [
    'dagster', 'api', 'grpc',
    '-h', '0.0.0.0',
    '-p', '3030',
  ],
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
