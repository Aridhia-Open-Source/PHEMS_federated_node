FROM alpine/k8s:1.29.4


ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

RUN addgroup -S "${USERNAME}" --gid "${USER_GID}" \
    && adduser -S "${USERNAME}" -G "${USERNAME}" -u "${USER_UID}"

COPY --chmod=777 cleanup.sh /scripts/

USER ${USER_UID}

ENTRYPOINT [ "/bin/sh", "-c", "/scripts/cleanup.sh" ]
