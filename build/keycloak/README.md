# Custom Keycloak build

### Issue
During testing we have found out that on cluster restart/re-deployment the user session is not valid even if the user's token `exp` date is in the future.

The root cause is the caching system on KC which is very volatile, and doesn't use the DB by default.

### Solution
In order to switch to DB sessions, we need to use `infinispan`. The version installed in `quay.io/keycloak/keycloak:23.0.4` is 14.0.21. By injecting a custom config ([cache-ispn.xml](./cache-ispn.xml)) we tell infinispan to create a db connection to a postgres server, create a table, and use it to track sessions.

The DB will be the same as what Keycloak uses for its general use.

As additional measure the helm chart hardcodes 2 replicas for Keycloak StatefulSet, as single-pod setup will preserve part of the session, leaving the client blank, and effectively not evaluating the non-expired token as invalid.

### Dependencies
`infinispan` is not ready to use postgres DBs, so few dependencies need to be downloaded and injected in the lib folder (`/opt/keycloak/providers`), and keycloak will be able to append them at runtime.

The 2 dependencies needed are:
| Library | Version |
| ------- | ------- |
|infinispan-cachestore-jdbc|14.0.27|
|infinispan-cachestore-jdbc-common-jakarta|14.0.27|

They will be downloaded from maven repo, and their versions need to be kept the same, or a mismatch will happen resulting in errors like
```
ERROR [org.keycloak.quarkus.runtime.cli.ExecutionExceptionHandler] (main) ERROR: 'void org.infinispan.persistence.jdbc.common.configuration.AbstractJdbcStoreConfiguration.<init>(java.lang.Enum, org.infinispan.commons.configuration.attributes.AttributeSet, org.infinispan.configuration.cache.AsyncStoreConfiguration, org.infinispan.persistence.jdbc.common.configuration.ConnectionFactoryConfiguration)'
```
