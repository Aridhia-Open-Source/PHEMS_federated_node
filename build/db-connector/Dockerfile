FROM python:3.12

# hadolint ignore=SC1070
ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

ENV DEBIAN_FRONTEND=noninteractive

# hadolint ignore=DL3013,DL3008
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install --no-install-recommends -y \
        unixodbc \
        krb5-user \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        pyodbc mariadb "sqlglot[rs]" sqlalchemy psycopg2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY connector.py /app/
COPY --chmod=777 entrypoint.sh /app/

USER ${USER_UID}
ENTRYPOINT [ "/app/entrypoint.sh" ]
