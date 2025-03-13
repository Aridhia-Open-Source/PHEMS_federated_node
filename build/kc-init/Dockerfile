FROM python:3.12.1-slim-bullseye

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

WORKDIR /scripts

# hadolint detects pipenv as another invocation of pip
# hadolint ignore=DL3013,DL3008
RUN apt-get update \
    && apt-get upgrade -y \
    && python -m pip install --no-cache-dir requests \
    && groupadd -g "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" "$USERNAME" \
    && chown -R "$USERNAME":"$USERNAME" /scripts \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY *.py /scripts/

USER ${USER_UID}
ENTRYPOINT [ "/bin/sh", "-c", "python3 /scripts/refresh_credentials.py" ]
