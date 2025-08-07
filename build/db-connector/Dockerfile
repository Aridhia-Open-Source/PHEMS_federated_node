FROM python:3.13.5-slim

# hadolint ignore=SC1070
ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

COPY pyproject.toml /

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install --no-install-recommends -y \
        libpq-dev \
        curl \
        odbcinst \
        unixodbc \
        libmariadb3 \
        libmariadb-dev \
        pkg-config \
        default-libmysqlclient-dev \
        build-essential \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv sync \
    && curl -LsSf https://packages.microsoft.com/config/debian/"$(grep VERSION_ID /etc/os-release | cut -d '"' -f 2)"/packages-microsoft-prod.deb -o packages-microsoft-prod.deb \
    && dpkg -i packages-microsoft-prod.deb \
    && rm packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install --no-install-recommends -y msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/
COPY *.py /app/
USER ${USER_UID}
ENV PYTHONPATH=/app
ENV PATH="/.venv/bin:$PATH"
ENTRYPOINT [ "python3", "-m", "connector" ]
