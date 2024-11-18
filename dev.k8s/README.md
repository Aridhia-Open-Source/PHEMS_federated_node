# Development resources

**WARNING**: _All the k8s templates in here are not meant to be run in a production environment_

Any of them can be deployed with
```sh
kubectl apply -f dev.k8s/deployment/db.yaml
```
or all of them with
```sh
kubectl apply -f dev.k8s/
```


List of templates:
- [db.yaml](./deployments/db.yaml)

    Aims to emulate an external database with Postgres as engine. It uses a persistent volume using local storage.

- [mssql.yaml](./deployments/mssql.yaml)

    Aims to emulate an external database with Miscrosoft SQL as engine. It uses a persistent volume using local storage.
