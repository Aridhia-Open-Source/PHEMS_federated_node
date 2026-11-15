FROM python:3.12-slim

ARG APP_USER=fednode
ARG USER_UID=1001
ARG USER_GID=1001

# Owns the code, so Tilt can sync into it as the container user
RUN groupadd -g "$USER_GID" "$APP_USER" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" "$APP_USER"

WORKDIR /opt/nexus/operator

# Locked third-party deps, the client's included (scripts/pip_compile.sh compiles both pyprojects)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The shared nexus-api client, from the nexus-client named build context (docker-bake.hcl).
# Editable at its repo path next to the operator, so Tilt syncs into it.
# hadolint ignore=DL3022
COPY --from=nexus-client --chown=${USER_UID}:${USER_GID} . /opt/nexus/client
RUN pip install --no-cache-dir --no-deps -e /opt/nexus/client

COPY --chown=${USER_UID}:${USER_GID} . .
RUN pip install --no-cache-dir --no-deps -e . && pip check

USER ${USER_UID}

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["kopf", "run", "-m", "nexus_operator.main", "--standalone", "--liveness=http://0.0.0.0:8080/healthz"]
