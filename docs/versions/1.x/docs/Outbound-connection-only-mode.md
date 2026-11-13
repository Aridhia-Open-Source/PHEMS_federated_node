# Outbound Connection Only Mode

If your cluster cannot accept inbound connections from researchers, or if you are joining a federated network that requires a standardised task submission workflow, the Federated Node can run in **outbound mode** using the Federated Node Task Controller (FNTC).

In outbound mode, researchers do not call the FN API directly. Instead, they submit tasks via a GitHub repository. The Task Controller monitors that repository and - from inside your cluster - calls the FN API internally when a task is submitted, then pushes results back to GitHub when the task completes.


## Enabling outbound mode

The Task Controller is bundled as a subchart in the FN Helm chart. Enable it by adding to your `values.yaml`:

```yaml
outboundMode: true
```

Additional configuration for the Task Controller goes under `fn-task-controller`. A minimal example:

```yaml
outboundMode: true

fn-task-controller:
  storage:
    local:
      path: /data/controller

  idp:
    github:
      secret_name: myorg-my-task-repo
      secret_key: GH_SECRET
      clientid_key: GH_CLIENT_ID
      orgAndRepo: MyOrg/My-Task-Repo

  delivery:
    github:
      repository: MyOrg/My-Task-Repo
```

See the [Helm Values Reference](Helm-Values-Reference.md) for all `fn-task-controller` configuration options.


## Full setup guide

Complete setup documentation is in the [Task Controller wiki](https://github.com/Aridhia-Open-Source/federated-node-task-controller/wiki):

- [Overview](https://github.com/Aridhia-Open-Source/federated-node-task-controller/wiki) - how the Task Controller works and when to use it
- [GitHub Setup](https://github.com/Aridhia-Open-Source/federated-node-task-controller/wiki/GitHub-Setup) - create the GitHub App, repository, and Actions pipeline
- [Deploy](https://github.com/Aridhia-Open-Source/federated-node-task-controller/wiki/Deploy) - configure and deploy the controller
- [Running Tasks](https://github.com/Aridhia-Open-Source/federated-node-task-controller/wiki/Running-Tasks) - how researchers submit tasks and retrieve results
