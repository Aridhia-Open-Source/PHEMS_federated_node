FROM alpine:3.20

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

RUN addgroup -S "${USERNAME}" --gid "${USER_GID}" \
    && adduser -S "${USERNAME}" -G "${USERNAME}" -u "${USER_UID}" \
    && apk --no-cache add 'postgresql16-client=~16'

COPY --chmod=777 dbinit.sh /scripts/dbinit.sh

USER ${USER_UID}

ENTRYPOINT [ "sh", "-c", "/scripts/dbinit.sh" ]
