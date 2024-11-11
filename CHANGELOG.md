# Releases Changelog

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
- Expanded autid logs to include request bodies, excluding sensitive informations
- Covered GitHub organization rename
- Added License file

### Bugfixes

- Some pre-upgrade jobs were not correctly detected and be replaced due to a lack of labels
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