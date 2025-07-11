FROM python:3.13.2-slim

# hadolint ignore=SC1070
ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

COPY app /app
COPY migrations /migrations
COPY alembic.ini /
COPY pyproject.toml /

WORKDIR /app

RUN groupadd -g "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" "$USERNAME" \
    && chown -R "$USERNAME":"$USERNAME" /app

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install --no-install-recommends -y \
        libpq-dev \
        python3-dev \
        gcc \
        curl \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv sync \
    && PATH=$(which pg_config):$PATH \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/.venv/bin:$PATH"
USER ${USER_UID}
EXPOSE 5000
WORKDIR /
ENTRYPOINT [ "waitress-serve", "--host=0.0.0.0", "--port=5000", "--call", "app:create_app"]
