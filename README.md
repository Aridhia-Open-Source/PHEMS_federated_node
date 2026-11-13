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
    DataController->>Trigger: Review & Merge PR (approval gate)
    Node->>Trigger: Poll merged PRs, read the task spec
    Node->>Node: Create task, check the project, dataset and repos are allowed
    Node->>Task: Start pod in the tasks namespace, next to the dataset
    Task-->>Node: Write results to its output folder
    Node->>Results: Push results branch, open results PR
    DataController->>Results: Review & Merge results PR (release gate)
    Node->>Results: Sync PR state, record the result as merged
```

## Components

```mermaid
flowchart TD
  subgraph People["People"]
    Researcher("Researcher")
    DataController("Data Controller")
    Admin("Admin")
  end

  subgraph GitProvider["Git Provider (GitHub / Gitea)"]
    TriggerRepo("Trigger Repo")
    ResultsRepo("Results Repo")
  end

  subgraph FederatedNode["Federated Node"]
    Traefik("Traefik")

    subgraph Nexus["Nexus"]
      UI("nexus-ui")
      API("nexus-api")
    end

    Keycloak("Keycloak")
    Postgres[("Postgres")]
    Secrets("fn-secrets")

    subgraph Dagster["Dagster"]
      subgraph DagsterServices["Services"]
        Daemon("Daemon (sensors)")
        CodeServer("Code Server")
        WebServer("Web Server")
      end

      subgraph DagsterRuns["Run Pods"]
        Run1("Pod")
        Run2("Pod")
      end
    end

    subgraph TasksNamespace["tasks namespace (default-deny)"]
      Task1("Task Pod")
      Task2("Task Pod")
    end

    ResultsVolume("Results Volume")
  end

  Datasets[("Datasets")]

  Researcher -->|"task spec PR"| TriggerRepo
  DataController -->|"merges"| TriggerRepo
  DataController -->|"merges"| ResultsRepo
  Admin --> Traefik
  Traefik --> UI
  Traefik --> API
  Traefik --> Keycloak
  UI --> API
  API --> Keycloak
  API --- Postgres
  Keycloak --- Postgres
  API --- Secrets
  Daemon -->|"polls"| TriggerRepo
  Daemon --> API
  Daemon -->|"launches"| DagsterRuns
  DagsterRuns -->|"starts"| TasksNamespace
  DagsterRuns -->|"results PR"| ResultsRepo
  TasksNamespace -->|"only route out"| Datasets
  TasksNamespace --- ResultsVolume
  DagsterRuns --- ResultsVolume
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
