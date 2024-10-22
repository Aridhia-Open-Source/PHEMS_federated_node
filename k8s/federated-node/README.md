# Federated Node Helm Chart

## values file
The necessary values are:
|path|subpath|description|
|-|-|-|
|registries[]|url|This element should report the CR host that is used to host the analytics images|
|registries[].secret|name|The existing secret name that holds the CR's credentials|
|registries[].secret|userKey|The secret's key that holds the CR's username|
|registries[].secret|passKey|The secret's key that holds the CR's password/token|
|registries[]|username|The CR's username. Has lower priority than the secret|
|registries[]|password|The CR's password/token. Has lower priority than the secret.|
|-|-|-|
|storage|local|If running a cluster off the cloud, this will be the suggested config|
|storage.local|path|Where to persist files in the host machine|
|storage|azure|If running a cluster on azure, or using an Azure Storage Class, this will be the suggested config|
|storage.azure|secretName|Secret name where the credentials for the azure storage are saved|
|storage.azure|shareName|Share name within the azure storage|
|-|-|-|
|db|host|DB hostname|
|db|name|Database name|
|db|user|DB username|
|db|password|DB password (unless testing is not adviced to store passwords in plain text). Has lower priority than the secret.|
|db|secret|Secret for DB credentials|
|db.secret|key|Secret key where the password is stored|
|db.secret|name|Secret name|
|-|-|-|
|ingress|host|The URL where the FN will be hosted at|
|ingress.whitelist|enabled|Enable the whitelist of IP CIDRs|
|ingress.whitelist|ips|List of IP CIDRs|
|ingress.blacklist|enabled|Enable the whitelist of IP CIDRs|
|ingress.blacklist|ips|List of IP CIDRs|
|ingress|tls|Certificates for nginx to use to allow HTTPS. Leaving it empty or not present at all will trigger a browser warning about the connection not being secure|
|ingress.tls|secretName |Secret name where the certs are. Defaults to `tls` if the `ingress.tls` section is set|
|ingress.tls|certFile|The .cert file path. Has lower priority than the secret.|
|ingress.tls|keyFile|The .key file path. Has lower priority than the secret.|
|-|-|-|
|.|local_development|Set to `false` as default, if set to `true` it will not create the certificate cron job|
|-|-|-|
|certs|frequency|Number of days used to set the frequency of certificate refresh cronjob. This number is divided by 30, and used to run every `frequency / 30` months|
|certs.azure|sp_certificate|Set the Service Principal credentials for the DNS service, so that the certificate can be auto-renew. The credentials should be in a secret and its name should be set in the sp_certificate field. `DNS_SP_ID` `DNS_SP_SECRET` `AZ_DIRECTORY_ID` `SUBSCRIPTION_ID` are the fields needed in the secret|
|certs.aws|sp_certificate|AWS needs couple of env vars, and those should be replicated in the secret `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`|

### Existing secrets
It is highly suggested to have some secrets pre-set in the namespace this helm chart will be installed at:
- db password
- registries credentials
- azure storage credentials
- tls cert
