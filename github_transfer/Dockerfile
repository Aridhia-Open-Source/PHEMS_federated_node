FROM alpine:3.19

ARG USERNAME=appuser
ARG USER_UID=1001
ARG USER_GID=1001

RUN apk add --no-cache \
    bash \
    git \
    zip \
    curl \
    ca-certificates \
    github-cli

RUN addgroup -g "$USER_GID" "$USERNAME" \
    && adduser --uid "$USER_UID" --ingroup "$USERNAME" -D "$USERNAME"

WORKDIR /app
COPY --chown=${USERNAME}:${USERNAME} main.sh .

USER ${USER_UID}
ENTRYPOINT ["/bin/bash", "/app/main.sh"]
