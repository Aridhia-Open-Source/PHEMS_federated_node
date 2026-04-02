# Dagster Architecture - External Database Setup

## Before: Separate PostgreSQL Instances

```
┌─────────────────────────────────────────────────────────────────┐
│                      Kubernetes Cluster                         │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐      │
│  │         PHEMS Federated Node Components              │      │
│  │                                                      │      │
│  │  ┌──────────────┐          ┌──────────────────┐    │      │
│  │  │   Backend    │          │   PostgreSQL     │    │      │
│  │  │     API      │─────────▶│      Pod         │    │      │
│  │  └──────────────┘          │                  │    │      │
│  │                            │  Database: fndb  │    │      │
│  │                            └──────────────────┘    │      │
│  └──────────────────────────────────────────────────────┘      │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐      │
│  │              Dagster Components                      │      │
│  │                                                      │      │
│  │  ┌──────────────┐  ┌──────────────┐                │      │
│  │  │  Webserver   │  │    Daemon    │                │      │
│  │  └──────┬───────┘  └──────┬───────┘                │      │
│  │         │                 │                         │      │
│  │         └────────┬────────┘                         │      │
│  │                  ▼                                  │      │
│  │         ┌──────────────────┐                        │      │
│  │         │   PostgreSQL     │                        │      │
│  │         │      Pod         │  ◄── Separate DB!     │      │
│  │         │                  │                        │      │
│  │         │ Database: test   │                        │      │
│  │         └──────────────────┘                        │      │
│  └──────────────────────────────────────────────────────┘      │
│                                                                 │
│  Issues:                                                        │
│  • Two PostgreSQL instances = 2x resources                     │
│  • Separate backups needed                                     │
│  • More complex to manage                                      │
│  • Higher resource costs                                       │
└─────────────────────────────────────────────────────────────────┘
```

## After: Shared PostgreSQL Instance

```
┌─────────────────────────────────────────────────────────────────┐
│                      Kubernetes Cluster                         │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐      │
│  │         PHEMS Federated Node Components              │      │
│  │                                                      │      │
│  │  ┌──────────────┐                                   │      │
│  │  │   Backend    │                                   │      │
│  │  │     API      │─────────┐                         │      │
│  │  └──────────────┘         │                         │      │
│  └───────────────────────────┼──────────────────────────┘      │
│                              │                                 │
│  ┌──────────────────────────┼──────────────────────────┐      │
│  │              Dagster      │                          │      │
│  │                           │                          │      │
│  │  ┌──────────────┐  ┌──────────────┐                │      │
│  │  │  Webserver   │  │    Daemon    │                │      │
│  │  └──────┬───────┘  └──────┬───────┘                │      │
│  │         │                 │                         │      │
│  │         └────────┬────────┘                         │      │
│  └──────────────────┼──────────────────────────────────┘      │
│                     │                                          │
│        ┌────────────┴────────────┐                            │
│        ▼                         ▼                            │
│  ┌──────────────────────────────────────┐                     │
│  │      Shared PostgreSQL Pod           │                     │
│  │                                      │                     │
│  │  ┌────────────────┐ ┌──────────────┐│                     │
│  │  │  Database:     │ │ Database:    ││                     │
│  │  │     fndb       │ │ dagster_db   ││                     │
│  │  │                │ │              ││                     │
│  │  │ (FN tables)    │ │(Dagster tabs)││                     │
│  │  └────────────────┘ └──────────────┘│                     │
│  │                                      │                     │
│  │  Benefits:                           │                     │
│  │  • Same PostgreSQL instance          │                     │
│  │  • Separate databases for isolation  │                     │
│  │  • Single backup process             │                     │
│  │  • Reduced resource usage            │                     │
│  └──────────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

## Component Connections

```
┌────────────────────┐
│  Dagster Webserver │
│  (User Interface)  │
└─────────┬──────────┘
          │
          │ reads/writes
          ▼
┌──────────────────────┐
│  PostgreSQL Server   │
│                      │
│  ┌────────────────┐  │
│  │  dagster_db    │  │  ◄── Dagster storage
│  │                │  │      • Runs
│  │  Tables:       │  │      • Event logs
│  │  - runs        │  │      • Job configs
│  │  - event_logs  │  │      • Schedules
│  │  - jobs        │  │      • Sensors
│  │  - schedules   │  │      • Asset keys
│  │  - sensors     │  │
│  │  - assets      │  │
│  │  (and more)    │  │
│  └────────────────┘  │
│                      │
│  ┌────────────────┐  │
│  │     fndb       │  │  ◄── Federated Node storage
│  │                │  │      • FN tables
│  │  (FN tables)   │  │      • Unchanged
│  └────────────────┘  │
└──────────────────────┘
          ▲
          │ reads/writes
          │
┌─────────┴──────────┐
│  Dagster Daemon    │
│  (Background jobs) │
└────────────────────┘
```

## Configuration Flow

```
values.yaml
    │
    ├─► db.host: "postgres-service"  ───────┐
    ├─► db.user: "test"  ────────────────┐  │
    ├─► db.secret: "backend-secrets"  ─┐ │  │
    │                                  │ │  │
    └─► dagster.postgresql:           │ │  │
        ├─ enabled: false  ◄─── Disable subchart
        └─ postgresqlHost: ──────────────┼──┼─► Connect to
           postgresqlUser: ──────────────┼──┘   existing DB
           postgresqlDatabase: "dagster_db"
           postgresqlSecretName: ────────┘

            │
            ▼
    ┌────────────────────────┐
    │  dagster-env-config    │
    │     ConfigMap          │
    │                        │
    │  DAGSTER_POSTGRES_HOST │
    │  DAGSTER_POSTGRES_USER │
    │  DAGSTER_POSTGRES_DB   │
    └────────────────────────┘
            │
            ▼
    ┌────────────────────────┐
    │   backend-secrets      │
    │       Secret           │
    │                        │
    │     PGPASSWORD         │
    └────────────────────────┘
            │
            ▼
    ┌────────────────────────┐
    │   Dagster Pods         │
    │  (use environment      │
    │   variables to         │
    │   connect to DB)       │
    └────────────────────────┘
```

## Network Flow

```
┌──────────────┐
│   Browser    │
└──────┬───────┘
       │ HTTP
       │ (port 8080)
       ▼
┌──────────────────────┐
│  Dagster Webserver   │
│  Service             │
└──────────┬───────────┘
           │
           │ Queries DB
           │ (port 5432)
           ▼
┌──────────────────────┐
│  PostgreSQL Service  │
│  postgres-service    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  PostgreSQL Pod      │
│                      │
│  fndb + dagster_db   │
└──────────────────────┘
```

## Data Isolation

```
PostgreSQL Server
├── Database: fndb (existing)
│   ├── Table: users
│   ├── Table: tasks
│   ├── Table: results
│   └── ... (Federated Node tables)
│
└── Database: dagster_db (new)
    ├── Table: runs
    ├── Table: event_logs
    ├── Table: jobs
    ├── Table: schedules
    ├── Table: sensors
    ├── Table: asset_keys
    └── ... (Dagster tables)

Note: Complete isolation between databases
      • No cross-database queries
      • Separate permissions possible
      • Independent backup/restore
      • Different schemas
```

## Deployment Sequence

```
1. Prepare
   ├─► Identify DB connection details
   ├─► Create dagster_db database
   └─► Backup existing data

2. Configure
   ├─► Update values.yaml
   │   ├─► Set db.host
   │   ├─► Set db.user
   │   ├─► Disable postgresql subchart
   │   └─► Configure connection
   │
   └─► Create dagster-env-configmap.yaml

3. Deploy
   ├─► helm upgrade federated-node
   ├─► Wait for pods to start
   └─► Check no PostgreSQL pod created

4. Validate
   ├─► Run validation script
   ├─► Check pod status
   ├─► Verify database tables
   ├─► Test Dagster UI
   └─► Execute test run

5. Monitor
   ├─► Check logs
   ├─► Monitor resources
   ├─► Verify connections
   └─► Document configuration
```

## Secret Flow

```
Option 1: Using Existing Secret (Recommended)
┌──────────────────────────┐
│  backend-secrets         │
│  (existing secret)       │
│                          │
│  PGPASSWORD: <base64>    │
└──────────┬─────────��─────┘
           │
           │ Referenced by
           │
           ├──────────────┐
           │              │
           ▼              ▼
┌────────────────┐  ┌─────────────────┐
│  Backend Pod   │  │  Dagster Pods   │
│  (uses for     │  │  (uses for      │
│   fndb)        │  │   dagster_db)   │
└────────────────┘  └─────────────────┘

Option 2: Separate Secrets
┌──────────────────────────┐
│  backend-secrets         │
│  PGPASSWORD: <base64>    │
└──────────┬───────────────┘
           │
           ▼
┌────────────────┐
│  Backend Pod   │
└────────────────┘

┌──────────────────────────┐
│  dagster-postgresql-     │
│  secret                  │
│  postgresql-password:... │
└──────────┬───────────────┘
           │
           ▼
┌─────────────────┐
│  Dagster Pods   │
└─────────────────┘
```

## Troubleshooting Flow

```
Problem: Pods CrashLoopBackOff
    │
    ├─► Check logs
    │   └─► kubectl logs <pod> --previous
    │
    ├─► Verify DB connection
    │   ├─► Is postgresqlHost correct?
    │   ├─► Does dagster_db exist?
    │   └─► Are credentials correct?
    │
    └─► Fix and redeploy
        └─► kubectl rollout restart deployment

Problem: Database not found
    │
    ├─► Connect to PostgreSQL
    │   └─► kubectl exec -it <db-pod> -- psql
    │
    ├─► Create database
    │   └─► CREATE DATABASE dagster_db;
    │
    └─► Restart Dagster pods
        └─► kubectl delete pods -l app=dagster

Problem: Connection refused
    │
    ├─► Check service exists
    │   └─► kubectl get svc | grep postgres
    │
    ├─► Verify service name in values.yaml
    │   └─► postgresqlHost: "postgres-service"
    │
    └─► Test DNS resolution
        └─► kubectl exec <pod> -- nslookup postgres-service
```

## Resource Comparison

```
Before (Separate DB):
┌─────────────────────────────┐
│  PostgreSQL for FN          │
│  CPU: 500m  Memory: 512Mi   │  Total: 1 CPU
└─────────────────────────────┘  Total: 1Gi RAM

┌─────────────────────────────┐
│  PostgreSQL for Dagster     │
│  CPU: 500m  Memory: 512Mi   │
└─────────────────────────────┘

After (Shared DB):
┌─────────────────────────────┐
│  PostgreSQL (Shared)        │
│  CPU: 750m  Memory: 768Mi   │  Total: 750m CPU
│                             │  Total: 768Mi RAM
│  ├─ fndb                    │
│  └─ dagster_db              │  25% resource savings!
└─────────────────────────────┘
```

---

## Key Takeaways

1. **Single PostgreSQL Instance**: One database server, multiple databases
2. **Data Isolation**: Completely separate databases (`fndb` vs `dagster_db`)
3. **Shared Credentials**: Can use same user/password for both databases
4. **No PostgreSQL Subchart**: Dagster's PostgreSQL chart is disabled
5. **Simplified Management**: Single backup, monitoring, and maintenance point
6. **Resource Efficiency**: ~25% reduction in database resources
7. **Same Functionality**: Dagster works identically, just uses external DB

---

See other documentation files for detailed setup instructions.
