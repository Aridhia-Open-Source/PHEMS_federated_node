![phems_logo](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/images/phems_logo_RGB_color_cropped_left%20align.JPG)
# PHEMS - Federated Node

The Federated Node runs analysis tasks next to sensitive data and lets out only results that someone has reviewed. Analytics code goes to the data, never the other way round. It deploys as a Helm chart onto Kubernetes, and was built by Aridhia as a technical partner of [PHEMS](https://phems.eu/).

## How it works

A researcher opens a pull request on a watched git repository, adding a task spec. When it is merged, the node creates a task and runs it in an isolated pod against one dataset. The results come back as a results pull request, which a reviewer merges or closes.

```mermaid
flowchart LR
    R([Researcher]) -->|"pull request"| GP[Git Provider]
    GP -->|"merged, ingested by sensor"| DG["dagster"]
    DG -->|"launches task"| TP["task pod"]
    TP -->|"results pushed"| RP["Git Provider<br/>results pull request"]
    RP --> V([Reviewer merges])
```

## Components

```mermaid
flowchart LR
    subgraph Node["Federated Node"]
        TR[Traefik]
        UI["nexus/ui"]
        API["nexus/api"]
        KC[Keycloak]
        DB[(Postgres)]
        DG["dagster"]
        subgraph Tasks["tasks namespace"]
            TP["task pods"]
            NP["default-deny network policy"]
        end
    end
    GP[Git Provider]
    DS[(Datasets)]
    TR --> UI
    TR --> API
    TR --> KC
    API --> KC
    API --> DB
    KC --> DB
    DG --> API
    DG --> DB
    DG -->|"launches"| TP
    DG <-->|"pull requests"| GP
    TP --> NP
    NP -->|"only route out"| DS
```

## Access

Keycloak signs people and programs in; nexus-api decides what each may do.

- Every account holds one of five fixed roles: `SuperUser` (recovery), `Administrator` (sets up the node), `Service` (the operator), `Users` and `Dagster`. A role is a Keycloak group under `/roles`, so a hospital can feed it from its own directory.
- What a person may do to a project or global record is a list of grants in nexus-api: `read`, `assign`, `execute`, `operate`, `write` or `manage`, for a user or a Keycloak group, optionally until a date. Every call is checked, reads included, by one reviewed Cedar policy file (`nexus/api/authz/`). Revoking applies at once.
- Install sets a first admin (`firstUserSecret`) and a break-glass superuser (`superuserSecret`).

Pages: [Sign-in and roles](docs/versions/2.x/docs/Sign-In-And-Roles.md), [Granting access](docs/versions/2.x/docs/Granting-Access.md), [Auth setup](docs/versions/2.x/docs/Auth-Setup.md). Design: ADRs [0035](project/decisions/0035-api-authorization-oidc-authentication.md), [0036](project/decisions/0036-keycloak-authentication-roles-and-system-accounts.md) and [0037](project/decisions/0037-cedar-authorization-grants-and-policies.md).

## Principles

- Pull request review is the approval: a task starts when its pull request is merged, and results leave the node only when a results pull request is merged.
- Tasks are isolated by default: each runs in its own pod in a separate namespace, and a default-deny network policy keeps it off the public internet.
- The node only pulls and reaches out. It polls the git provider and pushes results, and nothing outside has to call in to start a task.
- One record and its rules live in `nexus/api`: projects, datasets, repositories, tasks and results, and every state change. Dagster carries out what the API decides.

## Where to go next

- Deploying a node: [Deploy-Core](docs/versions/2.x/docs/Deploy-Core.md), plus the page for your platform ([Azure](docs/versions/2.x/docs/Deploy-Azure.md), [AWS](docs/versions/2.x/docs/Deploy-AWS.md), [GCP](docs/versions/2.x/docs/Deploy-GCP.md), [On-Premises](docs/versions/2.x/docs/Deploy-On-Premises.md)). Start with [Prerequisites](docs/versions/2.x/docs/Prerequisites.md).
- Running it locally: [DEPLOYMENT.md](DEPLOYMENT.md), "Run it locally".
- Who can sign in and who can do what: [Sign-in and roles](docs/versions/2.x/docs/Sign-In-And-Roles.md), [Granting access](docs/versions/2.x/docs/Granting-Access.md), [Auth setup](docs/versions/2.x/docs/Auth-Setup.md).
- Setting up a project: [MANAGEMENT.md](MANAGEMENT.md), then [Datasets](docs/versions/2.x/docs/Datasets.md) and the [Researcher guide](docs/versions/2.x/docs/Researcher-Guide.md). Git credentials are in [SETUP_GIT_APPS.md](SETUP_GIT_APPS.md).
- Contributing: [AGENTS.md](AGENTS.md) for the repo map, mise tasks and conventions, and the [decision records](project/decisions/README.md).
- Licences for the component projects: [sub-licenses](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/tree/main/sub-licenses).
