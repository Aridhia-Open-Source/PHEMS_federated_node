# Federated Node Helm Chart

## values file
The necessary values are:
|path|subpath|description|
|-|-|-|
|acrs[]|url|This element should report the ACR host that is used to host the analytics images|
|acrs[].secret|name|The existing secret name that holds the ACR's credentials|
|acrs[].secret|userKey|The secret's key that holds the ACR's username|
|acrs[].secret|passKey|The secret's key that holds the ACR's password/token|
|acrs[]|username|The ACR's username. Has lower priority than the secret|
|acrs[]|password|The ACR's password/token. Has lower priority than the secret.|
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

### Existing secrets
It is highly suggested to have some secrets pre-set in the namespace this helm chart will be installed at:
- db password
- acr credentials
- azure storage credentials
- tls cert
