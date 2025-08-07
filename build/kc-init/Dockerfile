FROM python:3.13.5-slim

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

WORKDIR /scripts

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install --no-install-recommends -y curl \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv init \
    && /root/.local/bin/uv add requests \
    && groupadd -g "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" "$USERNAME" \
    && chown -R "$USERNAME":"$USERNAME" /scripts \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY *.py /scripts/
ENV PATH="/.venv/bin:$PATH"
USER ${USER_UID}
ENTRYPOINT [ "/bin/sh", "-c", "python3 /scripts/setup_realm.py" ]
