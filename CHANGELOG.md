# Releases Changelog

## 1.3.0
- Upgraded all python images to use `python:3.13-slim`
- Upgraded alpine image to 3.22
- Added a `taskReview` flag on the values to enable task results review before being released. Set to `false` by default.
- Results can also be delivered automatically after bein g triggered by the API call directly. The `/tasks/<id>/results` endpoint will still work.

## 1.2.0
- Added two `DELETE` enpoints for datasets and registries. Using them will remove related k8s secrets, and DB entries. In the case of datasets, dictionaries and catalogues. For registries, all related containers added either manually of via sync (manual or scheduled).
- Added support for AWS EFS persistent volume through the csi driver `efs.csi.aws.com`
    To configure it, set in the values file:
    ```yaml
    storage:
    aws:
        fileSystemId: <your EFS system ID>
        accessPointId: <Optional, access point id for better permission and isolation management in the EFS>
    ```

- Removed the option to provide db credentials in plaintext on the values file (which wasn't actively used, but it might have been misleading)

### Security
- Added the following headers to nginx:
    - `strict-transport-security`
    - `content-security-policy`
    - `referrer-policy`
    - `permission-policy`
    - `x-content-type-options`
    - `cors-allow-origin` (list of allowed hosts can be set via `.integrations.domains` in the values file. Defaults to `self`)

## 1.1.0
- Results are now delivered as a `zip` file.
- Added a `PATCH` endpoint for `/registries` so it's easier to update credentials
- Added the `active` field for registries, so outdated ones can be safely deactivated
- `db_query` field for `/tasks` POST is now optional, and its related env variables are not set if not provided
- `CONNECTION_STRING` is a new env var passed to the task pod containing info about DB connection
- The `fetch-data` init pod is conditional to the `db_query` field
- `cert-manager`'s Certificate now supports `rotationPolicy` via the `certs.rotationPolicy` field. Defaults to `Never`. The other value supported is `Always`.

### Bugfixes
- The secret for the cert manager are now automatically copied to the appropriate namespace.

## 1.0.0
- Added the Federated Node Task Controller as a chart dependency. This can be installed by setting `outboundMode` to true on the values file. By default, it won't be installed.
- Some jobs will be cleaned before and after an upgrade.
- Fixed issues with rendering nfs templates due to an extra `-`
- Multiple database engines now supported:
    - MS SQL
    - Postgres
    - MariaDB
    - MySQL
    - OracleDB
- Tasks do not need to fetch data themselves. The node will do so and mount a file called `input.csv` as default. This can be specified by the `inputs` field in the `/tasks` request. Where it will have the following format:
    ```json
    {
        "file_name": "file_path"
    }
    ```

### Bugfixes
- Issue with new user fixed due to a format mismatch

## 0.11.0
- Changed the way data is fetched from datasets, now the FN will gather it in a `csv` file and mount it to the analytics pod.
- The dataset now has an optional `schema` field, mostly for MS SQL services.
- The POST `tasks` endpoint now uses `db_query` as a new field. This is a json object with `query` and `dialect` as properties.
- POST `tasks` uses the `input` field to set where the fetched data csv file should be called and where it should be mounted. The format will be
    ```json
    {
        "file_name": "path_to_mount"
    }
    ```
- DB credentials are not passed to the task's pod anymore
- Replaced the keycloak-credential-refresh job with a re-setter one.
- Added a new value, `create_db_deployment`, only for local deployments. Defaults to `false`
- Added a weight on the nginx namespace template, as new installation might complain
- The datasets are now strictly linked to the `token_transfer` request body. A non-admin user can only trigger a task by providing the project-name they have been approved for. This will avoid inconsistencies with names and ids.
- The alpine helper image now has the same tag as the backend.

### Bugfixes
- Fixed an issue with the result cleaner where the volume mounted would include too much

## 0.10.0
**With this update, if using nginx, you will need to update your dns record to the new ingress' IP**

- Added `cert-manager` to handle SSL renewal. Set `cert-manager.enabled` in the values file to `true`.

    An example of configuration on AKS would be:
    ```yaml
    cert-manager:
        enabled: true
    certs:
        azure:
            configmap: azuredns-config
            secretName: azuredns-secret
    ```
    If not needed leave `cert-manager` and `certs` out of the values file.
- nginx is explicitly set to off. To enable it, set `ingress-nginx.enabled: true` in your values file.
- Restructured the way nginx is configured. Most of the settings were migrated to the root level from `ingress`. In detail:
    - `ingress.on_aks` moved to `on_aks`
    - `ingress.on_eks` moved to `on_eks`
    - `ingress.host` moved to `host`
    - `ingress.tls.secretName` moved to `tls.secretName`
    - `ingress.whitelist.*` moved to `whitelist.*`
    - `ingress.blacklist.*` moved to `blacklist.*`

- on AKS-based deployments would need to add:
    ```yaml
    ingress-nginx:
        controller:
            service:
                externalTrafficPolicy: Local
    ```
- nginx namespace is now defined in `ingress-nginx.namespaceOverride`
- Added the `/tasks/<task_id>/logs` to fetch a task pod's logs.
- Task's pods will not have service account tokens mounted

### Security
- Updated the nginx version to `1.12.1` to address a vulnerability

## 0.9.0
- Added a test suite for the helm chart. This can be simply run with `helm test federatednode`
- __smoketests__ can be also run if the values file contains
    ```yaml
    smoketests: true
    ```
    __Warning__ this will add and then remove the test data from keycloak and the db. It will not be enabled by default.

### Bugfixes
- Fixed a deployment issue issue with first-time installations where on azure storage, the results folder should exist already. Now this is done by the backend's initcontainer.
- Fixed a deployment issue where ingresses were not updated or deleted during upgrades
- Fixed a deployment issue when using azure storage accounts, the secret containing auth credentials is missing on the tasks namespace. This led tasks to fail to start.
- Fixed a bug where tasks always have a fixed creation date, depending on server start. That caused some of them to be deemed expired.

## 0.8.0
- Added Container and Registry management:
    - /containers
        - POST
        - GET
        - GET /id
        - PATCH /id
        - POST /sync
    - /registries
        - POST
        - GET
        - GET /id
- Removed `regcred` automatic generation, as deployments in the helm chart are all public
- Removed `registries-list.json` which was a sibling process to the `regcred`
- In the values file, the `registries` key is deprecated.

## 0.7.2
### Bugfixes
- Fixed an issue with the `needs_to_reset_password` field not being set correctly
- Fixed an issue with the reset password process where sometimes the users were incorrectly not found

## 0.7.1
### Bugfixes
- Fixed an issue with emails not being parsed correctly when special characters are included

## 0.7.0
- Added POST, GET `/users` admin-only endpoints to perform user management, and PUT `/users/reset-password` to allow users to reset their own credentials.

- Updated `jinja` and `pyjwt` dependencies due to vulnerablities found.

## 0.6.0
- Pods are now running as non-root users

- POST `/tasks` now accepts the outputs field to dynamically mount a volume so that results can be fetched correctly. If no value is provided, the default location of `/mnt/data/` will be used.

- Added PATCH /datasets/<id> endpoints, so existing datasets can be amended, or a dictionary added to them.

## 0.5.1
### Bugfixes
- Fixed an issue with TLS termination on nginx, as the two ingress order was not respected. This caused the ssl secret to be ignored as the nginx controller takes the oldest deployed ingress with the same host as valid config. In some cases `keycloak` ingress was deployed first, and by not having a secret reference, nginx would apply the k8s default cert.

## 0.5.0

- First OpenSource version!

## 0.0.8

- Added the capability to use a dataset name as an alternative to their ids

### Bugfixes

- An issue with the ingress with the path type being migrated from `Prefix` to `ImplementationSpecific`


## 0.0.7

- Helm chart values `acrs` moved to `registries`

### Bugfixes

- Fixed some issues with deploying the helm chart not respecting the desired order
- Fixed an issue with audit log causing a failure  when a request is set with `Content-Type: application/json` but no body is sent
- Added support on the `select/beacon` to query a MS SQL DB. Also the tasks involving these databses will inject credentials prefixed with `MSSQL_`


## 0.0.6

We skipped few patch numbers due to local testing on updates.

- `image` field in values files now renamed to `backend` to avoid confusion
- Keycloak service now running on port 80
- Improved the cleanup cronjob
- Added support to dynamically set the frequency the cleanup job runs on (3 days default)
- `pullPolicy` setting is on the root level of values
- Added priorities on what runs when during updates
- Expanded autid logs to include request bodies, excluding sensitive information
- Covered GitHub organization rename
- Added License file

### Bugfixes

- Some pre-upgrade jobs were not correctly detected and replaced due to a lack of labels
- Added webOrigins in Keycloak to allow token validation from both within the cluster and from outside requests
- Fixed an issue with keycloak init credential job failing during updates
- Fixed an issue with keycloak wiping all configurations and auth backbone due to a incorrect body in the init script.
- Fixed an issue where admin users were incorrectly required to provide a project name in the headers
- Fixed an issue where audit logs were not considering failed requests


## 0.0.2

- Added Task execution service
- Added Keycloak, nginx templates
- Added pipenv vulnerability checks
- Added a cronjob to cleanup old results (> 3 days)
- Finalized helm chart
- Added API docs, rachable at `/docs`
- Token life can set dynamically through the chart values `token.life`, defaults to 30 days
- Added pipelines for building docker images and helm charts, and push them to repositories
- Keycloak with inifinispan caching on the DB to keep persistency with pod restarts
- Keycloak now recreates credentials with a chart upgrade
- Added support for azure deployments with storage account configuration
- Multiple Container Registries support
- Generalized the `initContaier` section for those objects that use the DB
- Non root checks on pods
- Expanded custom exception definitions
- Created custom k8s wrapper for most used processes
- Standardized column sizes (256 for smaller inputs, 4096 for larger ones)
- Added docker-compose setup for running tests on the CI and locally
- Optional DB pod deployment (mostly for local dev)


## 0.0.1

Initial implementation
- Helm chart basic structure
- Keycloak setup
- Backend with all needed endpoints
- nginx simple configuration
