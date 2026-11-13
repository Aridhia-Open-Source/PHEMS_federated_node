![phems_logo](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/images/phems_logo_RGB_color_cropped_left%20align.JPG)
# PHEMS - Federated Node

The Federated Node runs analysis tasks next to sensitive data and lets out only results that someone has reviewed. Analytics code goes to the data, never the other way round. It deploys as a Helm chart onto Kubernetes, and was built by Aridhia as a technical partner of [PHEMS](https://phems.eu/).

## How it works

A researcher opens a pull request on a watched git repository, adding a task spec. When it is merged, the node creates a task and runs it in an isolated pod against one dataset. The results come back as a results pull request, which a reviewer merges or closes.

```mermaid
sequenceDiagram
    participant Researcher
    participant Trigger as Trigger Repo
    participant DataController as Data Controller
    participant Node as Federated Node
    participant Task as Task Pod
    participant Results as Results Repo

    Researcher->>Trigger: Raise PR (task spec: image + dataset)
    DataController->>Trigger: Approve PR
    DataController->>Trigger: Merge PR
    Node->>Trigger: Poll merged PRs, read the task spec
    Node->>Node: Create task, check the project, dataset and repos are allowed
    Node->>Task: Start pod in the tasks namespace, next to the dataset
    Task-->>Node: Write results to its output folder
    Node->>Results: Push results branch, open Results PR
    DataController->>Results: Approve Results PR
    DataController->>Results: Merge Results PR
    Node->>Results: Sync PR state, record the result as merged
```

## Components

```mermaid
flowchart LR
  subgraph People["People"]
    direction TB
    Researcher("Researcher")
    DataController("Data Controller")
    Admin("Admin")
  end

  subgraph GitProvider["Git Provider"]
    direction TB
    TriggerRepo("Trigger Repo")
    ResultsRepo("Results Repo")
  end

  subgraph FederatedNode["Federated Node"]
    direction TB
    subgraph Control["Control"]
      direction LR
      Traefik("Traefik") --> Nexus("nexus-ui + nexus-api") --> Keycloak("Keycloak")
      Nexus --- Postgres[("Postgres")]
    end
    subgraph Dagster["Dagster"]
      direction LR
      Daemon("Daemon (sensors)") --> RunPods("Run Pods")
    end
    subgraph Tasks["tasks namespace"]
      TaskPods("Task Pods")
    end
    Daemon --> Nexus
    RunPods --> TaskPods
  end

  subgraph Institution["Institution Network"]
    Datasets[("Datasets")]
  end

  Researcher -->|"Trigger PR"| TriggerRepo
  DataController -->|"merges PRs"| GitProvider
  Admin --> Traefik
  Daemon -.->|"polls"| TriggerRepo
  RunPods -.->|"Results PR"| ResultsRepo
  TaskPods --> Datasets
```

## Principles

- Pull request review is the approval: a task starts when its pull request is merged, and results leave the node only when a results pull request is merged.
- Tasks are isolated by default: each runs in its own pod in a separate namespace, and a default-deny network policy keeps it off the public internet.
- The node only pulls and reaches out. It polls the git provider and pushes results, and nothing outside has to call in to start a task.
- One record and its rules live in `nexus/api`: projects, datasets, repositories, tasks and results, and every state change. Dagster carries out what the API decides.

## Where to go next

- Deploying a node: [Deploy-Core](docs/versions/2.x/docs/Deploy-Core.md), plus the page for your platform ([Azure](docs/versions/2.x/docs/Deploy-Azure.md), [AWS](docs/versions/2.x/docs/Deploy-AWS.md), [GCP](docs/versions/2.x/docs/Deploy-GCP.md), [On-Premises](docs/versions/2.x/docs/Deploy-On-Premises.md)). Start with [Prerequisites](docs/versions/2.x/docs/Prerequisites.md).
- Running it locally: [DEPLOYMENT.md](DEPLOYMENT.md), "Run it locally".
- Setting up a project: [MANAGEMENT.md](MANAGEMENT.md), then [Datasets](docs/versions/2.x/docs/Datasets.md) and the [Researcher guide](docs/versions/2.x/docs/Researcher-Guide.md). Git credentials are in [SETUP_GIT_APPS.md](SETUP_GIT_APPS.md).
- Contributing: [AGENTS.md](AGENTS.md) for the repo map, mise tasks and conventions, and the [decision records](project/decisions/README.md).
- Licences for the component projects: [sub-licenses](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/tree/main/sub-licenses).
