# Tilt configuration for federated_node development
# Manages image builds and live reloads for:
# - nexus-api
# - Dagster user code
# - Dagster daemon and webserver

#
# Prerequisites:
# - Kind cluster running (mise run cluster up)
# - Helm deployed (mise run deploy)
# Then: tilt up

load('ext://restart_process', 'custom_build_with_restart')
load('ext://dotenv', 'dotenv')

# Load environment config: .generated.env (scripts/configure.sh) first, so .dev.env wins
if os.path.exists('.generated.env'):
  dotenv('.generated.env')
dotenv('.dev.env')

DOCKER_REGISTRY = 'localhost:5001'

# CUSTOM_CA_FILE (optional): given to image builds as the BuildKit secret proxy_ca.
CA_FILE = os.getenv('CUSTOM_CA_FILE', '')
BUILD_SECRET = ['--secret', 'id=proxy_ca,src=' + os.path.abspath(CA_FILE)] if CA_FILE else []
NAMESPACE = os.getenv('NAMESPACE', 'fn')
RELEASE_NAME = os.getenv('RELEASE_NAME', 'fn-dev')
# The code server is part of the Federated Node chart (templates/dagster-code-server.yaml),
# so it is <release>-<fnDagster.codeServer.name>, not the dagster subchart's
# <release>-dagster-user-deployments-dagster-<name>.
DAGSTER_LOCATION = os.getenv('DAGSTER_USER_DEPLOYMENT', 'dagster-fn')
DAGSTER_DEPLOYMENT = RELEASE_NAME + '-' + DAGSTER_LOCATION

# What is reachable on localhost while Tilt is up. A section that sets up a port-forward adds
# one line next to it: DEV_URLS.append(('Name', 'http://localhost:PORT')). The dagster-reload
# resource at the end of this file prints the list and gives each entry a link in the Tilt UI.
DEV_URLS = []

# Allow Tilt to control what K8s cluster to deploy to
allow_k8s_contexts('kind-fn')

# K8s resources are managed by Helm via `mise run deploy`. Tilt needs to know about
# them to inject the restart wrapper.
k8s_yaml(local(
  'python3 scripts/tilt_manifests.py {ns} nexus-api {dagster} nexus-ui'.format(
    ns=NAMESPACE,
    dagster=DAGSTER_DEPLOYMENT,
  ),
  quiet=True,
))

# ==============================================================================
# NEXUS API (nexus/api)
# ==============================================================================
# Image ref has NO tag: Tilt assigns its own tag and injects it into the
# deployment, matching by the tag-stripped name. uvicorn --reload picks up synced code itself.
# The image also takes the shared fednode package (nexus/fednode) from the fednode named build context,
# which docker_build has none of, so it is a custom build, like Dagster's.
NEXUS_API_BUILD_CMD = ' '.join(
  ['docker buildx build --load --build-context fednode=nexus/fednode'] + BUILD_SECRET + ['-t {ref} nexus/api'])
custom_build_with_restart(
  '{}/nexus-api-fn'.format(DOCKER_REGISTRY),
  NEXUS_API_BUILD_CMD.format(ref='$EXPECTED_REF'),
  deps=[
    'nexus/api/app',
    'nexus/api/requirements.txt',
    'nexus/api/alembic.ini',
    'nexus/api/migrations',
    'nexus/api/Dockerfile',
    'nexus/api/.dockerignore',
    'nexus/fednode',
  ],
  entrypoint=[
    'uvicorn', '--factory', 'app:create_app', '--reload',
    '--reload-dir=/nexus', '--reload-dir=/opt/fednode',
    '--host=0.0.0.0', '--port=5000',
  ],
  ignore=[
    'nexus/fednode/tests',
    '**/.pytest_cache',
    '**/__pycache__',
    '**/*.pyc',
    '**/*.egg-info',
  ],
  live_update=[
    # Dependency / packaging changes => full rebuild
    fall_back_on([
      'nexus/api/requirements.txt',
      'nexus/api/alembic.ini',
      'nexus/api/migrations',
      'nexus/fednode/pyproject.toml',
    ]),
    # Python code changes => sync into the running container
    sync('nexus/api/app', '/nexus/app'),
    # The package is installed editable from here (nexus/api/Dockerfile)
    sync('nexus/fednode', '/opt/fednode'),
  ],
)

# ==============================================================================
# DAGSTER USER CODE DEPLOYMENT
# ==============================================================================
# What the code server and the run pods use from the Dagster image, plus the shared nexus-api
# client (nexus/fednode), which the image takes from the fednode named build context.
# Everything else under dagster/ (fncli, tests, docs, lint and CI files) is not used by either,
# so changing it rebuilds nothing. (The build still copies fncli and conftest.py, per
# dagster/.dockerignore.)
DAGSTER_IMAGE_FILES = [
  'app',
  'requirements.txt',
  'pyproject.toml',
  'dagster.yaml',
  'workspace.yaml',
]
DAGSTER_BUILD_DEPS = ['dagster/' + f for f in DAGSTER_IMAGE_FILES] + [
  'dagster/Dockerfile',
  'dagster/.dockerignore',
  'nexus/fednode',
]
# Test edits and pytest runs don't rebuild or restart the code server
DAGSTER_BUILD_IGNORE = [
  'dagster/app/tests',
  'nexus/fednode/tests',
  '**/.pytest_cache',
  '**/__pycache__',
  '**/*.pyc',
  '**/*.egg-info',
]
# docker_build has no named build context, so the Dagster image is a custom build
DAGSTER_BUILD_CMD = ' '.join(
  ['docker buildx build --load --build-context fednode=nexus/fednode'] + BUILD_SECRET + ['-t {ref} dagster'])

# The image has no ENTRYPOINT or CMD: the chart passes the whole gRPC command as the
# container args (templates/dagster-code-server.yaml). With an empty entrypoint Tilt's
# command is just the restart wrapper, and Kubernetes appends those args to it, so the
# wrapper runs the chart's own command. Don't set an entrypoint here and don't clear the
# args: either one doubles the command or leaves the wrapper with nothing to run.
custom_build_with_restart(
  '{}/dagster-fn'.format(DOCKER_REGISTRY),
  DAGSTER_BUILD_CMD.format(ref='$EXPECTED_REF'),
  deps=DAGSTER_BUILD_DEPS,
  entrypoint=[],
  ignore=DAGSTER_BUILD_IGNORE,
  live_update=[
    fall_back_on([
      'dagster/requirements.txt',
      'dagster/pyproject.toml',
      'dagster/dagster.yaml',
      'dagster/workspace.yaml',
      'nexus/fednode/pyproject.toml',
    ]),
    sync('dagster/app', '/opt/dagster/home/app'),
    # The client is installed editable from here (dagster/Dockerfile)
    sync('nexus/fednode', '/opt/dagster/nexus/fednode'),
  ],
)

# Run pods start from DAGSTER_CURRENT_IMAGE, not from the image Tilt live-updates, so
# rebuild and push that image (tag set in scripts/tilt_manifests.py) on every code change.
# Run pods always pull, so the next run picks it up.
local_resource(
  'dagster-run-image',
  cmd='{build} && docker push {img}'.format(
    build=DAGSTER_BUILD_CMD.format(ref='{}/dagster-fn:tilt-run'.format(DOCKER_REGISTRY)),
    img='{}/dagster-fn:tilt-run'.format(DOCKER_REGISTRY),
  ),
  # Only what the code server and run pods use. The docs, fncli, CI and lint files next to it don't.
  deps=DAGSTER_BUILD_DEPS,
  ignore=DAGSTER_BUILD_IGNORE,
  labels=['dev'],
)

# ==============================================================================
# NEXUS ADMIN UI
# ==============================================================================
# The chart runs the Vite dev server when nexus.ui.devServer is true (dev.values.yaml).
# Tilt builds that dev image and syncs nexus/ui into it; Vite hot-reloads the page.
docker_build(
  '{}/nexus-ui-dev-fn'.format(DOCKER_REGISTRY),
  'nexus/ui',
  target='dev',
  ignore=['node_modules', 'dist'],
  live_update=[
    fall_back_on(['nexus/ui/package.json', 'nexus/ui/package-lock.json']),
    sync('nexus/ui', '/app'),
  ],
)
k8s_resource('nexus-ui', port_forwards=['8088:5173'], labels=['dev'])
DEV_URLS.append(('nexus UI', 'http://localhost:8088/nexus-ui/'))

# ==============================================================================
# STATUS HELPERS
# ==============================================================================

# Expose nexus-api locally
k8s_resource('nexus-api', port_forwards=['5000:5000'])
DEV_URLS.append(('nexus-api docs', 'http://localhost:5000/docs'))

# kubectl port-forward exits when one of its connections breaks, and Tilt does not start
# a serve_cmd again once it has exited. Loop, so a dead forward comes back after a second.
def port_forward_cmd(service, namespace, ports):
  return 'while true; do kubectl port-forward svc/{service} -n {namespace} {ports}; sleep 1; done'.format(
    service=service, namespace=namespace, ports=ports,
  )

# Dagster webserver UI is deployed by Helm but not rebuilt by Tilt, so it has
# no k8s_resource() of its own to attach a port_forward to -- forward it
# directly via kubectl instead.
local_resource(
  'dagster-ui-port-forward',
  serve_cmd=port_forward_cmd('fn-dev-dagster-webserver', NAMESPACE, '3000:80'),
  labels=['infrastructure'],
)
DEV_URLS.append(('Dagster', 'http://localhost:3000'))

local_resource(
  'db-internal-port-forward',
  serve_cmd=port_forward_cmd('db', NAMESPACE, '5432:5432'),
  labels=['infrastructure'],
)

local_resource(
  'gitea-port-forward',
  serve_cmd=port_forward_cmd('gitea', NAMESPACE, '4000:4000'),
  labels=['infrastructure'],
)
DEV_URLS.append(('Gitea', 'http://localhost:4000'))

# The experiments chart's database, in its own namespace and release rather than the node's.
# Waits quietly until `fncli experiment deploy` (run by `mise run deploy`) has created it.
local_resource(
  'db-datasets-port-forward',
  serve_cmd='while true; do kubectl get svc db-datasets -n experiments >/dev/null 2>&1 && ' +
            'kubectl port-forward svc/db-datasets -n experiments 5433:5432; sleep 5; done',
  labels=['infrastructure'],
)

# `mise run deploy` installs it; rerun this after adding an experiment to experiments/
local_resource(
  'experiments-deploy',
  cmd='fncli experiment deploy',
  trigger_mode=TRIGGER_MODE_MANUAL,
  auto_init=False,
  labels=['infrastructure'],
)

local_resource(
  'keycloak-port-forward',
  serve_cmd=port_forward_cmd('keycloak', 'keycloak', '8080:80'),
  labels=['infrastructure'],
)
DEV_URLS.append(('Keycloak', 'http://localhost:8080'))

local_resource(
  'deployment-check',
  cmd='kubectl get deployment nexus-api -n {ns} >/dev/null 2>&1 && echo "OK: deployments ready" || echo "MISSING: run mise run deploy"'.format(ns=NAMESPACE),
  trigger_mode=TRIGGER_MODE_MANUAL,
  labels=['infrastructure'],
)

local_resource(
  'helm-status',
  cmd='helm status {rel} -n {ns} >/dev/null 2>&1 && echo "OK: helm release {rel} deployed" || echo "MISSING: run mise run deploy"'.format(rel=RELEASE_NAME, ns=NAMESPACE),
  trigger_mode=TRIGGER_MODE_MANUAL,
  labels=['infrastructure'],
)

# ==============================================================================
# CODE LOCATION RELOAD AND DEV URLS -- keep this section last
# ==============================================================================
# Keeps the Dagster webserver's code location loaded while Tilt rebuilds or restarts the
# code server (tilt/scripts/dagster_reload.sh), and prints DEV_URLS each time it (re)loads.
# The list is read here, so a section that appends to DEV_URLS must be above this block.
DEV_URLS.append(('Tilt', 'http://localhost:10350'))

local_resource(
  'dagster-reload',
  serve_cmd='bash tilt/scripts/dagster_reload.sh {location}'.format(
    location=DAGSTER_LOCATION,
  ),
  serve_env={'DEV_URLS': '\n'.join(['- {}: {}'.format(name, url) for name, url in DEV_URLS])},
  # Start once the code server is deployed and the Dagster UI is forwarded
  resource_deps=[DAGSTER_DEPLOYMENT, 'dagster-ui-port-forward'],
  links=[link(url, name) for name, url in DEV_URLS],
  labels=['dev'],
)
