FROM python:3.13.5-slim

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq-dev \
        odbcinst \
        unixodbc \
        libmariadb3 \
        libmariadb-dev \
        pkg-config \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install MSSQL ODBC driver
RUN DEBIAN_VERSION=$(grep VERSION_ID /etc/os-release | cut -d '"' -f 2) \
    && MSSQL_PROD_URL="https://packages.microsoft.com/config/debian/${DEBIAN_VERSION}/packages-microsoft-prod.deb" \
    && curl -LsSf "${MSSQL_PROD_URL}" -o packages-microsoft-prod.deb \
    && dpkg -i packages-microsoft-prod.deb \
    && rm packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install --no-install-recommends -y msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN groupadd -g "$USER_GID" "$USERNAME" && \
    useradd --uid "$USER_UID" --gid "$USER_GID" --create-home "$USERNAME"

# Copy application code with correct ownership
COPY --chown=${USER_UID}:${USER_GID} *.py .

USER ${USER_UID}

ENV PYTHONPATH=/app

ENTRYPOINT ["python3", "-m", "connector"]