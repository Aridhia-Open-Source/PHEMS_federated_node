# Federated Node Helm Chart

## values file
The necessary values are:
|path|subpath|description|
|-|-|-|
|storage|capacity|How much to reserve for tasks, defaults to `10Gi`. Other possible units are `Mi`, `Ti`, `Ki`|
|storage|local|If running a cluster off the cloud, this will be the suggested config|
|storage.local|path|Where to persist files in the host machine|
|storage|azure|If running a cluster on azure, or using an Azure Storage Class, this will be the suggested config|
|storage.azure|secretName|Secret name where the credentials for the azure storage are saved|
|storage.azure|shareName|Share name within the azure storage|
|storage.aws|fileSystemId|EFS system id, e.g. fs-xxxxxxxxx|
|storage.aws|accessPointId|Optional, access point id for better permission and isolation management in the EFS|
|-|-|-|
|db|host|DB hostname|
|db|name|Database name|
|db|user|DB username|
|db|secret|Secret for DB credentials|
|db.secret|key|Secret key where the password is stored|
|db.secret|name|Secret name|
|-|-|-|
|token|life|Duration in seconds for tokens|
|-|-|-|
|integrations|domains|The list of third party host that can reach the Federated Node. Otherwise these will be blocked by CSP policies. This will not affect direct user API usage.|
|host|The URL where the FN will be hosted at|
|whitelist|enabled|Enable the whitelist of IP CIDRs|
|whitelist|ips|List of IP CIDRs|
|blacklist|enabled|Enable the whitelist of IP CIDRs|
|blacklist|ips|List of IP CIDRs|
|tls|secretName|Secret name where the SSL certificate is. Defaults to `tls` if the `tls` section is set|

### Existing secrets
It is highly suggested to have some secrets pre-set in the namespace this helm chart will be installed at:
- db password
- azure storage credentials
- tls cert
