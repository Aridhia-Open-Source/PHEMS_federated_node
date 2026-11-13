# Deploy: AWS (EKS)

Work through [Deploy: Core](Deploy-Core.md) alongside this guide. The steps here are the AWS-specific additions to your `values.yaml` and any extra secrets to create.


## 1. Storage

The FN uses Amazon EFS (Elastic File System) to persist task results. **The EFS file system must already exist before deploying.**

You must also create an **EFS Access Point** - both `fileSystemId` and `accessPointId` are required fields. The access point ensures the FN pods mount with correct file permissions.

In the AWS console, when creating the access point set:

- Root directory path: `/files`
- Owner user ID: `1001`
- Owner group ID: `1001`
- Permissions: `777`

See the [AWS documentation on access points](https://docs.aws.amazon.com/efs/latest/ug/create-access-point.html) for full details.


## 2. TLS auto-renewal (optional)

If you want automatic SSL certificate renewal via AWS Route 53, create a secret with the required IAM role details. Values must be base64-encoded:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: aws-ssl-secret
  namespace: federated-node
data:
  EMAIL_CERT: <base64-encoded>
  REGION: <base64-encoded>
  ACCOUNT_ID: <base64-encoded>
  ROLE_NAME: <base64-encoded>
type: Opaque
```


## 3. Add the AWS block to values.yaml

Add this to your `values.yaml` (created in the core guide):

```yaml
on_eks: true

storage:
  aws:
    fileSystemId: fs-xxxxxxxxxxxxxxx
    accessPointId: fsap-xxxxxxxxxxxxxxx
```

With TLS auto-renewal:

```yaml
on_eks: true

storage:
  aws:
    fileSystemId: fs-xxxxxxxxxxxxxxx
    accessPointId: fsap-xxxxxxxxxxxxxxx

cert-manager:
  enabled: true

certs:
  aws: aws-ssl-secret
```


## 4. Deploy

Return to [Deploy: Core](Deploy-Core.md) step 8 and run `helm install` with your completed `values.yaml`.


## Next step

[Post-Deploy Testing](Post-Deploy-Testing.md)
