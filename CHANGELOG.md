# Releases Changelog

## 0.9.0
- Added the Federated Node Task Controller as a chart dependency. This can be installed by setting `outboundMode` to true on the values file. By default, it won't be installed.
- Added a test suite for the helm chart. This can be simply run with `helm test federatednode`
- __smoketests__ can be also run if the values file contains
    ```yaml
    smoketests: true
    ```
    __Warning__ this will add and then remove the test data from keycloak and the db. It will not be enabled by default.

### bugfixes
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
