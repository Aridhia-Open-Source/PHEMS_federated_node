# Gitea Mirror Service

Stage m1 skeleton: Flask + SQLAlchemy + Alembic service for ADR 0020 (gitea-mirror-service).

## What it is

A minimal skeleton service that mirrors GitHub repositories into Gitea. This stage includes:

- Flask app factory with SQLAlchemy ORM
- Alembic database migrations (baseline with 5 tables)
- GET /health endpoint (checks DB connection)
- Dockerfile and requirements (pinned)
- Test runner with Postgres in Docker
- First test: /health returns 200 and migration creates all 5 tables

## Running tests

```bash
cd gitea-mirror
./run_tests.sh
```

Each test run creates its own Docker Compose project to avoid collisions with parallel runs. The test database is automatically cleaned up after each run.

## Configuration

Environment variables required for the app:

- `GITEA_MIRROR_DB_USER`: Database user
- `GITEA_MIRROR_DB_PASSWORD`: Database password
- `GITEA_MIRROR_DB_HOST`: Database host
- `GITEA_MIRROR_DB_PORT`: Database port
- `GITEA_MIRROR_DB_NAME`: Database name

## Database schema

The baseline migration creates 5 tables:

- `mirrors`: upstream repositories to mirror
- `mirror_state`: cursor and sync state per mirror
- `mirrored_pull_requests`: merged PRs replicated to Gitea
- `webhooks`: subscriptions to mirror events
- `webhook_deliveries`: delivery status and retry queue
