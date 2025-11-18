FROM alpine/k8s:1.33.2

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

RUN addgroup -S "${USERNAME}" --gid "${USER_GID}" \
    && adduser -S "${USERNAME}" -G "${USERNAME}" -u "${USER_UID}"

RUN apk add --no-cache \
    'postgresql16-client=~16' && \
    python3 -m venv /venv && \
    /venv/bin/python3 -m pip install kubernetes requests

ENV PATH=/venv/bin:$PATH

USER ${USER_UID}

COPY --chmod=755 sync-cron.sh /usr/bin/sync-registry
COPY --chmod=755 cleanup.sh /usr/bin/cleanup
COPY --chmod=755 dbinit.sh /usr/bin/dbinit
COPY --chmod=755 keycloak-reset.sh /usr/bin/keycloak-reset
COPY --chmod=755 migrate-docker-secret.py /usr/bin/migrate-docker-secret
