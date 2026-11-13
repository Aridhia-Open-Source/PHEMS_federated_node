# Federated Node - Documentation

This documentation covers deploying, configuring, testing, and using the PHEMS Federated Node (FN).

## What is the Federated Node?

The Federated Node lets researchers run analytical tasks against sensitive datasets **without the data ever leaving your institution**. Analytics code (packaged as a Docker container) is sent to the data - not the other way around. Results are returned to the researcher after running locally inside your cluster.

It is built on the [ICODA Common API](https://github.com/federated-data-sharing/common-api) standard and deploys as a Helm chart onto a Kubernetes cluster.

Core components bundled in the chart:

- **Flask/Python backend** - the FN API
- **Keycloak** - authentication and role-based access control
- **Traefik** - reverse proxy and ingress (recommended for production)
- **PostgreSQL** - FN metadata (users, datasets, tasks, audit logs) - you provide this externally


## Where to start

**Understanding how it fits together:** [Architecture Overview](Architecture.md) covers the components, how Keycloak is wired in, the namespace and pod layout, and the database and firewall decisions you need to make yourself.

**Deploying for the first time:** [Prerequisites](Prerequisites.md), then your platform deploy guide, then [Post-Deploy Testing](Post-Deploy-Testing.md).

**Joining an existing federated network / outbound-only mode:** The network operator will have told you to use the Task Controller. Complete your deployment first, then head to the [Task Controller wiki](https://github.com/Aridhia-Open-Source/federated-node-task-controller/wiki).

**Building an analytics container:** [Analytics Container Development](Analytics-Container-Development.md) covers the environment variables, base images, and output contract.

**Giving a researcher access to run tasks:** [User Roles](User-Roles.md) then [Using the API](Using-The-API.md) for the dataset permissions call.
