FROM python:3.13.5-slim

COPY ./ /app
COPY ../../pyproject.toml /

ENV PYTHONDONTWRITEBYTECODE=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update \
    && apt-get install -y \
    libpq-dev \
    python3-dev \
    gcc \
    curl \
    jq \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv sync --extra dev \
    && PATH=$(which pg_config):$PATH \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/app
ENV PATH="/.venv/bin:$PATH"

WORKDIR /app
EXPOSE 5000
COPY --chmod=777 test-entrypoint.sh /app/
COPY setup.cfg /app/setup.cfg
ENTRYPOINT [ "./test-entrypoint.sh" ]
