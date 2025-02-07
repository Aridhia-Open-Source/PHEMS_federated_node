FROM alpine/k8s:1.29.4

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

RUN addgroup -S "${USERNAME}" --gid "${USER_GID}" \
    && adduser -S "${USERNAME}" -G "${USERNAME}" -u "${USER_UID}"

RUN apk add --update sudo jq curl

USER $USER_UID
COPY --chmod=755 sync-cron.sh /usr/bin/sync-registry
COPY --chmod=755 cleanup.sh /usr/bin/cleanup
