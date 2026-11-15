# Lint and test image: the locked deps plus the dev extras. The repo is mounted at /app at run time and
# PYTHONPATH finds the operator and the shared client (nexus/client), so no named build context is needed.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /opt/nexus/operator

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Dev extras (pytest, pytest-mock, pylint); the package itself comes from the mounted repo
COPY nexus_operator nexus_operator
RUN pip install --no-cache-dir ".[dev]"
