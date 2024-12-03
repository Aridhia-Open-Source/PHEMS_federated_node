FROM python:3.12.1-slim-bullseye

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

WORKDIR /scripts

RUN apt-get update \
    && apt-get upgrade -y \
    && python -m pip install requests \
    && groupadd -g "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" "$USERNAME" \
    && chown -R "$USERNAME":"$USERNAME" /scripts

ADD *.py /scripts/

USER ${USER_UID}
ENTRYPOINT [ "/bin/sh", "-c", "python3 /scripts/init_credentials.py" ]
