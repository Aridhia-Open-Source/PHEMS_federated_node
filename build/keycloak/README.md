# Custom Keycloak build

## Why is needed
- Azure Postgres server needs SHA-1 to be able to establish connection
- Custom entrypoint to allow bootstrap users to be created at runtime
- Build with features enabled so startup is faster
