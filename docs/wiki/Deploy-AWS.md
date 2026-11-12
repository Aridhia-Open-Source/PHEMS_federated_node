# Deploy: AWS (EKS)

Not yet tested on AWS. The values below were checked against the chart's schema and render cleanly with `helm template`, but nobody has run them on EKS.

Work through [Deploy: Core](./Deploy-Core) alongside this page. The steps here are what is different on AWS: the prerequisites, EFS storage, the RDS settings, ingress and DNS, and certificates.


## Prerequisites

| You need | Why |
|---|---|
| An EKS cluster whose network plugin **enforces NetworkPolicy** (the VPC CNI with network policy enabled, Calico or Cilium) | The chart denies task pods all traffic except DNS, private address ranges and the dataset databases you list. Without enforcement that rule does nothing. |
| The **Amazon EFS CSI driver** installed on the cluster | Shared results storage. |
| An **EFS file system and an access point**, with a mount target in each subnet your nodes use | Task pods and Dagster's run pods write results to the same volume. The file system and access point must exist before you install. |
| A security group rule allowing **NFS (TCP 2049)** from your nodes to the EFS mount targets | Without it the volume never mounts. |
| An **RDS for PostgreSQL** instance (or Aurora PostgreSQL) the cluster can reach, and its master login | Holds the FN's databases. The chart creates them for you. |
| A DNS zone you can add a record to (Route 53 if you want automatic certificates) | The node needs a hostname. |

Install the Gateway API and Traefik CRDs first ([Prerequisites](./Prerequisites#install-the-gateway-api-and-traefik-crds)).


## 1. Storage: EFS

Task pods and Dagster's run pods share one **ReadWriteMany** volume. On EKS that is EFS.

Create an **access point** on the file system. It makes every pod read and write as the same user, whatever the image's own user is. In the console, set:

- Root directory path: `/files`
- Owner user ID: `1001`
- Owner group ID: `1001`
- Permissions: `777`

The user and group match `fnDagster.artifacts.securityContext` (`runAsUser` and `runAsGroup`, both 1001 by default), which is what task pods run as. If you change one, change the other.

Then set the file system and access point ids:

```yaml
storage:
  capacity: 50Gi
  aws:
    fileSystemId: fs-0123456789abcdef0
    accessPointId: fsap-0123456789abcdef0
```

**Both ids are required.** The chart's schema fails the render with `missing property 'accessPointId'` when the access point is left out. The chart builds the StorageClass (`efs.csi.aws.com`, `efs-ap` provisioning mode, directory permissions `777`) and the volumes from these two values.

See the [AWS documentation on access points](https://docs.aws.amazon.com/efs/latest/ug/create-access-point.html).


## 2. PostgreSQL: RDS

Set `db.superuser` to the master login of the instance. The default `postgres` only works if that is the name you gave it:

```yaml
db:
  host: &dbHost your-instance.xxxxxxxx.eu-west-1.rds.amazonaws.com
  port: 5432
  superuser: fn_admin          # the RDS master user
  enforceSSL: true
  secret:
    name: postgres-superuser
    key: password

dagster:
  enabled: true
  postgresql:
    postgresqlHost: *dbHost
    postgresqlParams:
      sslmode: require
```

Create the `postgres-superuser` secret as in [Deploy: Core](./Deploy-Core#3-create-the-namespace-and-the-secrets-you-must-provide). If a DBA owns the databases and you have no admin login, see [Deploy: Core](./Deploy-Core#databases). Put the instance in the cluster's VPC, and let the node security group reach port 5432 on it.


## 3. Ingress and DNS

Use the chart's Traefik (`traefik.enabled: true`). On EKS its `LoadBalancer` service gets a load balancer with a **DNS name, not an IP address**. Point your `host` at it with a `CNAME`, or an alias record in Route 53:

```sh
kubectl get svc -n federated-node -l app.kubernetes.io/name=traefik
```

Annotate the service if you want a network load balancer or an internal one. Traefik's service annotations are set under `traefik.service.annotations`.


## 4. TLS

**Bring your own certificate** (recommended until the Route 53 path below has been tested). Create the `tls` secret from [Deploy: Core](./Deploy-Core#3-create-the-namespace-and-the-secrets-you-must-provide) and set `tls.secretName`. Nothing else is needed.

**Automatic renewal with cert-manager and Route 53.** With `cert-manager.enabled: true` and `on_eks: true` the chart creates a ClusterIssuer that solves a DNS-01 challenge in Route 53 by assuming an IAM role. You create, **before** you install, a secret in the release namespace with four keys:

```sh
kubectl create secret generic aws-ssl-secret -n federated-node \
  --from-literal=EMAIL_CERT='admin@your-institution.example.com' \
  --from-literal=REGION='eu-west-1' \
  --from-literal=ACCOUNT_ID='123456789012' \
  --from-literal=ROLE_NAME='fn-cert-manager-route53'
```

`ROLE_NAME` is an IAM role with permission on your hosted zone (`route53:GetChange`, `route53:ChangeResourceRecordSets`, `route53:ListResourceRecordSets` and `route53:ListHostedZonesByName`). Its trust policy must let the service account `cert-manager-acme-dns01-route53` assume it, through your cluster's OIDC provider. The install fails at the start, naming the secret if it is missing. The chart copies it into the cert-manager namespace.

The known issues below affect this path. Read them before you choose it.


## 5. Add the AWS block to values.yaml

On top of the file from [Deploy: Core](./Deploy-Core#4-write-your-values-file), replacing its `storage` block:

```yaml
on_eks: true

storage:
  capacity: 50Gi
  aws:
    fileSystemId: fs-0123456789abcdef0
    accessPointId: fsap-0123456789abcdef0
```

With automatic certificates, add:

```yaml
cert-manager:
  enabled: true

certs:
  aws: aws-ssl-secret
```

`on_eks: true` only selects the Route 53 issuer for cert-manager. Storage is chosen by `storage.aws`, not by this flag.


## Known issues

- **The Route 53 issuer uses the Let's Encrypt staging server.** Certificates it issues are not trusted by browsers or by git hosts that verify the chain. Do not use it for production until it points at the production server.
- **The service account the issuer refers to is not created.** The ClusterIssuer asks cert-manager to act as the service account `cert-manager-acme-dns01-route53`, and the chart does not create it. Create it in the cert-manager namespace (`fn-certmanager` by default) before the install.
- **The chart's RoleBinding for that service account names the wrong subject.** It grants `serviceaccounts/token` to the service account `cert-manager` in the namespace `cert-manager`. The cert-manager subchart's service account is `<release>-cert-manager` (for example `federatednode-cert-manager`) in `fn-certmanager`, so the grant does not reach it. Confirm with `kubectl get serviceaccounts -n fn-certmanager`, and create a RoleBinding for the real one.
- **Pods stuck in `ContainerCreating` with an EFS mount error.** Almost always the security group (NFS 2049 from the nodes), a missing mount target in a node's subnet, or the EFS CSI driver not installed.
- **A dataset on a public address is blocked by default.** The task network policy only allows private address ranges. List it in `taskNetworkPolicy.datasetEgress` ([Deploy: Core](./Deploy-Core#let-tasks-reach-their-dataset)).
- **RDS refuses the connection because SSL is off.** Set `db.enforceSSL: true` *and* `dagster.postgresql.postgresqlParams.sslmode: require`. The chart refuses to render if you set only the first.


## Next step

[Post-deploy testing](./Post-Deploy-Testing)
