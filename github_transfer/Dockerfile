FROM alpine:3.19

ARG APP_USER=appuser
ARG USER_UID=1001
ARG USER_GID=1001

WORKDIR /app

RUN apk add --no-cache \
    bash \
    git \
    zip \
    curl \
    ca-certificates \
    github-cli

RUN addgroup -g "$USER_GID" "$APP_USER" \
    && adduser --uid "$USER_UID" --ingroup "$APP_USER" -D "$APP_USER"

COPY --chown=${APP_USER}:${APP_USER} . .

USER ${USER_UID}
ENTRYPOINT ["/bin/bash", "/app/main.sh"]
