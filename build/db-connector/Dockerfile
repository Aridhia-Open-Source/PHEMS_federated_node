FROM python:3.12

# hadolint ignore=SC1070
ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

# hadolint ignore=DL3013,DL3008
RUN apt-get update \
    && apt-get upgrade -y \
    && apt install -y libpq-dev wget odbcinst unixodbc \
    && pip install --upgrade pip \
    && python3 -m pip install --no-cache-dir \
        pyodbc oracledb mariadb "sqlglot[rs]" sqlalchemy mysqlclient psycopg2 \
    && wget -q https://packages.microsoft.com/config/debian/$(grep VERSION_ID /etc/os-release | cut -d '"' -f 2 | cut -d '.' -f 1)/packages-microsoft-prod.deb \
    && yes | dpkg -i packages-microsoft-prod.deb \
    && rm packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/
COPY *.py /app/

USER ${USER_UID}
ENV PYTHONPATH=/app
ENTRYPOINT [ "python3", "-m", "connector" ]
