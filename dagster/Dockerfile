FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git && \
    rm -rf /var/lib/apt/lists/*

# setup the dagster home directory
ENV DAGSTER_HOME=/opt/dagster/home
WORKDIR $DAGSTER_HOME

# Install locked third-party deps, the client's included (scripts/pip_compile.sh compiles both pyprojects)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The shared nexus-api client, from the nexus-client named build context (docker-bake.hcl).
# Editable and at its repo path next to DAGSTER_HOME, so Tilt syncs into it and the tests find ../nexus/client/tests.
# hadolint ignore=DL3022
COPY --from=nexus-client . /opt/dagster/nexus/client
RUN pip install --no-cache-dir --no-deps -e /opt/dagster/nexus/client

# Copy package source (uses .dockerignore to limit scope)
COPY . .

# Install package code in editable mode; its dependencies are all in requirements.txt
RUN pip install --no-cache-dir --no-deps -e . && pip check

ENV PYTHONUNBUFFERED=1
EXPOSE 80
